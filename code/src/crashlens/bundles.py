"""Portable evidence archives, built only from a finished task's saved artifacts."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

MAX_BYTES = 256 * 1024 * 1024
MAX_FILES = 20000


def build_bundle(folder: Path, report: dict, html: str):
    root = folder.resolve()
    paths = [root / name for name in (
        "manifest.json", "summary.json", "cases.jsonl", "baseline-error.json", "baseline-results.json", "replay.bin")]
    paths += list((root / "seeds").glob("*.bin"))
    paths += list((root / "findings").rglob("*.bin"))
    paths += list((root / "findings").rglob("*.json"))
    paths = sorted(path for path in paths if path.is_file())
    if len(paths) > MAX_FILES or sum(path.stat().st_size for path in paths) > MAX_BYTES:
        raise ValueError("证据超过打包上限（256 MiB / 20000 文件），请直接复制本地任务目录")
    for path in paths:
        if not path.resolve().is_relative_to(root):
            raise ValueError("证据路径指向任务目录以外，拒绝打包")
    output = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    checksums = {}
    try:
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            def add(name, data):
                archive.writestr(name, data)
                checksums[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

            add("report.json", json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
            add("report.html", html.encode("utf-8"))
            add("README.txt", (
                "CrashLens evidence bundle\n\n"
                "Open report.html offline. report.json contains the task configuration and environment.\n"
                "evidence/findings/<signature>/input.bin contains the original failure bytes.\n"
                "minimized.bin is included only when saved after successful verification.\n"
                "manifest-sha256.json covers every other file in this archive.\n"
                "The target program and its dependencies are NOT bundled. Keep their original versions.\n"
                "To replay: crashlens replay <target-directory> <extracted-input.bin> --data-dir .crashlens-replay\n"
                "The CLI uses the target directory's current crashlens.toml; compare it with report.json.\n"
                "Use Python hashlib.sha256(file_bytes).hexdigest() to check a saved file.\n"
            ).encode("utf-8"))
            total = 0
            for path in paths:
                name = "evidence/" + path.relative_to(root).as_posix()
                digest, size = hashlib.sha256(), 0
                with path.open("rb") as source, archive.open(name, "w") as target:
                    while chunk := source.read(1024 * 1024):
                        size += len(chunk)
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise ValueError("证据在打包期间超过大小上限")
                        digest.update(chunk)
                        target.write(chunk)
                checksums[name] = {"bytes": size, "sha256": digest.hexdigest()}
            archive.writestr("manifest-sha256.json", json.dumps(checksums, ensure_ascii=False, indent=2).encode("utf-8"))
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


def stream_bundle(stream):
    try:
        while chunk := stream.read(1024 * 1024):
            yield chunk
    finally:
        stream.close()
