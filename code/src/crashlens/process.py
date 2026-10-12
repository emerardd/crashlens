from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import Config, resolve_command
from .store import write_json


class CaseDirectory(tempfile.TemporaryDirectory):
    def cleanup(self):
        # Windows can signal process termination before all inherited file handles
        # have finished releasing. Retry only sharing/access violations, bounded.
        deadline = time.monotonic() + 2
        while True:
            try:
                return super().cleanup()
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)


class WindowsJob:
    """Kill-on-close job. A blocked launcher closes the child-spawn assignment race."""
    def __init__(self, process):
        from ctypes import wintypes as w
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", w.DWORD), ("minimum", ctypes.c_size_t), ("maximum", ctypes.c_size_t),
                        ("active", w.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [("user", ctypes.c_longlong), ("kernel", ctypes.c_longlong),
                        ("period_user", ctypes.c_longlong), ("period_kernel", ctypes.c_longlong),
                        ("faults", w.DWORD), ("total", w.DWORD), ("active", w.DWORD), ("terminated", w.DWORD)]
        self.Accounting = Accounting
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.api.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def close(self):
        if self.handle:
            # Job termination is asynchronous: wait for all members, not only the gate.
            # Otherwise a target can still hold input/output files during temp cleanup.
            try:
                self.api.TerminateJobObject(self.handle, 1)
                deadline = time.monotonic() + 5
                while True:
                    info = self.Accounting()
                    if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                        raise ctypes.WinError(ctypes.get_last_error())
                    if info.active == 0:
                        break
                    if time.monotonic() > deadline:
                        raise OSError("Windows Job Object 成员未能在 5 秒内退出")
                    time.sleep(0.01)
            finally:
                self.api.CloseHandle(self.handle)
                self.handle = None


def classify(returncode, stderr, reason, config):
    if reason:
        return reason, reason
    # Crash evidence takes precedence over configured ordinary exit codes.
    unsigned = (returncode or 0) & 0xFFFFFFFF
    if (os.name != "nt" and returncode is not None and returncode < 0) or (
        os.name == "nt" and unsigned in {0xC0000005, 0xC000001D, 0xC0000094, 0xC00000FD, 0xC0000409, 0x40000015}
    ):
        return "crash", f"process-status:{returncode}"
    if returncode != 0 and "Traceback (most recent call last):" in stderr:
        tail = stderr.split("Traceback (most recent call last):")[-1]
        exceptions = re.findall(r"^([\w.]+(?:Error|Exception|Interrupt|Exit))(?::|$)", tail, re.M)
        if exceptions:
            frames = re.findall(r'File "([^"]+)", line (\d+), in ([^\n]+)', tail)
            normalized = [(Path(p).name, line, fn.strip()) for p, line, fn in frames[-5:]]
            return "exception", exceptions[-1] + ":" + json.dumps(normalized)
    if returncode in config.target.success_codes:
        return "passed", "passed"
    if returncode in config.target.reject_codes:
        return "rejected", "rejected"
    return "abnormal_exit", f"exit:{returncode}"


def execute(root: Path, config: Config, data: bytes, scratch: Path, cancelled=lambda: False) -> dict:
    scratch.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with CaseDirectory(prefix="case-", dir=scratch) as temp:
        folder = Path(temp)
        input_path = folder / ("input" + config.target.input_suffix)
        input_path.write_bytes(data)
        command = []
        stdout = stderr = ""
        reason = None
        returncode = None
        try:
            command = resolve_command(root, config, input_path)
            write_json(folder / "launch.json", {"command": command, "input": str(input_path),
                                                "cwd": str(root), "mode": config.target.input_mode})
            with (folder / "stdout").open("wb") as out, (folder / "stderr").open("wb") as err:
                flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                process = subprocess.Popen([sys.executable, str(Path(__file__).with_name("_gate.py")),
                                            str(folder / "launch.json"), str(folder / "exit.json")],
                                           stdin=subprocess.PIPE, stdout=out, stderr=err,
                                           creationflags=flags, start_new_session=os.name != "nt")
                job = None
                try:
                    if os.name == "nt":
                        job = WindowsJob(process)
                    process.stdin.write(b"G")
                    process.stdin.close()
                    while process.poll() is None:
                        if cancelled():
                            reason = "cancelled"
                            break
                        if time.monotonic() - started > config.target.timeout_seconds:
                            reason = "timeout"
                            break
                        if sum((folder / name).stat().st_size for name in ("stdout", "stderr")) > config.target.max_output_bytes:
                            reason = "output_limit"
                            break
                        time.sleep(0.01)
                finally:
                    if job:
                        job.close()
                    elif os.name != "nt":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
            result_path = folder / "exit.json"
            if result_path.exists() and not reason:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                returncode = result.get("returncode")
                if result.get("launch_error"):
                    reason = "launch_error"
                    stderr = result["launch_error"]
            elif not reason:
                reason = "runner_error"
                stderr = "执行辅助进程退出但没有产生目标退出记录"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            reason = "launch_error"
            stderr = str(exc)
        limit = config.target.max_output_bytes
        total = sum((folder / name).stat().st_size for name in ("stdout", "stderr") if (folder / name).exists())
        if total > limit and reason is None:
            reason = "output_limit"
        if (folder / "stdout").exists():
            with (folder / "stdout").open("rb") as stream:
                stdout = stream.read(limit).decode("utf-8", errors="replace")
        if (folder / "stderr").exists():
            with (folder / "stderr").open("rb") as stream:
                stderr += stream.read(limit).decode("utf-8", errors="replace")
        category, identity = classify(returncode, stderr, reason, config)
        return {"category": category, "signature": hashlib.sha256(identity.encode()).hexdigest()[:16],
                "identity": identity, "returncode": returncode, "stdout": stdout, "stderr": stderr,
                "duration_seconds": round(time.monotonic() - started, 4), "command": command,
                "output_truncated": total > limit, "input_sha256": hashlib.sha256(data).hexdigest(),
                "input_bytes": len(data)}
