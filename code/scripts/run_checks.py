"""Run delivery checks and retain their real output, with local paths redacted."""
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONUTF8="1")
    (project / ".crashlens").mkdir(exist_ok=True)
    commands = [
        [sys.executable, "-m", "pytest", "code/tests", "-q", "-p", "no:cacheprovider",
         f"--basetemp=.crashlens/pytest-delivery-{uuid.uuid4().hex[:10]}"],
        [sys.executable, "-m", "pip", "check"],
    ]
    logs = [f"Verified at {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"]
    failed = False
    for command in commands:
        result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = (result.stdout + result.stderr).replace(str(project), "<PROJECT_ROOT>")
        logs.append(f"Command: python {' '.join(command[1:])}\nExit code: {result.returncode}\n{output}\n")
        print(output, flush=True)
        failed |= result.returncode != 0
    destination = project / "code" / "examples" / "acceptance" / "test-output.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(logs), encoding="utf-8")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
