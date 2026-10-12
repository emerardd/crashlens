import json

from crashlens.config import Config, Fuzz, Target, load_config
from crashlens.engine import create_job, minimize, run_job
from crashlens.generators import generate
from crashlens.store import Store


def test_mutations_are_deterministic_and_generic():
    seeds = [b'{"unrelated_name":7,"some_text":"ok"}']
    a = list(generate(seeds, 60, 12, 512))
    b = list(generate(seeds, 60, 12, 512))
    assert a == b
    assert len(a) == 60
    assert len({data for _, data in a}) == 60
    assert max(len(data) for _, data in a) <= 512
    assert any(data == b'{"unrelated_name":0,"some_text":"ok"}' for _, data in a)


def test_minimizer_reduces_without_losing_failure():
    output, attempts = minimize(b"aaaaFAILzzzz", lambda data: b"FAIL" in data, 50)
    assert output == b"FAIL"
    assert 0 < attempts <= 50


def test_minimizer_respects_budget():
    calls = []
    output, attempts = minimize(b"unchanged", lambda data: calls.append(data) or False, 3)
    assert output == b"unchanged"
    assert attempts == len(calls) == 3


def test_small_budget_does_not_construct_structured_mutations(monkeypatch):
    def should_not_run(data):
        raise AssertionError("Structured mutation was requested after exhausting the case budget")
    monkeypatch.setattr("crashlens.generators.structured", should_not_run)
    assert list(generate([b'{"valid":true}'], 1, 42, 1024)) == [("seed", b'{"valid":true}')]


def test_engine_end_to_end(examples, tmp_path):
    store = Store(tmp_path / "data")
    root, config = load_config(str(examples / "datacraft-buggy"))
    config.fuzz.max_cases = 65
    config.fuzz.minimize_attempts = 5
    job = create_job(store, str(root), config.model_dump())
    run_job(store.home, job["id"])
    finished = store.get(job["id"])
    assert finished["state"] == "completed", finished["error"]
    assert finished["executed"] == 65
    assert finished["counts"]["passed"] >= 2
    assert finished["counts"]["rejected"] >= 2
    findings = store.findings(job["id"])
    assert any(f["identity"].startswith("ZeroDivisionError:") for f in findings)
    assert any(f["category"] == "timeout" for f in findings)
    assert any(f["occurrences"] > 1 for f in findings)
    for finding in findings:
        assert finding["stable"]
        folder = store.folder(job["id"]) / "findings" / finding["id"]
        assert (folder / "input.bin").is_file()
    minimized = [f for f in findings if f["minimization"] and f["minimization"]["verified"]]
    assert minimized


def test_fixed_example_no_findings(examples, tmp_path):
    store = Store(tmp_path / "data")
    root, config = load_config(str(examples / "datacraft-fixed"))
    job = create_job(store, str(root), config.model_dump())
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == "completed"
    assert result["executed"] == 80
    assert result["finding_count"] == 0


def test_stop_before_execution(examples, tmp_path):
    store = Store(tmp_path / "data")
    job = create_job(store, str(examples / "datacraft-buggy"))
    (store.folder(job["id"]) / "STOP").touch()
    run_job(store.home, job["id"])
    result = store.get(job["id"])
    assert result["state"] == "cancelled"
    assert result["executed"] == 0
