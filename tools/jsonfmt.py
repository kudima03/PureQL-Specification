"""Compact JSON formatting for test files: objects stay on one line while they fit."""
import json

WIDTH = 110


def _inline(value):
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{json.dumps(k)}: {_inline(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_inline(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def dumps(value, depth=0, column=0):
    """`depth` sets the indentation, `column` is where the value starts (for the width check)."""
    line = _inline(value)
    if column + len(line) <= WIDTH or not isinstance(value, (dict, list)) or not value:
        return line
    pad = "  " * (depth + 1)
    if isinstance(value, dict):
        items = [
            f"{pad}{json.dumps(k)}: {dumps(v, depth + 1, len(pad) + len(json.dumps(k)) + 2)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + "  " * depth + "}"
    items = [f"{pad}{dumps(v, depth + 1, len(pad))}" for v in value]
    return "[\n" + ",\n".join(items) + "\n" + "  " * depth + "]"
