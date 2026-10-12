"""Teaching-only defects. The platform must never import this program."""
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    args = parser.parse_args()
    if args.input:
        with open(args.input, "rb") as stream:
            raw = stream.read()
    else:
        raw = sys.stdin.buffer.read()
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        print("Invalid JSON", file=sys.stderr)
        return 2
    if not isinstance(obj, dict):
        print("Expected an object", file=sys.stderr)
        return 2
    # Teaching defect A: missing field is accessed without validation.
    operation = obj["operation"]
    if operation == "ratio":
        # Teaching defect B: division by zero and type mismatches are not handled.
        value = obj["numerator"] / obj["denominator"]
    elif operation == "repeat":
        count = obj["count"]
        if not isinstance(count, int) or not isinstance(obj.get("text"), str):
            return 2
        if count > 100:
            return 2
        # Teaching defect C: negative count never reaches zero.
        value = ""
        while count:
            if len(value) < 4096:
                value += obj["text"]
            count -= 1
    else:
        print("Unknown operation", file=sys.stderr)
        return 2
    sys.stdout.buffer.write((json.dumps({"value": value}, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
