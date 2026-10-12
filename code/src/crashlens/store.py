from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    # Windows readers may briefly deny replace while reading an evidence file.
    # Preserve atomic publication, but allow the reader to release its handle.
    deadline = time.monotonic() + 2
    while True:
        try:
            temporary.replace(path)
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def read_json(path: Path):
    # Windows replacement can briefly deny a concurrent reader an open handle.
    # Retry only access/sharing errors; corrupt JSON and missing files surface.
    deadline = time.monotonic() + 2
    while True:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


class Store:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = self.home / "index.sqlite3"
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=20)
        try:
            with con:
                yield con
        finally:
            con.close()

    def put(self, job):
        with self.connect() as con:
            con.execute("INSERT INTO jobs VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                        (job["id"], json.dumps(job, ensure_ascii=False)))

    def get(self, job_id):
        with self.connect() as con:
            row = con.execute("SELECT payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return json.loads(row[0])

    def list(self, limit=200):
        with self.connect() as con:
            rows = con.execute("SELECT payload FROM jobs ORDER BY rowid DESC LIMIT ?",
                               (-1 if limit is None else limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def folder(self, job_id):
        self.get(job_id)
        return self.home / "jobs" / job_id

    def findings(self, job_id):
        folder = self.folder(job_id) / "findings"
        return [read_json(p) for p in sorted(folder.glob("*/finding.json"))]
