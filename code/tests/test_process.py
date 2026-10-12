import json
import os
import time
from pathlib import Path

import psutil
import pytest

from crashlens.config import load_config
from crashlens.process import execute


def test_stdin_preserves_binary_bytes(make_target, tmp_path):
    root, config = make_target("import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n")
    result = execute(root, config, b"A\x00Z\n", tmp_path / "scratch")
    assert result["category"] == "passed"
    assert result["stdout"] == "A\x00Z\n"


def test_file_mode_handles_spaces(make_target, tmp_path):
    root, config = make_target("import sys\nfrom pathlib import Path\nsys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())\n")
    config.target.input_mode = "file"
    config.target.command.append("{input_file}")
    result = execute(root, config, b"test file input", tmp_path / "scratch with spaces")
    assert result["category"] == "passed"
    assert result["stdout"] == "test file input"


@pytest.mark.parametrize("code,category", [(0, "passed"), (2, "rejected"), (7, "abnormal_exit")])
def test_exit_contract(make_target, tmp_path, code, category):
    root, config = make_target(f"raise SystemExit({code})\n")
    assert execute(root, config, b"", tmp_path / "scratch")["category"] == category


def test_exception_grouping_ignores_message(make_target, tmp_path):
    root, config = make_target("import sys\nraise ValueError(sys.stdin.read())\n")
    a = execute(root, config, b"alpha", tmp_path / "scratch")
    b = execute(root, config, b"beta", tmp_path / "scratch")
    assert a["category"] == "exception"
    assert a["signature"] == b["signature"]
    assert a["stderr"] != b["stderr"]


def test_traceback_text_on_success_is_not_exception(make_target, tmp_path):
    root, config = make_target('import sys\nprint("Traceback (most recent call last):\\nValueError: example", file=sys.stderr)\n')
    assert execute(root, config, b"", tmp_path / "scratch")["category"] == "passed"


def test_missing_executable_is_environment_error(make_target, tmp_path):
    root, config = make_target("pass\n")
    config.target.command = ["crashlens-missing-program-98123"]
    assert execute(root, config, b"", tmp_path / "scratch")["category"] == "launch_error"


@pytest.mark.parametrize("parent_waits", [True, False])
def test_process_tree_cleanup(make_target, tmp_path, parent_waits):
    root, config = make_target(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "Path('child.pid').write_text(str(p.pid), encoding='utf-8')\n" +
        ("time.sleep(60)\n" if parent_waits else ""), timeout_seconds=0.8)
    result = execute(root, config, b"", tmp_path / "scratch")
    assert result["category"] == ("timeout" if parent_waits else "passed")
    pid = int((root / "child.pid").read_text(encoding="utf-8"))
    for _ in range(50):
        if not psutil.pid_exists(pid):
            break
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(0.02)
    else:
        pytest.fail("Descendant survived target completion/timeout")


def test_cancellation(make_target, tmp_path):
    root, config = make_target("import time\ntime.sleep(60)\n")
    result = execute(root, config, b"", tmp_path / "scratch", lambda: True)
    assert result["category"] == "cancelled"
    assert result["duration_seconds"] < 2


def test_repeated_timeouts_release_input_handles(make_target, tmp_path):
    root, config = make_target("import sys, time\nsys.stdin.buffer.read(1)\ntime.sleep(60)\n",
                               timeout_seconds=0.2)
    scratch = tmp_path / "scratch"
    for _ in range(8):
        assert execute(root, config, b"hold input", scratch)["category"] == "timeout"
        assert list(scratch.iterdir()) == []


def test_output_limit(make_target, tmp_path):
    root, config = make_target("import sys\nsys.stdout.write('x' * 100000)\n", max_output_bytes=1024)
    result = execute(root, config, b"", tmp_path / "scratch")
    assert result["category"] == "output_limit"
    assert result["output_truncated"]
    assert len(result["stdout"]) <= 1024


def test_buggy_and_fixed_examples(examples, tmp_path):
    data = b'{"operation":"ratio","numerator":12,"denominator":0}'
    root, config = load_config(str(examples / "datacraft-buggy"))
    bad = execute(root, config, data, tmp_path / "scratch")
    assert bad["category"] == "exception"
    assert "ZeroDivisionError" in bad["identity"]
    root, config = load_config(str(examples / "datacraft-fixed"))
    fixed = execute(root, config, data, tmp_path / "scratch")
    assert fixed["category"] == "rejected"


@pytest.mark.parametrize("version", ["datacraft-buggy", "datacraft-fixed"])
def test_demo_unicode_output_independent_of_windows_console_encoding(examples, tmp_path, monkeypatch, version):
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "gbk")
    root, config = load_config(str(examples / version))
    data = json.dumps({"operation": "repeat", "count": 2, "text": "中文🙂"}).encode("utf-8")
    result = execute(root, config, data, tmp_path / "scratch")
    assert result["category"] == "passed", result["stderr"]
    assert json.loads(result["stdout"]) == {"value": "中文🙂中文🙂"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal status is platform-specific")
def test_posix_signal_crash(make_target, tmp_path):
    root, config = make_target("import os, signal\nos.kill(os.getpid(), signal.SIGTERM)\n")
    assert execute(root, config, b"", tmp_path / "scratch")["category"] == "crash"


@pytest.mark.skipif(os.name != "nt", reason="Windows native status is platform-specific")
def test_windows_native_exit(make_target, tmp_path):
    root, config = make_target("import ctypes\nctypes.windll.kernel32.ExitProcess(0xC0000005)\n")
    assert execute(root, config, b"", tmp_path / "scratch")["category"] == "crash"
