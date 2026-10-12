"""Budgeted reduction preserving JSON syntax when input is JSON."""
import json
from itertools import islice

from .json_tools import encode, nodes, replace, round_robin


def method(data):
    try:
        json.loads(data)
        return "json-structure"
    except (ValueError, UnicodeError, RecursionError):
        return "byte-deletion"


def reductions(node):
    if isinstance(node, (dict, list)):
        keys = list(islice(node, 64)) if isinstance(node, dict) else list(range(min(len(node), 64)))
        width = max(1, len(keys))
        while keys:
            for start in range(0, len(keys), width):
                removed = set(keys[start:start + width])
                if isinstance(node, dict):
                    yield {key: value for key, value in node.items() if key not in removed}
                else:
                    yield [value for i, value in enumerate(node) if i not in removed]
            if width == 1:
                break
            width = max(1, width // 2)
    elif isinstance(node, str):
        yield ""
        if len(node) > 1:
            yield node[:len(node) // 2]
            yield node[len(node) // 2:]
    elif isinstance(node, bool):
        yield False
    elif isinstance(node, (int, float)):
        yield 0
        yield 1
        yield -1


def candidates(obj):
    def at_node(path, node):
        for value in reductions(node):
            yield encode(replace(obj, path, value))
    yield from round_robin(at_node(path, node) for path, node in nodes(obj))


def proposals(obj):
    yield encode(obj)
    yield from candidates(obj)


def minimize_json(data, predicate, budget):
    current, attempts = data, 0
    while attempts < budget:
        try:
            obj = json.loads(current)
            seen = {current}
            for candidate in proposals(obj):
                if len(candidate) >= len(current) or candidate in seen:
                    continue
                seen.add(candidate)
                attempts += 1
                if predicate(candidate):
                    current = candidate
                    break
                if attempts >= budget:
                    return current, attempts
            else:
                return current, attempts
        except (ValueError, UnicodeError, RecursionError):
            return current, attempts
    return current, attempts


def minimize(data, predicate, budget):
    """Every accepted reduction must preserve the caller's failure predicate."""
    if method(data) == "json-structure":
        return minimize_json(data, predicate, budget)
    current, granularity, attempts = data, 2, 0
    while current and attempts < budget:
        width = max(1, (len(current) + granularity - 1) // granularity)
        reduced = False
        for start in range(0, len(current), width):
            if attempts >= budget:
                break
            candidate = current[:start] + current[start + width:]
            attempts += 1
            if predicate(candidate):
                current = candidate
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if not reduced:
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
    return current, attempts
