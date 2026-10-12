"""Export actual visible Codex conversation records; never export hidden reasoning."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def visible_records(source: Path):
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # A live session may end with a partially written line.
            continue
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload", {})
        kind = payload.get("type")
        if kind == "message":
            if payload.get("role") not in {"user", "assistant"} or payload.get("channel") == "analysis":
                continue
            texts = [item.get("text", "") for item in payload.get("content", [])
                     if item.get("type") in {"input_text", "output_text", "text"}]
            text = "\n".join(texts)
            # Host-injected user-role context is not a human conversation message.
            if text.startswith(("<recommended_plugins>", "# AGENTS.md instructions", "<environment_context>")):
                continue
            if "<in-app-browser-context" in text and "## My request:" in text:
                text = text.split("## My request:", 1)[1].strip()
            if not text:
                continue
            payload = {"type": "message", "role": payload["role"],
                       "channel": payload.get("channel"), "text": text}
        elif kind not in {"function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output"}:
            continue
        yield {"source_line": number, "timestamp": entry.get("timestamp"), "payload": payload}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="The explicit session JSONL file")
    parser.add_argument("--output", type=Path, default=Path("prompt"))
    args = parser.parse_args()
    source = args.source.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    records = list(visible_records(source))
    # Redact local account paths, retaining project-relative layout and exact code.
    redactions = [
        (r"(?i)[A-Z]:\\\\Users\\\\[^\\\s\"']+", r"<USER_HOME>"),
        (r"(?i)[A-Z]:\\Users\\[^\\\s\"']+", r"<USER_HOME>"),
        (r"(?i)[A-Z]:/Users/[^/\s\"']+", r"<USER_HOME>"),
    ]
    for record in records:
        def redact(value):
            if isinstance(value, str):
                for pattern, replacement in redactions:
                    value = re.sub(pattern, replacement, value)
                # Public transcript does not need ephemeral browser session secrets.
                value = re.sub(r'(crashlens-token[\"\s]+content=\")[^\"]+', r'\1<REDACTED>', value)
                return value
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        record["payload"] = redact(record["payload"])
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    machine = args.output / "conversation.visible.jsonl"
    machine.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    parts = ["# 实际开发与调试对话\n", f"导出时间：{stamp}\n",
             "这是截至导出时的真实可见记录。用户目录路径已脱敏；系统/开发者提示、隐藏推理和宿主环境注入不导出。工具调用与结果单独保留，不用摘要替代。后续新对话需重新运行导出脚本。\n"]
    for index, record in enumerate(records, 1):
        item = record["payload"]
        who = item.get("role") or item.get("name") or item["type"]
        parts.append(f"\n## {index}. {who} / {record['timestamp']} / 源行 {record['source_line']}\n")
        if item["type"] == "message":
            parts.append(item["text"] + "\n")
        else:
            encoded = json.dumps(item, ensure_ascii=False, indent=2)
            fence = "`" * max(4, max((len(m.group()) for m in re.finditer(r"`+", encoded)), default=0) + 1)
            parts.append(f"<details><summary>实际工具调用或结果</summary>\n\n{fence}json\n{encoded}\n{fence}\n\n</details>\n")
    (args.output / "conversation.md").write_text("\n".join(parts), encoding="utf-8")
    manifest = {"exported_at": stamp, "source_filename": source.name,
                "records": len(records), "visible_jsonl_sha256": hashlib.sha256(machine.read_bytes()).hexdigest(),
                "scope": "Actual visible user/assistant messages and tool calls/results up to export time",
                "excluded": ["hidden reasoning", "system/developer instructions", "host-injected environment context"],
                "redactions": ["local user home path", "recognizable ephemeral page token"],
                "note": "This export precedes the assistant's final response in its current turn; rerun after later turns."}
    (args.output / "export-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

