from crashlens.config import Config, Fuzz, Target
from crashlens.engine import create_job, run_job
from crashlens.store import Store
import pytest


def test_bad_normal_seed_is_not_a_discovered_bug(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    (root / "seeds").mkdir()
    (root / "seeds" / "normal.txt").write_text("hello", encoding="utf-8")
    (root / "app.py").write_text("import crashlens_nonexistent_dependency\n", encoding="utf-8")
    config = Config(target=Target(command=["{python}", "app.py"]), fuzz=Fuzz(max_cases=10))
    store = Store(tmp_path / "data")
    job = create_job(store, str(root), config.model_dump())
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == "failed"
    assert result["finding_count"] == 0
    assert "正常种子" in result["error"]
    assert (store.folder(job["id"]) / "baseline-error.json").exists()


@pytest.mark.parametrize("reason", ["user_stop", "time_budget"])
def test_cancelled_seed_is_not_baseline_failure(tmp_path, examples, monkeypatch, reason):
    store = Store(tmp_path / "data")
    job = create_job(store, str(examples / "datacraft-buggy"))
    folder = store.folder(job["id"])
    clock = [0.0]
    monkeypatch.setattr("crashlens.engine.time.monotonic", lambda: clock[0])

    def cancel(*args):
        if reason == "user_stop":
            (folder / "STOP").touch()
        else:
            clock[0] = 121.0
        return {"category": "cancelled", "signature": "cancelled", "stderr": "", "stdout": ""}

    monkeypatch.setattr("crashlens.engine.execute", cancel)
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == ("cancelled" if reason == "user_stop" else "completed")
    assert result["completion_reason"] == reason
    assert result["error"] is None
    assert result["finding_count"] == 0
    assert not (folder / "baseline-error.json").exists()
