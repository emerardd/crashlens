"""Bounded JSON traversal shared by mutation and input reduction."""
from collections import deque
from itertools import islice
import copy
import json


def encode(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def nodes(value, max_nodes=256, max_depth=32):
    queue = deque([((), value)])
    for _ in range(max_nodes):
        if not queue:
            break
        path, node = queue.popleft()
        yield path, node
        if len(path) >= max_depth:
            continue
        if isinstance(node, dict):
            children = islice(node.items(), 64)
        elif isinstance(node, list):
            children = islice(enumerate(node), 64)
        else:
            continue
        for key, child in children:
            if len(queue) >= max_nodes:
                break
            queue.append((path + (key,), child))


def replace(value, path, replacement):
    if not path:
        return replacement
    other = copy.deepcopy(value)
    parent = other
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = replacement
    return other


def round_robin(iterators):
    pending = deque(map(iter, iterators))
    while pending:
        current = pending.popleft()
        try:
            yield next(current)
        except StopIteration:
            continue
        pending.append(current)
