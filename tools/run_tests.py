#!/usr/bin/env python3
"""Validates samples/* (must pass) and tests/invalid/* (must fail) against PureQL-Specification.json.

A sample is a bare query; an invalid test is { "description", "query" }.
"""
import json
import sys
import time
from pathlib import Path

import jsonschema

root = Path(__file__).resolve().parent.parent
validator = jsonschema.Draft202012Validator(json.loads((root / "PureQL-Specification.json").read_text()))


def deepest(error):
    """Prefer the error that got furthest into the document: it names the offending node."""
    return (len(error.absolute_path), *jsonschema.exceptions.relevance(error))


def cases(expected):
    if expected == "valid":
        for path in sorted((root / "samples").glob("*.json")):
            yield path, json.loads(path.read_text()), ""
    else:
        for path in sorted((root / "tests" / "invalid").glob("*.json")):
            case = json.loads(path.read_text())
            yield path, case["query"], case["description"]


failures = 0
for expected in ["valid", "invalid"]:
    print(f"\n== {expected} ==")
    for path, query, description in cases(expected):
        started = time.perf_counter()
        errors = list(validator.iter_errors(query))
        error = jsonschema.exceptions.best_match(errors, key=deepest)
        elapsed = (time.perf_counter() - started) * 1000
        ok = (error is None) == (expected == "valid")
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {path.name:<52} {elapsed:7.1f} ms  {description}")
        if error is not None:
            location = "/".join(str(p) for p in error.absolute_path) or "<root>"
            print(f"      at {location}: {error.message[:110]}")


def nested(depth):
    """equal(if(equal(if(...)), …)): every level hides the operand type one step deeper."""
    uuid = {"source": "orders", "field": "id", "type": {"name": "uuid"}}
    condition = {"source": "orders", "field": "is_paid", "type": {"name": "boolean"}}
    for _ in range(depth):
        branch = {"operator": "if", "condition": condition, "then": uuid, "else": uuid}
        condition = {"operator": "equal", "left": branch, "right": uuid}
    return {
        "from": {"entity": "orders"},
        "where": condition,
        "select": [{"alias": "id", "type": {"name": "uuid"}, "expression": uuid}],
    }


# Validation must stay linear in nesting depth. Without operand probes this
# query took minutes; now it takes milliseconds.
print("\n== performance ==")
started = time.perf_counter()
valid = validator.is_valid(nested(DEPTH := 30))
elapsed = time.perf_counter() - started
ok = valid and elapsed < 2
failures += not ok
print(f"{'PASS' if ok else 'FAIL'}  {f'equal / if nested {DEPTH} deep':<52} {elapsed * 1000:7.1f} ms")

print(f"\n{'all passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
