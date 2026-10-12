import time
import hashlib
import io
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from crashlens.config import Target, load_config, seed_files
from crashlens.web import create_app


def test_web_rejects_cross_site_requests_and_unknown_hosts(tmp_path, examples):
    app = create_app(tmp_path / "data")
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/", headers={"Host": "evil.invalid"}).status_code == 400
        body = {"directory": str(examples / "datacraft-buggy")}
        assert client.post("/api/inspect", json=body).status_code == 403
        headers = {"X-CrashLens-Token": app.state.token}
        assert client.post("/api/inspect", json=body, headers=headers).status_code == 200
        headers["Origin"] = "https://evil.invalid"
        assert client.post("/api/inspect", json=body, headers=headers).status_code == 403


def test_web_worker_and_report(tmp_path, examples):
    app = create_app(tmp_path / "data")
    root, config = load_config(str(examples / "datacraft-buggy"))
    config.fuzz.max_cases = 5
    config.fuzz.minimize = False
    with TestClient(app) as client:
        client.headers["X-CrashLens-Token"] = app.state.token
        response = client.post("/api/jobs", json={"directory": str(root), "config": config.model_dump()})
        assert response.status_code == 201, response.text
        job_id = response.json()["id"]
        assert client.get(f"/api/jobs/{job_id}/evidence.zip").status_code == 409
        other = client.post("/api/jobs", json={"directory": str(root), "config": config.model_dump()})
        assert other.status_code == 400
        for _ in range(150):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] not in {"queued", "running"}:
                break
            time.sleep(0.1)
        assert job["state"] == "completed", job
        assert client.get(f"/api/jobs/{job_id}/report.json").status_code == 200
        report = client.get(f"/api/jobs/{job_id}/report.html")
        assert report.status_code == 200
        assert "CrashLens" in report.text
        assert client.get("/api/jobs/not-a-job").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/findings/missing/input").status_code == 404
        assert len(job["findings"]) == 1
        finding_id = job["findings"][0]["id"]
        bundle = client.get(f"/api/jobs/{job_id}/evidence.zip")
        assert bundle.status_code == 200
        assert bundle.headers["content-type"] == "application/zip"
        with ZipFile(io.BytesIO(bundle.content)) as archive:
            names = set(archive.namelist())
            checksums = json.loads(archive.read("manifest-sha256.json"))
            assert names == set(checksums) | {"manifest-sha256.json"}
            for name, entry in checksums.items():
                data = archive.read(name)
                assert len(data) == entry["bytes"]
                assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert archive.read(f"evidence/findings/{finding_id}/input.bin") == b"{}"
            assert "evidence/seeds/000.bin" in names
            assert "evidence/cases.jsonl" in names
            assert all("scratch" not in name for name in names)
            assert json.loads(archive.read("report.json"))["id"] == job_id
        response = client.post(f"/api/jobs/{job_id}/findings/{finding_id}/replay", json={})
        assert response.status_code == 201, response.text
        replay_id = response.json()["id"]
        for _ in range(150):
            replay = client.get(f"/api/jobs/{replay_id}").json()
            if replay["state"] not in {"queued", "running"}:
                break
            time.sleep(0.1)
        assert replay["state"] == "completed"
        assert replay["comparison"]["same_failure"]
        assert replay["comparison"]["verdict"] == "reproduced"
        replay_bundle = client.get(f"/api/jobs/{replay_id}/evidence.zip")
        assert replay_bundle.status_code == 200
        with ZipFile(io.BytesIO(replay_bundle.content)) as archive:
            baseline = json.loads(archive.read("evidence/baseline-results.json"))
            assert baseline and all(entry["result"]["category"] == "passed" for entry in baseline)
        response = client.post(f"/api/jobs/{job_id}/findings/{finding_id}/replay",
                               json={"directory": str(examples / "datacraft-fixed")})
        assert response.status_code == 201, response.text
        regression_id = response.json()["id"]
        for _ in range(150):
            regression = client.get(f"/api/jobs/{regression_id}").json()
            if regression["state"] not in {"queued", "running"}:
                break
            time.sleep(0.1)
        assert regression["state"] == "completed"
        assert not regression["comparison"]["same_failure"]
        assert regression["comparison"]["category"] == "rejected"
        assert regression["comparison"]["verdict"] == "handled"


def test_invalid_config_and_seed_escape(examples):
    with pytest.raises(ValueError):
        Target(command=["python"], input_mode="file")
    with pytest.raises(ValueError):
        Target(command=["python"], success_codes=[0, 2], reject_codes=[2])
    root, config = load_config(str(examples / "datacraft-buggy"))
    config.fuzz.seed_directory = "../datacraft-fixed/seeds"
    with pytest.raises(ValueError):
        seed_files(root, config)
