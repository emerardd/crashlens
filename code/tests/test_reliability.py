import json
import sqlite3
import subprocess
import sys
import time

import psutil
import pytest

from crashlens.engine import create_job, run_job
from crashlens.generators import generate
from crashlens.manager import Manager
from crashlens.store import Store


def prepare(make_target, source="import sys\nsys.stdin.buffer.read()\n"):
    root, config = make_target(source)
    (root / "seeds").mkdir()
    (root / "seeds" / "normal.bin").write_bytes(b"good")
    config.fuzz.max_cases = 20
    return root, config


@pytest.mark.parametrize("failure", ["missing_script", "reject_baseline", "missing_module"])
def test_regression_environment_failure_is_inconclusive(make_target, tmp_path, failure):
    root, config = prepare(make_target, "raise SystemExit(2)\n")
    if failure == "missing_script":
        config.target.command[1] = "missing_entry.py"
    elif failure == "missing_module":
        config.target.command = ["{python}", "-m", "crashlens_nonexistent_test_module"]
    store = Store(tmp_path / "data")
    job = create_job(store, str(root), config.model_dump(),
                     {"kind": "regression", "signature": "original", "data": b"bad"})
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == "failed"
    assert result["executed"] == 0
    assert result["finding_count"] == 0
    assert result["comparison"]["verdict"] == "inconclusive"
    assert result["comparison"]["same_failure"] is None
    assert (store.folder(job["id"]) / "baseline-error.json").exists()


@pytest.mark.parametrize("code,verdict", [(0, "handled"), (2, "handled"), (7, "different_failure")])
def test_regression_preserves_legitimate_rejection(make_target, tmp_path, code, verdict):
    root, config = prepare(make_target,
        f"import sys\nraise SystemExit(0 if sys.stdin.buffer.read() == b'good' else {code})\n")
    store = Store(tmp_path / "data")
    job = create_job(store, str(root), config.model_dump(),
                     {"kind": "regression", "signature": "original", "data": b"bad"})
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == "completed", result["error"]
    assert result["comparison"]["verdict"] == verdict
    assert result["comparison"]["result"]["returncode"] == code


def test_surrogate_json_seed_does_not_fail_job(make_target, tmp_path):
    root, config = prepare(make_target)
    (root / "seeds" / "normal.bin").write_bytes(b'{"text":"\\ud800"}')
    store = Store(tmp_path / "data")
    job = create_job(store, str(root), config.model_dump())
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == "completed", result["error"]
    assert result["executed"] == 20
    assert result["counts"] == {"passed": 20}


def test_deep_json_and_binary_seeds_continue_byte_mutations():
    seeds = [b"[" * 2000 + b"0" + b"]" * 2000, b"\xff\x00"]
    cases = list(generate(seeds, 30, 42, 8192))
    assert len(cases) == 30
    assert any(strategy == "byte-mutation" for strategy, _ in cases)


def test_store_closes_connections_and_rolls_back(tmp_path, monkeypatch):
    connections = []
    original = sqlite3.connect
    def connect(*args, **kwargs):
        con = original(*args, **kwargs)
        connections.append(con)
        return con
    monkeypatch.setattr(sqlite3, "connect", connect)
    store = Store(tmp_path / "data")
    store.put({"id": "one"})
    for _ in range(40):
        assert store.get("one") == {"id": "one"}
        assert len(store.list()) == 1
    with pytest.raises(RuntimeError):
        with store.connect() as con:
            con.execute("DELETE FROM jobs")
            raise RuntimeError("rollback")
    assert store.get("one") == {"id": "one"}
    for con in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            con.execute("SELECT 1")


def test_recovery_includes_jobs_older_than_history_limit(tmp_path):
    store = Store(tmp_path / "data")
    store.put({"id": "old", "state": "running"})
    for i in range(201):
        store.put({"id": str(i), "state": "completed"})
    manager = Manager(store.home)
    assert store.get("old")["state"] == "interrupted"
    manager.close()


def alive(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_server_death_stops_worker_and_target_tree(make_target, tmp_path):
    root, config = prepare(make_target,
        "import subprocess, sys, os, json, time\nfrom pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "Path('target-pids.json').write_text(json.dumps([os.getpid(), child.pid]), encoding='utf-8')\n"
        "time.sleep(30)\n")
    config.target.timeout_seconds = 30
    home = tmp_path / "data"
    settings = tmp_path / "config.json"
    settings.write_text(json.dumps(config.model_dump()), encoding="utf-8")
    supervisor = tmp_path / "supervisor.py"
    supervisor.write_text(
        "import json, sys, time\nfrom pathlib import Path\nfrom crashlens.manager import Manager\n"
        "root, home, settings = map(Path, sys.argv[1:])\n"
        "manager = Manager(home)\n"
        "job = manager.start(str(root), json.loads(settings.read_text(encoding='utf-8')))\n"
        "(root / 'worker.json').write_text(json.dumps([manager.worker.pid, job['id']]), encoding='utf-8')\n"
        "time.sleep(30)\n", encoding="utf-8")
    process = subprocess.Popen([sys.executable, str(supervisor), str(root), str(home), str(settings)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pids = []
    try:
        deadline = time.monotonic() + 10
        while not (root / "target-pids.json").exists():
            if process.poll() is not None:
                pytest.fail(str(process.communicate()))
            assert time.monotonic() < deadline, "Target failed to start"
            time.sleep(0.02)
        # Atomicity is unnecessary in the target fixture; allow its tiny write to finish.
        target_pids = None
        while target_pids is None:
            try:
                target_pids = json.loads((root / "target-pids.json").read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                assert time.monotonic() < deadline
                time.sleep(0.01)
        worker_pid, job_id = json.loads((root / "worker.json").read_text(encoding="utf-8"))
        pids = [worker_pid, *target_pids]
        assert all(alive(pid) for pid in pids)
        with pytest.raises(SystemExit, match="工作进程"):
            Manager(home)
        process.kill()  # No graceful Manager.close(): simulate server failure.
        process.wait(timeout=5)
        deadline = time.monotonic() + 10
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(alive(pid) for pid in pids), "Orphan process survived server death"
        manager = Manager(home)
        try:
            recovered = manager.store.get(job_id)
            assert recovered["state"] in {"interrupted", "cancelled"}
            assert manager.worker is None
            # The recovered store can accept a fresh task.
            (root / "target.py").write_text("pass\n", encoding="utf-8")
            config.fuzz.max_cases = 1
            fresh = manager.start(str(root), config.model_dump())
            manager.worker.wait(timeout=10)
            manager.refresh()
            assert manager.store.get(fresh["id"])["state"] == "completed"
            assert manager.store.get(job_id)["state"] == recovered["state"]
        finally:
            manager.close()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
        for pid in pids:
            try:
                psutil.Process(pid).kill()
            except psutil.NoSuchProcess:
                pass
