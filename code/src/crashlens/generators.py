"""Generic deterministic boundary/JSON/byte mutations; no target-specific keys."""
from __future__ import annotations

import json
import random
from collections.abc import Iterator
from itertools import islice

from .json_tools import encode, nodes, replace, round_robin


def replacements(value):
    choices = [None, "", [], {}]
    if isinstance(value, bool):
        choices = [not value] + choices
    elif isinstance(value, (int, float)):
        choices = [0, -1, 1, 2147483647, -2147483648] + choices
    elif isinstance(value, str):
        choices += ["A" * 256, "\x00", "中文🙂"]
    return choices


def local_mutations(node):
    if isinstance(node, dict):
        keys = list(islice(node, 64))
        for key in keys:
            other = dict(node)
            del other[key]
            yield other
        for key in keys:
            for replacement in replacements(node[key]):
                yield {**node, key: replacement}
    elif isinstance(node, list):
        yield []
        for i in range(min(len(node), 64)):
            yield node[:i] + node[i + 1:]
            for replacement in replacements(node[i]):
                yield node[:i] + [replacement] + node[i + 1:]
    else:
        yield from replacements(node)


def mutate_node(obj, path, node):
    for value in local_mutations(node):
        yield encode(replace(obj, path, value))


def structured(data: bytes) -> Iterator[bytes]:
    # Unsupported parser/serializer depths must not abort unrelated strategies.
    try:
        yield from _structured(data)
    except (ValueError, UnicodeError, RecursionError):
        return


def _structured(data: bytes) -> Iterator[bytes]:
    try:
        obj = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        return

    yield encode(obj)
    yield from round_robin(mutate_node(obj, path, node) for path, node in nodes(obj))


def generate(seeds: list[bytes], max_cases: int, random_seed: int,
             max_bytes: int) -> Iterator[tuple[str, bytes]]:
    if not seeds or max_cases <= 0:
        return
    seen = set()
    count = 0
    # Generate lazily: a small case budget must not first materialize every
    # mutation of a large structured input.
    initial = [("seed", data) for data in seeds] + [
        ("boundary", data) for data in [b"", b"\n", b"{}", b"[]", b"null", b"\xff", b"A" * min(4096, max_bytes)]]
    for strategy, data in initial:
        if len(data) > max_bytes or data in seen:
            continue
        seen.add(data)
        yield strategy, data
        count += 1
        if count >= max_cases:
            return
    pending = {"json-structure": iter(round_robin(structured(data) for data in seeds)),
               "byte-mutation": iter(byte_mutations(seeds, random.Random(random_seed), max_cases * 30, max_bytes))}
    # Advance even duplicate attempts: a wide seed cannot starve other seeds
    # or the byte strategy. Keep three structured attempts per byte attempt.
    while pending and count < max_cases:
        for strategy in ["json-structure"] * 3 + ["byte-mutation"]:
            if strategy not in pending:
                continue
            try:
                data = next(pending[strategy])
            except StopIteration:
                del pending[strategy]
                continue
            if len(data) > max_bytes or data in seen:
                continue
            seen.add(data)
            yield strategy, data
            count += 1
            if count >= max_cases:
                return


def byte_mutations(seeds, rng, attempts, max_bytes):
    for _ in range(attempts):
        original = rng.choice(seeds)
        pos = rng.randrange(len(original) + 1)
        end = min(len(original), pos + rng.randint(1, 16))
        operation = rng.randrange(5)
        if operation == 0:
            data = original[:pos] + original[end:]
        elif operation == 1:
            data = original[:pos] + rng.randbytes(rng.randint(1, 16)) + original[pos:]
        elif operation == 2:
            data = original[:pos] + rng.choice([b"0", b"-1", b"null", b"[]", b"\x00"]) + original[end:]
        elif operation == 3:
            data = original[:pos] + original[pos:end] * rng.randint(2, 8) + original[end:]
        else:
            data = original[:pos] + rng.choice(seeds)
        yield data[:max_bytes]
