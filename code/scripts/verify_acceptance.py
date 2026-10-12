"""Reproduce the course acceptance case and export portable evidence."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from crashlens.config import load_config
from crashlens.engine import create_job, run_job
from crashlens.process import execute
from crashlens.store import Store, now, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(".crashlens/acceptance"))
    parser.add_argument("--output", type=Path, default=Path("code/examples/acceptance"))
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    examples = project / "code" / "examples"
    store = Store(args.data_dir)
    runs = []
    for version in ("datacraft-buggy", "datacraft-fixed"):
        job = create_job(store, str(examples / version))
        print(f"Running {version}: {job['id']}", flush=True)
        run_job(store.home, job["id"])
        result = store.get(job["id"])
        if result["state"] != "completed" or result["executed"] != 80:
            raise RuntimeError(f"Acceptance did not complete: {result}")
        runs.append(result)
    buggy, fixed = runs
    findings = store.findings(buggy["id"])
    if fixed["finding_count"] or not any(f["identity"].startswith("ZeroDivisionError:") for f in findings):
        raise RuntimeError("Unexpected fixed/buggy results")
    if not any(f["category"] == "timeout" for f in findings):
        raise RuntimeError("Timeout example was not exercised")
    original_root, original_config = load_config(str(examples / "datacraft-buggy"))
    fixed_root, fixed_config = load_config(str(examples / "datacraft-fixed"))
    regressions = []
    args.output.mkdir(parents=True, exist_ok=True)
    for finding in findings:
        source = store.folder(buggy["id"]) / "findings" / finding["id"]
        input_path = source / "minimized.bin" if (source / "minimized.bin").exists() else source / "input.bin"
        data = input_path.read_bytes()
        replay = execute(original_root, original_config, data, store.home / "scratch")
        regression = execute(fixed_root, fixed_config, data, store.home / "scratch")
        if replay["signature"] != finding["signature"]:
            raise RuntimeError(f"Replay did not reproduce {finding['id']}")
        if regression["category"] not in {"passed", "rejected"}:
            raise RuntimeError(f"Fixed version failed {finding['id']}")
        destination = args.output / "inputs" / finding["id"]
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "input.bin", destination / "input.bin")
        if (source / "minimized.bin").exists():
            shutil.copyfile(source / "minimized.bin", destination / "minimized.bin")
        regressions.append({"finding_id": finding["id"], "input_variant": input_path.name,
                            "replay": replay, "fixed": regression})
    payload = {"verified_at": now(), "kind": "Artificial teaching defects, not third-party vulnerabilities",
               "buggy": buggy, "fixed": fixed, "findings": findings, "regressions": regressions}
    # Published evidence is portable; originals remain untouched in the local data directory.
    def portable(value):
        if isinstance(value, str):
            return value.replace(str(project), "<PROJECT_ROOT>").replace(project.as_posix(), "<PROJECT_ROOT>")
        if isinstance(value, list):
            return [portable(item) for item in value]
        if isinstance(value, dict):
            return {key: portable(item) for key, item in value.items()}
        return value
    payload = portable(payload)
    write_json(args.output / "acceptance.json", payload)
    rows = ["# 实际验收结果\n", f"验证时间：{payload['verified_at']}\n",
            "该文件由 `code/scripts/verify_acceptance.py` 根据真实执行结果生成。教学缺陷是人工设置的。公开 JSON 中的项目绝对路径替换为 `<PROJECT_ROOT>`，本地原始证据保持不变。\n",
            "| 目标 | 生成用例 | 正常通过 | 正常拒绝 | 异常 | 超时 | 失败分组 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for version, result in zip(("缺陷版本", "修复版本"), runs):
        c = result["counts"]
        rows.append(f"| {version} | {result['executed']} | {c.get('passed',0)} | {c.get('rejected',0)} | {c.get('exception',0)} | {c.get('timeout',0)} | {result['finding_count']} |")
    rows += ["\n每个失败分组都使用代表输入（优先已验证缩减版本）进行了额外独立重放，并在修复版本上执行同一输入。\n",
             "| 分组 | 类别 | 原始 / 缩减字节 | 原版本重放 | 修复版本 |",
             "| --- | --- | ---: | --- | --- |"]
    for finding, regression in zip(findings, regressions):
        minimum = finding["minimization"]
        size = f"{finding['result']['input_bytes']} / {minimum['reduced_bytes'] if minimum and minimum['verified'] else '—'}"
        rows.append(f"| `{finding['id']}` | {finding['category']} | {size} | {regression['replay']['category']}，签名一致 | {regression['fixed']['category']} |")
    rows += ["\n完整配置、环境、源文件哈希、首次堆栈、自动重放、缩减验证和独立回归结果见 [acceptance.json](acceptance.json)。原始输入与缩减输入在 `inputs/<signature>/`。\n",
             "复现示例（仓库根目录，替换实际 signature）：\n",
             "```powershell\n.\\.venv\\Scripts\\python.exe -m crashlens replay .\\code\\examples\\datacraft-buggy .\\code\\examples\\acceptance\\inputs\\<signature>\\input.bin --data-dir .crashlens-cli\n```\n",
             "本批用例的结果见上表。失败按异常类型和调用位置归组，可结合触发输入排查具体原因。"]
    (args.output / "readme.md").write_text("\n".join(rows), encoding="utf-8")
    print(json.dumps({"buggy": buggy["counts"], "fixed": fixed["counts"],
                      "groups": len(findings), "regressions": len(regressions), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
