"""Validated version of the educational DataCraft CLI."""
import argparse
import json
import math
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
        return reject("Invalid JSON")
    if not isinstance(obj, dict):
        return reject("Expected an object")
    operation = obj.get("operation")
    if operation == "ratio":
        numerator, denominator = obj.get("numerator"), obj.get("denominator")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (numerator, denominator)):
            return reject("Expected numeric operands")
        if denominator == 0:
            return reject("Denominator must not be zero")
        try:
            value = numerator / denominator
            if not math.isfinite(value):
                return reject("Result must be finite")
        except (OverflowError, ValueError):
            return reject("Numeric value out of range")
    elif operation == "repeat":
        count, text = obj.get("count"), obj.get("text")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100:
            return reject("Count must be an integer in [0, 100]")
        if not isinstance(text, str) or len(text) * count > 4096:
            return reject("Invalid text or result too large")
        value = text * count
    else:
        return reject("Unknown operation")
    sys.stdout.buffer.write((json.dumps({"value": value}, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0


def reject(message):
    print(message, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
