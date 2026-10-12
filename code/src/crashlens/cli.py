from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from .config import load_config
from .engine import create_job, run_job
from .process import execute
from .store import Store


class DataLock:
    def __init__(self, home, name="server.lock"):
        home.mkdir(parents=True, exist_ok=True)
        self.stream = (home / name).open("a+b")
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)

    def __enter__(self):
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            message = ("上次工作进程尚未退出，请稍后重新启动服务" if self.stream.name.endswith("worker.lock")
                       else "该数据目录已有 CrashLens 实例，请关闭它或使用其他 --data-dir")
            raise SystemExit(message)
        return self

    def __exit__(self, *args):
        self.stream.close()


def main():
    parser = argparse.ArgumentParser(description="CrashLens · 本地命令行动态测试平台")
    sub = parser.add_subparsers(dest="action", required=True)
    serve = sub.add_parser("serve", help="启动本地网页")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data-dir", type=Path, default=Path(".crashlens"))
    run = sub.add_parser("run", help="从项目配置运行测试")
    run.add_argument("directory")
    run.add_argument("--data-dir", type=Path, default=Path(".crashlens"))
    replay = sub.add_parser("replay", help="用保存的输入独立执行目标")
    replay.add_argument("directory")
    replay.add_argument("input", type=Path)
    replay.add_argument("--data-dir", type=Path, default=Path(".crashlens"))
    worker = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker.add_argument("home", type=Path)
    worker.add_argument("job_id")
    worker.add_argument("--supervised", action="store_true")
    args = parser.parse_args()
    if args.action == "_worker":
        if args.supervised:
            # Block until the server has installed process-tree protection.
            # EOF before GO means the server died during startup.
            if os.read(sys.stdin.fileno(), 1) != b"G":
                return
            with DataLock(args.home, "worker.lock"):
                if Store(args.home).get(args.job_id)["state"] != "queued":
                    return
                def watch_owner():
                    # Raw descriptor reads avoid holding a buffered-IO lock
                    # during interpreter shutdown of this daemon thread.
                    while os.read(sys.stdin.fileno(), 4096):
                        pass
                    (args.home / "jobs" / args.job_id / "STOP").touch()
                threading.Thread(target=watch_owner, daemon=True).start()
                run_job(args.home, args.job_id)
        else:
            run_job(args.home, args.job_id)
        return
    home = args.data_dir.resolve()
    with DataLock(home):
        if args.action == "serve":
            import uvicorn
            from .web import create_app
            uvicorn.run(create_app(home), host="127.0.0.1", port=args.port, log_level="info")
        elif args.action == "run":
            store = Store(home)
            job = create_job(store, args.directory)
            print(f"Job: {job['id']}", flush=True)
            run_job(home, job["id"])
            result = store.get(job["id"])
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["state"] != "completed":
                raise SystemExit(1)
        else:
            root, config = load_config(args.directory)
            result = execute(root, config, args.input.read_bytes(), home / "scratch")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if result["category"] not in {"passed", "rejected"}:
                raise SystemExit(1)
