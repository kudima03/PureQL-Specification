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

print(f"\n{'all passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
