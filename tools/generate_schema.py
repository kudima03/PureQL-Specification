#!/usr/bin/env python3
"""Generates PureQL-Specification.json. Never edit the schema by hand: change this file and rerun it.

Every expression definition is named `<type>@<context>` or
`<type>.nullable@<context>`. The context is chosen by position (which clause,
inside an aggregate body or not) and passed down via $ref; the result type is
chosen bottom-up by the matching branch. Operators are shared between
contexts: `add.integer@row` and `add.integer@group` have the same shape and
differ only in what their operands may be.

Contexts:
  row         where, join.on, groupBy keys, aggregate selector/predicate.
              Fields allowed, aggregates not.
  projection  select / orderBy of a non-grouped query.
              Fields allowed, aggregates over "all" rows (broadcast).
  group       select / having / orderBy of a grouped query.
              No fields; group keys and aggregates over "group" or "all" rows.

Subtyping (each arrow means "accepted wherever the right side is expected"):
  T -> T.nullable                      a non-null value is a valid T?
  integer -> decimal                   implicit widening, as in C#

There is no untyped null: a null literal is written with its type,
{"type": {"name": "uuid", "nullable": true}, "value": null}. So the type of
every expression is determined by its subtree alone, never by its context.

A document is the main query plus optional `subqueries`: named queries the
main query and later subqueries can read from (`from` / `join` with
`subquery`, or `in` over one of their columns). Every select column declares
its alias and type, and the validator checks the expression against that
type, so each subquery has a verified output schema. Matching a reference to
that schema is name resolution and is left to the interpreter.

Null semantics follow C# / LINQ to Objects:
  - arithmetic, concat, date/time math, if, round/floor/ceiling are lifted:
    nullable operands give a nullable result (null if any operand is null);
  - equal / notEqual / comparisons / in accept nullable operands and return a
    non-null boolean (null == null is true, any ordering against null is false);
  - every condition (where, having, on, and/or/not, if.condition, aggregate
    predicate) requires a non-null boolean.
"""
import json
from pathlib import Path

VERSION = "0.1.0-preview.0.5.0"
SCHEMA_ID = f"https://github.com/kudima03/PureQL-Specification/releases/download/{VERSION}/PureQL-Specification.json"

TYPES = ["integer", "decimal", "string", "boolean", "date", "time", "datetime", "uuid"]
SUBTYPES = {"decimal": ["integer"]}
# integer operands are compared / tested for equality through decimal.
EQUATABLE = ["decimal", "string", "boolean", "date", "time", "datetime", "uuid"]
COMPARABLE = ["decimal", "string", "date", "time", "datetime"]
# min / max keep the selector type, so integer is listed separately.
ORDERED = ["integer", "decimal", "string", "date", "time", "datetime"]
# average: selector type -> result type
AVERAGEABLE = {"decimal": "decimal", "date": "date", "time": "time", "datetime": "datetime"}

# [0-9] rather than \d: in Python's `re` \d also matches non-ASCII digits,
# in ECMA-262 it does not. No lookahead, for the same portability reason.
DATE = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
TIME = r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?"
# Mandatory, RFC 3339 range. -00:00 ("offset unknown") is excluded; +00:00 is Z.
OFFSET = (
    r"(Z"
    r"|\+([01][0-9]|2[0-3]):[0-5][0-9]"
    r"|-(0[1-9]|1[0-9]|2[0-3]):[0-5][0-9]"
    r"|-00:(0[1-9]|[1-5][0-9]))"
)

VALUE = {
    "integer": {"type": "integer"},
    "decimal": {"type": "number"},
    "string": {"type": "string"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "pattern": f"^{DATE}$"},
    "time": {"type": "string", "pattern": f"^{TIME}$"},
    "datetime": {"type": "string", "pattern": f"^{DATE}T{TIME}{OFFSET}$"},
    "uuid": {
        "type": "string",
        "pattern": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
    },
}

CONTEXTS = {
    "row": {"fields": True, "keys": False, "over": []},
    "projection": {"fields": True, "keys": False, "over": ["all"]},
    "group": {"fields": False, "keys": True, "over": ["group", "all"]},
}

NAME = {"type": "string", "minLength": 1}

defs = {}


def ref(name):
    return {"$ref": f"#/$defs/{name}"}


def obj(required, props):
    return {
        "type": "object",
        "required": required,
        "properties": props,
        "additionalProperties": False,
    }


def suffix(nullable):
    return ".nullable" if nullable else ""


def expr(t, ctx, nullable=False):
    return ref(f"{t}{suffix(nullable)}@{ctx}")


def array_of(item, min_items):
    return {"type": "array", "items": item, "minItems": min_items}


# --- leaves ---------------------------------------------------------------

for t in TYPES:
    defs[f"type.{t}"] = obj(["name"], {"name": {"const": t}, "nullable": {"const": False}})
    defs[f"type.{t}.nullable"] = obj(
        ["name", "nullable"], {"name": {"const": t}, "nullable": {"const": True}}
    )
    defs[f"type.{t}List"] = obj(["name"], {"name": {"const": f"{t}List"}})
    # A literal is nullable exactly when its value is null.
    defs[f"literal.{t}"] = obj(["type", "value"], {"type": ref(f"type.{t}"), "value": VALUE[t]})
    defs[f"literal.{t}.nullable"] = obj(
        ["type", "value"], {"type": ref(f"type.{t}.nullable"), "value": {"type": "null"}}
    )

    for nullable in [False, True]:
        s = suffix(nullable)
        defs[f"param.{t}{s}"] = obj(
            ["param_name", "type"], {"param_name": NAME, "type": ref(f"type.{t}{s}")}
        )
        # `source` is the entity, subquery or alias the column comes from.
        defs[f"field.{t}{s}"] = obj(
            ["source", "field", "type"],
            {"source": NAME, "field": NAME, "type": ref(f"type.{t}{s}")},
        )
        defs[f"key.{t}{s}"] = obj(
            ["key", "type"],
            {"key": {"type": "integer", "minimum": 0}, "type": ref(f"type.{t}{s}")},
        )

    # A list is a value (List<T>), not a column: it is accepted only by `in`.
    defs[f"list.{t}"] = {
        "anyOf": [
            obj(
                ["type", "value"],
                {"type": ref(f"type.{t}List"), "value": {"type": "array", "items": VALUE[t]}},
            ),
            obj(["param_name", "type"], {"param_name": NAME, "type": ref(f"type.{t}List")}),
            # Every value of one column of a subquery's result.
            obj(
                ["subquery", "field", "type"],
                {
                    "subquery": NAME,
                    "field": NAME,
                    "type": {"anyOf": [ref(f"type.{t}"), ref(f"type.{t}.nullable")]},
                },
            ),
        ]
        + [ref(f"list.{sub}") for sub in SUBTYPES.get(t, [])]
    }

# --- operators, per context -----------------------------------------------

for ctx, rules in CONTEXTS.items():
    # operator name -> list of (result type, result nullable, definition name)
    ops = {}

    def op(name, t, nullable, def_name, schema):
        defs[def_name] = schema
        ops.setdefault(name, []).append((t, nullable, def_name))

    def lifted(name, t, build, tag=None):
        """Strict variant (non-null operands -> T) and lifted one (nullable operands -> T?)."""
        base = f"{name}.{tag or t}"
        op(name, t, False, f"{base}@{ctx}", build(False))
        op(name, t, True, f"{base}.nullable@{ctx}", build(True))

    def nary(name, operand_t):
        return lambda n: obj(
            ["operator", "values"],
            {"operator": {"const": name}, "values": array_of(expr(operand_t, ctx, n), 2)},
        )

    def binary(name, left_t, right_t):
        return lambda n: obj(
            ["operator", "left", "right"],
            {
                "operator": {"const": name},
                "left": expr(left_t, ctx, n),
                "right": expr(right_t, ctx, n),
            },
        )

    def unary(name, operand_t):
        return lambda n: obj(
            ["operator", "value"], {"operator": {"const": name}, "value": expr(operand_t, ctx, n)}
        )

    # numbers
    for t in ["integer", "decimal"]:
        for name in ["add", "subtract", "multiply"]:
            lifted(name, t, nary(name, t))
    lifted("divide", "decimal", nary("divide", "decimal"))
    for name in ["integerDivide", "modulo"]:
        lifted(name, "integer", binary(name, "integer", "integer"))
    for name in ["floor", "ceiling"]:
        lifted(name, "integer", unary(name, "decimal"))
    lifted("round", "integer", unary("round", "decimal"))
    lifted("round", "decimal", lambda n: obj(
        ["operator", "value", "digits"],
        {
            "operator": {"const": "round"},
            "value": expr("decimal", ctx, n),
            "digits": expr("integer", ctx),
        },
    ), tag="decimal.digits")

    # strings
    lifted("concat", "string", nary("concat", "string"))

    # date / time / datetime math
    lifted("dateAddDays", "date", binary("dateAddDays", "date", "integer"))
    lifted("dateDiffDays", "integer", binary("dateDiffDays", "date", "date"))
    lifted("timeAddSeconds", "time", binary("timeAddSeconds", "time", "decimal"))
    lifted("timeDiffSeconds", "decimal", binary("timeDiffSeconds", "time", "time"))
    lifted("datetimeAddSeconds", "datetime", binary("datetimeAddSeconds", "datetime", "decimal"))
    lifted("datetimeDiffSeconds", "decimal", binary("datetimeDiffSeconds", "datetime", "datetime"))

    # booleans: conditions are always non-null
    for name in ["and", "or"]:
        op(name, "boolean", False, f"{name}@{ctx}", obj(
            ["operator", "conditions"],
            {"operator": {"const": name}, "conditions": array_of(expr("boolean", ctx), 1)},
        ))
    op("not", "boolean", False, f"not@{ctx}", obj(
        ["operator", "condition"],
        {"operator": {"const": "not"}, "condition": expr("boolean", ctx)},
    ))

    for t in EQUATABLE:
        for name in ["equal", "notEqual"]:
            op(name, "boolean", False, f"{name}.{t}@{ctx}", obj(
                ["operator", "left", "right"],
                {
                    "operator": {"const": name},
                    "left": expr(t, ctx, True),
                    "right": expr(t, ctx, True),
                },
            ))
        op("in", "boolean", False, f"in.{t}@{ctx}", obj(
            ["operator", "value", "list"],
            {"operator": {"const": "in"}, "value": expr(t, ctx, True), "list": ref(f"list.{t}")},
        ))

    for t in COMPARABLE:
        for name in ["greaterThan", "lessThan", "greaterThanOrEqual", "lessThanOrEqual"]:
            op(name, "boolean", False, f"{name}.{t}@{ctx}", obj(
                ["operator", "left", "right"],
                {
                    "operator": {"const": name},
                    "left": expr(t, ctx, True),
                    "right": expr(t, ctx, True),
                },
            ))

    # conditional and null handling, for every type
    for t in TYPES:
        lifted("if", t, lambda n, t=t: obj(
            ["operator", "condition", "then", "else"],
            {
                "operator": {"const": "if"},
                "condition": expr("boolean", ctx),
                "then": expr(t, ctx, n),
                "else": expr(t, ctx, n),
            },
        ))
        # coalesce is non-null as soon as one operand is non-null.
        op("coalesce", t, False, f"coalesce.{t}@{ctx}", obj(
            ["operator", "values"],
            {
                "operator": {"const": "coalesce"},
                "values": {**array_of(expr(t, ctx, True), 2), "contains": expr(t, ctx)},
            },
        ))
        op("coalesce", t, True, f"coalesce.{t}.nullable@{ctx}", obj(
            ["operator", "values"],
            {"operator": {"const": "coalesce"}, "values": array_of(expr(t, ctx, True), 2)},
        ))

    # Aggregates: the body (selector / predicate) is always `row` context,
    # which has no aggregates, so aggregates cannot nest. Nulls produced by the
    # selector are skipped, as in Enumerable.Sum / Min / Max over T?.
    if rules["over"]:
        over = {"enum": rules["over"]}
        predicate = expr("boolean", "row")

        def aggregate(name, selector_t, result_t):
            # May see no rows (predicate, over "all", all-null selector) -> T?.
            op(name, result_t, True, f"{name}.{selector_t}.nullable@{ctx}", obj(
                ["operator", "over", "selector"],
                {
                    "operator": {"const": name},
                    "over": over,
                    "selector": expr(selector_t, "row", True),
                    "predicate": predicate,
                },
            ))
            # A group is never empty, so an unfiltered non-null selector gives T.
            if "group" in rules["over"]:
                op(name, result_t, False, f"{name}.{selector_t}@{ctx}", obj(
                    ["operator", "over", "selector"],
                    {
                        "operator": {"const": name},
                        "over": {"const": "group"},
                        "selector": expr(selector_t, "row"),
                    },
                ))

        op("count", "integer", False, f"count@{ctx}", obj(
            ["operator", "over"],
            {"operator": {"const": "count"}, "over": over, "predicate": predicate},
        ))
        for t in ["integer", "decimal"]:
            # Sum of no rows is 0, never null.
            op("sum", t, False, f"sum.{t}@{ctx}", obj(
                ["operator", "over", "selector"],
                {
                    "operator": {"const": "sum"},
                    "over": over,
                    "selector": expr(t, "row", True),
                    "predicate": predicate,
                },
            ))
        for selector_t, result_t in AVERAGEABLE.items():
            aggregate("average", selector_t, result_t)
        for t in ORDERED:
            aggregate("min", t, t)
            aggregate("max", t, t)
        for name in ["any", "all"]:
            op(name, "boolean", False, f"{name}@{ctx}", obj(
                ["operator", "over", "predicate"],
                {"operator": {"const": name}, "over": over, "predicate": predicate},
            ))

    # `<type>[.nullable]@<ctx>`: leaves, subtypes, plus operators dispatched on
    # `operator` so the validator only tries the definitions of that operator.
    for t in TYPES:
        for nullable in [False, True]:
            leaves = []
            for leaf_nullable in [False, True] if nullable else [False]:
                s = suffix(leaf_nullable)
                if rules["keys"]:
                    leaves.append(ref(f"key.{t}{s}"))
                if rules["fields"]:
                    leaves.append(ref(f"field.{t}{s}"))
                leaves.append(ref(f"param.{t}{s}"))
                leaves.append(ref(f"literal.{t}{s}"))

            dispatch_to = {}
            for name, impls in ops.items():
                strict = [d for r, n, d in impls if r == t and not n]
                lifted_ = [d for r, n, d in impls if r == t and n]
                # In a nullable position the lifted variant accepts everything
                # the strict one does, so it alone is enough.
                chosen = (lifted_ or strict) if nullable else strict
                if chosen:
                    dispatch_to[name] = chosen

            dispatch = {
                "type": "object",
                "required": ["operator"],
                "properties": {"operator": {"enum": list(dispatch_to)}},
                "allOf": [
                    {
                        "if": {"required": ["operator"], "properties": {"operator": {"const": name}}},
                        "then": {"anyOf": [ref(d) for d in chosen]},
                    }
                    for name, chosen in dispatch_to.items()
                ],
            }
            subtypes = [expr(sub, ctx, nullable) for sub in SUBTYPES.get(t, [])]
            defs[f"{t}{suffix(nullable)}@{ctx}"] = {"anyOf": leaves + [dispatch] + subtypes}

    defs[f"value@{ctx}"] = {"anyOf": [expr(t, ctx, True) for t in TYPES]}

# --- query ----------------------------------------------------------------

DIRECTION = {"enum": ["asc", "desc"], "default": "asc"}

# A source is either a stored entity or a subquery, named explicitly so the two
# can never be confused.
SOURCE = {"entity": NAME, "subquery": NAME, "alias": NAME}
ONE_SOURCE = {"oneOf": [{"required": ["entity"]}, {"required": ["subquery"]}]}

defs["from"] = {**obj([], SOURCE), **ONE_SOURCE}
defs["join"] = {
    **obj(
        ["type", "on"],
        {"type": {"enum": ["inner", "left", "right", "full"]}, **SOURCE, "on": expr("boolean", "row")},
    ),
    **ONE_SOURCE,
}
defs["pagination"] = obj(
    ["skip", "take"],
    {
        "skip": {"type": "integer", "minimum": 0},
        "take": {"type": "integer", "minimum": 1},
    },
)
defs["groupKey"] = obj(["expression"], {"expression": ref("value@row"), "alias": NAME})

ALL_TYPES = [f"type.{t}{suffix(n)}" for t in TYPES for n in [False, True]]

for ctx in ["projection", "group"]:
    # The expression is checked against the declared type (narrower types and
    # non-null values are accepted: an integer expression in a decimal column).
    defs[f"selectItem@{ctx}"] = {
        **obj(
            ["alias", "type", "expression"],
            {"alias": NAME, "type": {"anyOf": [ref(d) for d in ALL_TYPES]}, "expression": True},
        ),
        "allOf": [
            {
                "if": {"required": ["type"], "properties": {"type": ref(f"type.{t}{suffix(n)}")}},
                "then": {"properties": {"expression": expr(t, ctx, n)}},
            }
            for t in TYPES
            for n in [False, True]
        ],
    }
    defs[f"orderItem@{ctx}"] = obj(
        ["expression"], {"expression": ref(f"value@{ctx}"), "direction": DIRECTION}
    )

common = {
    "from": ref("from"),
    "joins": {"type": "array", "items": ref("join")},
    "where": expr("boolean", "row"),
    "distinct": {"type": "boolean", "default": False},
    "pagination": ref("pagination"),
}
plain = {
    "select": array_of(ref("selectItem@projection"), 1),
    "orderBy": {"type": "array", "items": ref("orderItem@projection")},
}
grouped = {
    "groupBy": array_of(ref("groupKey"), 1),
    "having": expr("boolean", "group"),
    "select": array_of(ref("selectItem@group"), 1),
    "orderBy": {"type": "array", "items": ref("orderItem@group")},
}
# Subqueries are flat: only the main query may declare them.
main = {"subqueries": array_of(ref("subquery"), 1)}

defs["plainQuery"] = obj(["from", "select"], {**common, **plain})
defs["groupedQuery"] = obj(["from", "groupBy", "select"], {**common, **grouped})
defs["query"] = {
    "if": {"required": ["groupBy"]},
    "then": ref("groupedQuery"),
    "else": ref("plainQuery"),
}
defs["subquery"] = obj(["name", "query"], {"name": NAME, "query": ref("query")})
defs["mainPlainQuery"] = obj(["from", "select"], {**main, **common, **plain})
defs["mainGroupedQuery"] = obj(["from", "groupBy", "select"], {**main, **common, **grouped})

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": SCHEMA_ID,
    "version": VERSION,
    "title": "PureQL specification",
    "if": {"required": ["groupBy"]},
    "then": ref("mainGroupedQuery"),
    "else": ref("mainPlainQuery"),
    "$defs": dict(sorted(defs.items())),
}

out = Path(__file__).resolve().parent.parent / "PureQL-Specification.json"
out.write_text(json.dumps(schema, indent=2) + "\n")
print(f"{out.name}: {len(defs)} definitions")
