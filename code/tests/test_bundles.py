import json
from zipfile import ZipFile

import pytest

from crashlens.bundles import build_bundle, stream_bundle


def test_bundle_captures_baseline_error_and_closes_stream(tmp_path):
    (tmp_path / "baseline-error.json").write_text('{"category":"launch_error"}', encoding="utf-8")
    stream = build_bundle(tmp_path, {"state": "failed"}, "<html>failed</html>")
    with ZipFile(stream) as archive:
        assert json.loads(archive.read("evidence/baseline-error.json"))["category"] == "launch_error"
    stream.seek(0)
    chunks = stream_bundle(stream)
    assert next(chunks).startswith(b"PK")
    chunks.close()
    assert stream.closed


def test_bundle_enforces_size_limit_before_reading(tmp_path, monkeypatch):
    (tmp_path / "replay.bin").write_bytes(b"1234")
    monkeypatch.setattr("crashlens.bundles.MAX_BYTES", 3)
    with pytest.raises(ValueError, match="打包上限"):
        build_bundle(tmp_path, {}, "")
