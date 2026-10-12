import json

import pytest

from crashlens.generators import generate, structured
from crashlens.minimizer import minimize
from crashlens.engine import create_job, run_job
from crashlens.store import Store


def test_nested_object_and_array_elements_are_mutated():
    data = b'{"request":{"items":[{"count":5,"enabled":true}]},"keep":"unchanged"}'
    mutations = [json.loads(value) for value in structured(data)]
    assert any(value.get("request") == {"items": [{"count": 0, "enabled": True}]}
               and value.get("keep") == "unchanged" for value in mutations)
    assert any(value.get("request") == {"items": [{"count": 5, "enabled": False}]}
               for value in mutations)
    assert any(value.get("request") == {"items": []} for value in mutations)


def test_wide_seed_does_not_starve_other_seed_or_byte_strategy():
    wide = json.dumps({f"field{i}": i for i in range(64)}).encode()
    small = b'{"nested":{"denominator":8}}'
    cases = list(generate([wide, small], 30, 42, 8192))
    assert any(strategy == "byte-mutation" for strategy, _ in cases)
    assert any(strategy == "json-structure" and json.loads(data) == {"nested": {"denominator": 0}}
               for strategy, data in cases)
    assert cases == list(generate([wide, small], 30, 42, 8192))


def test_json_minimizer_removes_noise_but_preserves_nested_failure():
    data = json.dumps({"noise": "x" * 100, "request": {"items": [
        {"denominator": 9, "noise": "a" * 80}, {"denominator": 0, "noise": "b" * 80}]}}).encode()
    calls = []
    def predicate(candidate):
        obj = json.loads(candidate)  # Every trial must remain valid JSON.
        calls.append(candidate)
        request = obj.get("request", {})
        return isinstance(request, dict) and any(
            isinstance(item, dict) and item.get("denominator") == 0
            for item in request.get("items", []))
    reduced, attempts = minimize(data, predicate, 100)
    assert predicate(reduced)
    assert json.loads(reduced) == {"request": {"items": [{"denominator": 0}]}}
    assert attempts == len(calls) - 1
    assert len(reduced) < len(data) // 2


@pytest.mark.parametrize("data", [b'{"a":"\\ud800","n":5}', b'"long string"', b'1234567', b'[1,2,3]'])
def test_json_reduction_budget_and_syntax(data):
    calls = []
    def reject(candidate):
        json.loads(candidate)
        calls.append(candidate)
        return False
    reduced, attempts = minimize(data, reject, 3)
    assert reduced == data
    assert attempts == len(calls) <= 3
    assert minimize(data, reject, 0) == (data, 0)


def test_binary_reduction_keeps_original_behavior():
    reduced, attempts = minimize(b'\xff\x00prefixFAILsuffix', lambda data: b'FAIL' in data, 50)
    assert reduced == b'FAIL'
    assert 0 < attempts <= 50


def test_wide_json_reduction_respects_member_exploration_limit():
    obj = {f"field{i}": i for i in range(80)}
    calls = []
    def reject(candidate):
        value = json.loads(candidate)
        assert all(value[f"field{i}"] == i for i in range(64, 80))
        calls.append(candidate)
        return False
    data = json.dumps(obj).encode()
    reduced, attempts = minimize(data, reject, 10)
    assert reduced == data
    assert attempts == len(calls) == 10


def test_nested_failure_is_discovered_and_minimized_in_real_process(make_target, tmp_path):
    root, config = make_target(
        "import json, sys\n"
        "try:\n"
        "    obj = json.loads(sys.stdin.buffer.read())\n"
        "    denominator = obj['request']['denominator']\n"
        "    if type(denominator) is not int: raise ValueError('type')\n"
        "except (ValueError, UnicodeError, TypeError, KeyError):\n"
        "    raise SystemExit(2)\n"
        "print(12 / denominator)\n")
    (root / "seeds").mkdir()
    (root / "seeds" / "normal.json").write_text(
        json.dumps({"request": {"denominator": 3}, "noise": "x" * 120}), encoding="utf-8")
    config.fuzz.max_cases = 35
    config.fuzz.minimize = True
    config.fuzz.minimize_attempts = 30
    store = Store(tmp_path / "data")
    job = create_job(store, str(root), config.model_dump())
    run_job(store.home, job["id"])
    finished = store.get(job["id"])
    assert finished["state"] == "completed", finished["error"]
    finding = next(f for f in store.findings(job["id"]) if f["identity"].startswith("ZeroDivisionError:"))
    assert finding["strategy"] == "json-structure"
    assert finding["minimization"]["verified"]
    assert finding["minimization"]["method"] == "json-structure"
    reduced = store.folder(job["id"]) / "findings" / finding["id"] / "minimized.bin"
    assert json.loads(reduced.read_bytes()) == {"request": {"denominator": 0}}
