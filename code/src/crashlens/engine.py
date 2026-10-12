from __future__ import annotations

import json
import platform
import sys
import time
import traceback
import uuid
from pathlib import Path

from .config import Config, load_config, resolve_command, seed_files, source_hashes
from .generators import generate
from .minimizer import method as minimization_method, minimize
from .process import execute
from .store import Store, now, write_json

FINDING_CATEGORIES = {"exception", "crash", "timeout", "abnormal_exit", "output_limit"}
TERMINAL = {"completed", "cancelled", "failed", "interrupted"}


def create_job(store: Store, directory: str, override=None, source=None):
    root, config = load_config(directory, override)
    resolve_command(root, config, root / "example-input.bin")
    seeds = seed_files(root, config)
    job_id = uuid.uuid4().hex[:16]
    folder = store.home / "jobs" / job_id
    folder.mkdir(parents=True)
    seed_manifest = []
    for index, path in enumerate(seeds):
        saved = folder / "seeds" / f"{index:03d}.bin"
        saved.parent.mkdir(exist_ok=True)
        saved.write_bytes(path.read_bytes())
        seed_manifest.append({"name": path.name, "file": saved.name})
    if source is not None:
        source = dict(source)
        (folder / "replay.bin").write_bytes(source.pop("data"))
    job = {"id": job_id, "directory": str(root), "config": config.model_dump(),
           "created_at": now(), "updated_at": now(), "state": "queued", "executed": 0,
           "auxiliary_executions": 0, "counts": {}, "finding_count": 0, "current": "等待执行",
           "source": source, "seeds": seed_manifest, "source_hashes": source_hashes(root, config),
           "environment": {"platform": platform.platform(), "python": sys.version,
                           "executable": sys.executable}, "error": None}
    if source is not None:
        job["comparison"] = {"expected_signature": source["signature"],
                             "actual_signature": None, "category": None,
                             "same_failure": None, "verdict": "inconclusive", "result": None}
    write_json(folder / "manifest.json", job)
    store.put(job)
    return job


def run_job(home: Path, job_id: str):
    store = Store(home)
    job = store.get(job_id)
    folder = store.folder(job_id)
    root = Path(job["directory"])
    config = Config.model_validate(job["config"])
    began = time.monotonic()
    deadline = began + config.fuzz.max_seconds
    groups = {}

    def stopping():
        return (folder / "STOP").exists() or time.monotonic() >= deadline

    def update():
        job["updated_at"] = now()
        job["elapsed_seconds"] = round(time.monotonic() - began, 3)
        store.put(job)

    def trial(data, auxiliary=False):
        result = execute(root, config, data, folder / "scratch", stopping)
        if auxiliary:
            job["auxiliary_executions"] += 1
        return result

    try:
        job["state"] = "running"
        update()
        if job["source"]:
            # A rejected replay is meaningful only after the target accepts a
            # known-good input. Interpreter/setup failures can also exit with 2.
            if not job["seeds"]:
                raise RuntimeError("回归或重放缺少正常样例，无法判断目标是否能正常启动")
            baseline_results = []
            for seed in job["seeds"]:
                if stopping():
                    break
                baseline = trial((folder / "seeds" / seed["file"]).read_bytes(), True)
                baseline_results.append({"seed": seed["name"], "result": baseline})
                write_json(folder / "baseline-results.json", baseline_results)
                if baseline["category"] == "cancelled":
                    break
                if baseline["category"] != "passed":
                    write_json(folder / "baseline-error.json", baseline)
                    raise RuntimeError(f"回归或重放正常样例未通过（{baseline['category']}），无法得出结论；请检查入口、依赖和种子")
            cases = iter([("replay", (folder / "replay.bin").read_bytes())])
        else:
            seeds = [(folder / "seeds" / seed["file"]).read_bytes() for seed in job["seeds"]]
            cases = generate(seeds, config.fuzz.max_cases, config.fuzz.random_seed, config.fuzz.max_input_bytes)
        with (folder / "cases.jsonl").open("w", encoding="utf-8") as log:
            for strategy, data in cases:
                if stopping():
                    break
                job["current"] = f"执行用例 {job['executed'] + 1} · {strategy}"
                update()
                result = trial(data)
                case_no = job["executed"] + 1
                record = {"case": case_no, "strategy": strategy, **result}
                # Full output is retained only for findings; ordinary cases have a compact audit log.
                log.write(json.dumps({k: v for k, v in record.items() if k not in {"stdout", "stderr", "command"}}, ensure_ascii=False) + "\n")
                log.flush()
                job["executed"] += 1
                category = result["category"]
                job["counts"][category] = job["counts"].get(category, 0) + 1
                if strategy == "seed" and category not in {"passed", "cancelled"}:
                    write_json(folder / "baseline-error.json", record)
                    raise RuntimeError(
                        f"正常种子 #{case_no} 试运行未通过（{category}）。请检查依赖、入口、退出码约定和种子；"
                        "此结果保留为基线错误，不计作自动发现的 Bug。")
                if job["source"]:
                    same = result["signature"] == job["source"]["signature"]
                    verdict = ("inconclusive" if category in {"launch_error", "runner_error", "cancelled"}
                               else "reproduced" if same else "handled" if category in {"passed", "rejected"}
                               else "different_failure")
                    job["comparison"] = {"expected_signature": job["source"]["signature"],
                                         "actual_signature": result["signature"], "category": category,
                                         "same_failure": None if verdict == "inconclusive" else same,
                                         "verdict": verdict,
                                         "result": result}
                if category in {"launch_error", "runner_error"}:
                    raise RuntimeError(result["stderr"] or category)
                if category == "cancelled":
                    break
                if category not in FINDING_CATEGORIES:
                    update()
                    continue
                fingerprint = result["signature"]
                dest = folder / "findings" / fingerprint
                if fingerprint in groups:
                    finding = groups[fingerprint]
                    finding["occurrences"] += 1
                    occurrence = dest / "occurrences" / f"{case_no:05d}"
                    occurrence.mkdir(parents=True)
                    (occurrence / "input.bin").write_bytes(data)
                    write_json(occurrence / "result.json", record)
                else:
                    dest.mkdir(parents=True)
                    (dest / "input.bin").write_bytes(data)
                    finding = {"id": fingerprint, "category": category, "identity": result["identity"],
                               "signature": fingerprint, "occurrences": 1, "first_case": case_no,
                               "strategy": strategy, "result": result, "verification": [],
                               "minimization": None, "label": "待确认"}
                    groups[fingerprint] = finding
                    job["finding_count"] = len(groups)
                    write_json(dest / "finding.json", finding)
                    job["current"] = f"重放验证 · {category}"
                    update()
                    for _ in range(2):
                        if stopping():
                            break
                        verification = trial(data, True)
                        finding["verification"].append(verification)
                    stable = len(finding["verification"]) == 2 and all(
                        r["signature"] == fingerprint for r in finding["verification"])
                    finding["stable"] = stable
                    if stable and config.fuzz.minimize and category in {"exception", "crash"} and not stopping():
                        job["current"] = f"缩减输入 · {category}"
                        update()
                        def predicate(candidate):
                            if stopping():
                                return False
                            return trial(candidate, True)["signature"] == fingerprint
                        reduced, attempts = minimize(data, predicate, config.fuzz.minimize_attempts)
                        checked = trial(reduced, True) if not stopping() else None
                        valid = checked is not None and checked["signature"] == fingerprint
                        if valid:
                            (dest / "minimized.bin").write_bytes(reduced)
                        finding["minimization"] = {"original_bytes": len(data), "reduced_bytes": len(reduced),
                                                   "method": minimization_method(data),
                                                   "attempts": attempts, "verified": valid, "result": checked}
                write_json(dest / "finding.json", finding)
                update()
        if (folder / "STOP").exists():
            job["state"] = "cancelled"
            job["completion_reason"] = "user_stop"
            job["current"] = "已停止，已发现的证据保留"
        else:
            job["state"] = "completed"
            job["completion_reason"] = (
                "time_budget" if time.monotonic() >= deadline else
                "case_limit" if job["executed"] >= (1 if job["source"] else config.fuzz.max_cases) else
                "corpus_exhausted")
            job["current"] = "时间预算已用完" if time.monotonic() >= deadline else "测试完成"
        job["budget_exhausted"] = time.monotonic() >= deadline
    except Exception as exc:
        job["state"] = "failed"
        job["completion_reason"] = "error"
        job["error"] = str(exc)
        job["current"] = "执行失败，查看环境或平台错误"
        (folder / "worker-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        job["finished_at"] = now()
        job["updated_at"] = now()
        job["elapsed_seconds"] = round(time.monotonic() - began, 3)
        write_json(folder / "summary.json", job)
        # Publish the terminal state only after its final evidence is on disk.
        store.put(job)
