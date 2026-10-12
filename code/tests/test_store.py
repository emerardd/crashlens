import json
import threading
import time
from pathlib import Path

import pytest

from crashlens.store import read_json, write_json


def test_atomic_evidence_write_tolerates_short_lived_reader(tmp_path):
    path = tmp_path / "finding.json"
    write_json(path, {"version": 1})
    errors = []
    def writer():
        try:
            write_json(path, {"version": 2})
        except Exception as exc:
            errors.append(exc)
    with path.open("rb") as reader:
        thread = threading.Thread(target=writer)
        thread.start()
        time.sleep(0.08)
        assert json.load(reader)["version"] in {1, 2}
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 2}


def test_evidence_read_retries_transient_sharing_error(tmp_path, monkeypatch):
    path = tmp_path / "finding.json"
    path.write_text('{"identity":"confirmed"}', encoding="utf-8")
    original = Path.read_text
    calls = []
    def read(self, *args, **kwargs):
        calls.append(self)
        if len(calls) == 1:
            raise PermissionError("simulated sharing violation")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    assert read_json(path) == {"identity": "confirmed"}
    assert len(calls) == 2


def test_evidence_read_does_not_hide_permanent_denial(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("permanent")
    ticks = iter([0, 3])
    monkeypatch.setattr(Path, "read_text", denied)
    monkeypatch.setattr("crashlens.store.time.monotonic", lambda: next(ticks))
    with pytest.raises(PermissionError, match="permanent"):
        read_json(tmp_path / "finding.json")

