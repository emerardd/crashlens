from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from .engine import TERMINAL, create_job
from .store import Store, now
from .process import WindowsJob
from .cli import DataLock


class Manager:
    def __init__(self, home: Path):
        self.store = Store(home)
        self.lock = threading.Lock()
        self.active = None
        self.worker = None
        self.worker_log = None
        self.worker_job = None
        # A surviving POSIX worker observes pipe EOF and cancels its target.
        # Do not recover state or accept new work before it releases ownership.
        with DataLock(home, "worker.lock"):
            # Hold recovery ownership until all stale records are finalized.
            for job in self.store.list(limit=None):
                if job["state"] not in TERMINAL:
                    job.update(state="interrupted", current="上次运行中断，证据已保留", updated_at=now())
                    self.store.put(job)

    def refresh(self):
        if self.worker and self.worker.poll() is not None:
            self.worker.stdin.close()
            if self.worker_job:
                self.worker_job.close()
                self.worker_job = None
            job = self.store.get(self.active)
            if job["state"] not in TERMINAL:
                job.update(state="failed", error=f"工作进程意外退出：{self.worker.returncode}", updated_at=now())
                self.store.put(job)
            self.worker_log.close()
            self.worker = self.active = self.worker_log = None

    def start(self, directory, config=None, source=None):
        with self.lock:
            self.refresh()
            if self.worker and self.store.get(self.active)["state"] in TERMINAL:
                # The final evidence is saved just before the worker exits. Allow
                # that short exit tail rather than rejecting a user's next task.
                try:
                    self.worker.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                self.refresh()
            if self.worker:
                raise ValueError("已有任务正在运行，请等待完成或先停止任务")
            job = create_job(self.store, directory, config, source)
            folder = self.store.folder(job["id"])
            log = (folder / "worker.log").open("wb")
            worker = None
            guard = None
            try:
                worker = subprocess.Popen([sys.executable, "-m", "crashlens", "_worker",
                                           str(self.store.home), job["id"], "--supervised"],
                                          stdin=subprocess.PIPE, stdout=log, stderr=log,
                                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                if sys.platform == "win32":
                    guard = WindowsJob(worker)
                worker.stdin.write(b"G")
                worker.stdin.flush()
            except OSError as exc:
                if guard:
                    guard.close()
                if worker:
                    worker.stdin.close()
                    worker.kill()
                    worker.wait(timeout=5)
                log.close()
                job.update(state="failed", error=str(exc))
                self.store.put(job)
                raise
            self.active, self.worker, self.worker_log = job["id"], worker, log
            self.worker_job = guard
            return job

    def stop(self, job_id):
        job = self.store.get(job_id)
        if job["state"] not in TERMINAL:
            (self.store.folder(job_id) / "STOP").touch()
        return job

    def close(self):
        with self.lock:
            self.refresh()
            if self.worker:
                self.stop(self.active)
                try:
                    self.worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.worker.kill()
                    self.worker.wait(timeout=5)
                self.refresh()
