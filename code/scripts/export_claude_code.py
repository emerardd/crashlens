"""Export actual visible Claude Code conversation records; never export hidden reasoning."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REDACTIONS = [
    (r"(?i)[A-Z]:\\\\Users\\\\[^\\\s\"']+", r"<USER_HOME>"),
    (r"(?i)[A-Z]:\\Users\\[^\\\s\"']+", r"<USER_HOME>"),
    (r"(?i)[A-Z]:/Users/[^/\s\"']+", r"<USER_HOME>"),
    (r"(?i)/[a-z]/Users/[^/\s\"']+", r"<USER_HOME>"),
    (r"[\w.+-]+@[\w-]+\.[\w.]+", r"<EMAIL>"),
    (r"\b(gho|ghp|github_pat|sk-ant|sk)_[A-Za-z0-9_\-]{8,}", r"<REDACTED_TOKEN>"),
]


def redact(value):
    if isinstance(value, str):
        # Host-injected context inside user turns is not part of the human conversation.
        value = re.sub(r"<system-reminder>.*?</system-reminder>", "", value, flags=re.S)
        for pattern, replacement in REDACTIONS:
            value = re.sub(pattern, replacement, value)
        # The local account name also appears in ls output and temp directory names.
        value = re.sub(rf"(?i)(?<![A-Za-z0-9]){re.escape(Path.home().name)}(?![A-Za-z0-9])", "<USER>", value)
        value = re.sub(r'(crashlens-token[\"\s]+content=\")[^\"]+', r'\1<REDACTED>', value)
        return value.strip("\n")
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def flatten(content):
    """Turn tool_result content into plain text; images become a placeholder."""
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif item.get("type") == "image":
            parts.append("[图片：截图或录像帧，未导出]")
    return "\n".join(parts)


def visible_records(source: Path):
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # A live session may end with a partially written line.
        if entry.get("type") not in {"user", "assistant"} or entry.get("isMeta") or entry.get("isSidechain"):
            continue
        content = entry.get("message", {}).get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for item in content or []:
            kind = item.get("type")
            if kind == "text":
                text = redact(item.get("text", ""))
                if not text or text.startswith(("<command-", "<local-command")):
                    continue
                payload = {"type": "message", "role": entry["type"], "text": text}
            elif kind == "tool_use":
                payload = {"type": "tool_call", "name": item.get("name"), "input": redact(item.get("input"))}
            elif kind == "tool_result":
                payload = {"type": "tool_result", "is_error": bool(item.get("is_error")),
                           "output": redact(flatten(item.get("content")))}
            else:  # thinking / redacted_thinking / images in user turns are not exported
                continue
            yield {"source_line": number, "timestamp": entry.get("timestamp"), "payload": payload}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="The explicit Claude Code session JSONL file")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Claude Code 对话")
    args = parser.parse_args()
    source = args.source.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    records = list(visible_records(source))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    machine = args.output / "conversation.visible.jsonl"
    machine.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    parts = [f"# {args.title}\n", f"导出时间：{stamp}\n",
             "这是截至导出时的真实可见记录（Claude Code）。用户目录、邮箱与令牌已脱敏；系统提示、隐藏推理和宿主注入的上下文不导出；截图类图片以占位符代替。\n"]
    for index, record in enumerate(records, 1):
        item = record["payload"]
        who = item.get("role") or item.get("name") or item["type"]
        parts.append(f"\n## {index}. {who} / {record['timestamp']}\n")
        if item["type"] == "message":
            parts.append(item["text"] + "\n")
        else:
            encoded = json.dumps(item, ensure_ascii=False, indent=2)
            fence = "`" * max(4, max((len(m.group()) for m in re.finditer(r"`+", encoded)), default=0) + 1)
            label = "工具调用" if item["type"] == "tool_call" else "工具结果"
            parts.append(f"<details><summary>{label}</summary>\n\n{fence}json\n{encoded}\n{fence}\n\n</details>\n")
    (args.output / "conversation.md").write_text("\n".join(parts), encoding="utf-8")
    manifest = {"exported_at": stamp, "source_filename": source.name, "tool": "Claude Code",
                "records": len(records), "visible_jsonl_sha256": hashlib.sha256(machine.read_bytes()).hexdigest(),
                "excluded": ["hidden reasoning", "system instructions", "host-injected context", "screenshots"],
                "redactions": ["local user home path", "email address", "access tokens", "ephemeral page token"],
                "note": "Turns after the export time are not included; rerun to refresh."}
    (args.output / "export-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
