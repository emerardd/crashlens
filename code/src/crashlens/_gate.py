"""Internal launcher: do not spawn target until the parent contains this process."""
import json
import os
import subprocess
import sys


def main():
    metadata, result_path = sys.argv[1:]
    with open(metadata, encoding="utf-8") as stream:
        spec = json.load(stream)
    if os.read(sys.stdin.fileno(), 1) != b"G":
        return
    try:
        with open(spec["input"], "rb") as stream:
            child = subprocess.Popen(spec["command"], cwd=spec["cwd"],
                                     stdin=stream if spec["mode"] == "stdin" else subprocess.DEVNULL,
                                     shell=False)
            result = {"returncode": child.wait()}
    except OSError as exc:
        result = {"launch_error": str(exc)}
    with open(result_path, "w", encoding="utf-8") as stream:
        json.dump(result, stream)


if __name__ == "__main__":
    main()

