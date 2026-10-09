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
              Fields allowed, aggregates over all rows (broadcast); `over`
              may be omitted, it can only be "all".
  group       select / having / orderBy of a grouped query.
              No fields; group keys and aggregates over the group (the
              default when `over` is omitted) or over "all" rows.

Subtyping (each arrow means "accepted wherever the right side is expected"):
  T -> T.nullable                      a non-null value is a valid T?
  integer -> decimal                   implicit widening

There is no untyped null: a null literal is written with its type,
{"type": {"name": "uuid", "nullable": true}, "value": null}. So the type of
every expression is determined by its subtree and its context, never inferred
from surrounding expressions. The context only decides the rows of an
aggregate without `over`, and so whether min / max / average can be null.

A document is the main query plus optional `subqueries`: named queries the
main query and later subqueries can read from (`from` / `join` with
`subquery`, or `in` over one of their columns). Every select column declares
its alias and type, and the validator checks the expression against that
type, so each subquery has a verified output schema. Matching a reference to
that schema is name resolution and is left to the interpreter.

Null semantics:
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

# A type and its subtypes form a family: every operator that is generated per
# operand type (equal, in, comparisons) has one variant per family, and the
# variant for `decimal` also takes `integer` operands.
FAMILIES = {t: [t] + SUBTYPES.get(t, []) for t in TYPES if not any(t in s for s in SUBTYPES.values())}
FAMILY = {member: f for f, members in FAMILIES.items() for member in members}
# Operators whose result type depends on an operand: the property that
# carries that type. Every other operator has a fixed result family.
SPINE = {"if": "then", "coalesce": "values", "min": "selector", "max": "selector", "average": "selector"}

# [0-9] rather than \d: in Python's `re` \d also matches non-ASCII digits,
# in ECMA-262 it does not. No lookahead, for the same portability reason.
# A real calendar date: 31-day and 30-day months, February up to the 28th, and
# February 29 only in leap years (divisible by 4, centuries only by 400).
MONTH_DAY = (
    r"(0[13578]|1[02])-(0[1-9]|[12][0-9]|3[01])"
    r"|(0[469]|11)-(0[1-9]|[12][0-9]|30)"
    r"|02-(0[1-9]|1[0-9]|2[0-8])"
)
LEAP_YEAR = r"[0-9]{2}(0[48]|[2468][048]|[13579][26])|(0[048]|[2468][048]|[13579][26])00"
DATE = rf"([0-9]{{4}}-({MONTH_DAY})|({LEAP_YEAR})-02-29)"
TIME = r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,9})?"
# Mandatory, RFC 3339 range. -00:00 ("offset unknown") is excluded; +00:00 is Z.
OFFSET = (
    r"(Z"
    r"|\+([01][0-9]|2[0-3]):[0-5][0-9]"
    r"|-(0[1-9]|1[0-9]|2[0-3]):[0-5][0-9]"
    r"|-00:(0[1-9]|[1-5][0-9]))"
)



def pattern(body):
    """A whole-string pattern. In Python's `re`, `$` also matches before a final
    newline, so "2024-01-01\\n" would pass there and fail in ECMA-262: the
    explicit newline check keeps both in agreement."""
    return {"type": "string", "pattern": f"^{body}$", "not": {"pattern": r"\n"}}


VALUE = {
    "integer": {"type": "integer"},
    "decimal": {"type": "number"},
    "string": {"type": "string"},
    "boolean": {"type": "boolean"},
    "date": pattern(DATE),
    "time": pattern(TIME),
    "datetime": pattern(f"{DATE}T{TIME}{OFFSET}"),
    "uuid": pattern(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
}

CONTEXTS = {
    "row": {"fields": True, "keys": False, "over": []},
    "projection": {"fields": True, "keys": False, "over": ["all"], "default_over": "all"},
    "group": {"fields": False, "keys": True, "over": ["group", "all"], "default_over": "group"},
}

# An entity, field, alias, parameter or subquery name: not empty, no leading
# or trailing space or tab, no line break. Inner spaces and any other
# characters are allowed, so stored names that need quoting stay expressible.
NAME = pattern(r"[^ \t\n\r]([^\n\r]*[^ \t\n\r])?")

defs = {}
# definition name -> (property, family): the variant applies only when that
# property is an expression of that family (see `probe.<family>`).
guards = {}
# operator name -> families of its result, over every context
results = {}


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


def guarded(def_name):
    """A variant chosen by the family of one operand, probed before it is validated.

    Without the probe, `equal` would validate its `left` once per family, and
    an `if` or `coalesce` inside it once more per family at every level, which
    makes validation exponential in nesting depth.
    """
    if def_name not in guards:
        return ref(def_name)
    prop, family = guards[def_name]
    name = f"guarded.{def_name}"
    defs[name] = {
        "if": {"required": [prop], "properties": {prop: ref(f"probe.{family}")}},
        "then": ref(def_name),
        "else": False,
    }
    return ref(name)


def same_shape(a, b):
    return defs[a]["properties"].keys() == defs[b]["properties"].keys()


for ctx, rules in CONTEXTS.items():
    # operator name -> list of (result type, result nullable, definition name)
    ops = {}

    def op(name, t, nullable, def_name, schema, guard=None):
        defs[def_name] = schema
        ops.setdefault(name, []).append((t, nullable, def_name))
        results.setdefault(name, set()).add(FAMILY[t])
        if guard:
            guards[def_name] = guard

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
            ), guard=("left", t))
        op("in", "boolean", False, f"in.{t}@{ctx}", obj(
            ["operator", "value", "list"],
            {"operator": {"const": "in"}, "value": expr(t, ctx, True), "list": ref(f"list.{t}")},
        ), guard=("value", t))

    for t in COMPARABLE:
        for name in ["greaterThan", "lessThan", "greaterThanOrEqual", "lessThanOrEqual"]:
            op(name, "boolean", False, f"{name}.{t}@{ctx}", obj(
                ["operator", "left", "right"],
                {
                    "operator": {"const": name},
                    "left": expr(t, ctx, True),
                    "right": expr(t, ctx, True),
                },
            ), guard=("left", t))

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
    # selector are skipped. `over` is optional: without it an aggregate runs
    # over the group in a grouped query and over all rows otherwise, so it is
    # written only for a total over all rows inside a grouped query.
    if rules["over"]:
        over = {"enum": rules["over"]}
        predicate = expr("boolean", "row")

        def aggregate(name, selector_t, result_t):
            # May see no rows (predicate, over "all", all-null selector) -> T?.
            op(name, result_t, True, f"{name}.{selector_t}.nullable@{ctx}", obj(
                ["operator", "selector"],
                {
                    "operator": {"const": name},
                    "over": over,
                    "selector": expr(selector_t, "row", True),
                    "predicate": predicate,
                },
            ))
            # A group is never empty, so an unfiltered non-null selector over the
            # group (explicit or by default) gives T.
            if rules["default_over"] == "group":
                op(name, result_t, False, f"{name}.{selector_t}@{ctx}", obj(
                    ["operator", "selector"],
                    {
                        "operator": {"const": name},
                        "over": {"const": "group"},
                        "selector": expr(selector_t, "row"),
                    },
                ))

        op("count", "integer", False, f"count@{ctx}", obj(
            ["operator"],
            {"operator": {"const": "count"}, "over": over, "predicate": predicate},
        ))
        for t in ["integer", "decimal"]:
            # Sum of no rows is 0, never null.
            op("sum", t, False, f"sum.{t}@{ctx}", obj(
                ["operator", "selector"],
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
                ["operator", "predicate"],
                {"operator": {"const": name}, "over": over, "predicate": predicate},
            ))

    # `<type>[.nullable]@<ctx>`: leaves and operators of the type and of its
    # subtypes, operators dispatched on `operator` so the validator only tries
    # the definitions of that operator. Subtypes are merged in rather than
    # referenced as a separate branch: ajv in draft 2020-12 mode evaluates every
    # anyOf branch, so a separate `integer` branch would validate each `if` or
    # `add` in a `decimal` position twice, and nested ones exponentially.
    for t in TYPES:
        members = [t] + SUBTYPES.get(t, [])
        for nullable in [False, True]:
            leaves = []
            for m in members:
                for leaf_nullable in [False, True] if nullable else [False]:
                    s = suffix(leaf_nullable)
                    if rules["keys"]:
                        leaves.append(ref(f"key.{m}{s}"))
                    if rules["fields"]:
                        leaves.append(ref(f"field.{m}{s}"))
                    leaves.append(ref(f"param.{m}{s}"))
                    leaves.append(ref(f"literal.{m}{s}"))

            dispatch_to = {}
            for name, impls in ops.items():
                chosen = []
                for m in members:
                    strict = [d for r, n, d in impls if r == m and not n]
                    lifted_ = [d for r, n, d in impls if r == m and n]
                    # In a nullable position the lifted variant accepts everything
                    # the strict one does, so it alone is enough.
                    picked = (lifted_ or strict) if nullable else strict
                    # A variant of the wider type with the same properties takes
                    # wider operands, so it accepts everything the subtype's
                    # variant does (add, if, coalesce, sum, min, …). The subtype's
                    # variant is kept only when its shape differs (round without
                    # digits) or the operator has no wider variant (count, floor).
                    chosen += [d for d in picked if not any(same_shape(d, c) for c in chosen)]
                if chosen:
                    dispatch_to[name] = chosen

            dispatch = {
                "type": "object",
                "required": ["operator"],
                "properties": {"operator": {"enum": list(dispatch_to)}},
                "allOf": [
                    {
                        "if": {"required": ["operator"], "properties": {"operator": {"const": name}}},
                        "then": {"anyOf": [guarded(d) for d in chosen]},
                    }
                    for name, chosen in dispatch_to.items()
                ],
            }
            defs[f"{t}{suffix(nullable)}@{ctx}"] = {"anyOf": leaves + [dispatch]}

    defs[f"value@{ctx}"] = {
        "anyOf": [
            {"if": ref(f"probe.{f}"), "then": expr(f, ctx, True), "else": False} for f in FAMILIES
        ]
    }

# --- probes ---------------------------------------------------------------
# `probe.<family>` tells cheaply which family an expression belongs to,
# without validating it. It follows only the operand that decides the result
# type (`SPINE`), so it costs one walk down that path, and the expression is
# then validated in full once, against the matching family. Probes decide
# nothing about validity: a wrong expression still fails that validation.

for name, families in results.items():
    assert len(families) == 1 or name in SPINE, f"{name}: result family depends on an operand"

for f, members in FAMILIES.items():
    fixed = [name for name, families in results.items() if name not in SPINE and families == {f}]
    branches = [
        # a field, parameter, literal or group key declares its type
        {
            "required": ["type"],
            "not": {"required": ["operator"]},
            "properties": {
                "type": {"type": "object", "required": ["name"], "properties": {"name": {"enum": members}}}
            },
        }
    ]
    if fixed:
        branches.append({"required": ["operator"], "properties": {"operator": {"enum": fixed}}})
    for prop in dict.fromkeys(SPINE.values()):
        names = [name for name, p in SPINE.items() if p == prop]
        target = (
            {"type": "array", "minItems": 1, "prefixItems": [ref(f"probe.{f}")]}
            if prop == "values"
            else ref(f"probe.{f}")
        )
        branches.append({
            "required": ["operator", prop],
            "properties": {"operator": {"enum": names}, prop: target},
        })
    # `type: object` everywhere: `required` and `properties` pass vacuously on a
    # string or null, and a probe that matches every family validates the node
    # once per family, at every level. Branches are exclusive (a leaf has no
    # `operator`), so a well-formed or malformed node matches one family at most.
    defs[f"probe.{f}"] = {"type": "object", "anyOf": branches}

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
# skip / take are a number or a non-null integer parameter, so a page can be
# chosen at execution time. The schema checks a number's range; a parameter's
# value is checked by the interpreter when it is bound.
defs["pagination"] = obj(
    ["skip", "take"],
    {
        "skip": {"anyOf": [{"type": "integer", "minimum": 0}, ref("param.integer")]},
        "take": {"anyOf": [{"type": "integer", "minimum": 1}, ref("param.integer")]},
    },
)
ALL_TYPES = [f"type.{t}{suffix(n)}" for t in TYPES for n in [False, True]]


def typed_item(ctx, required):
    """{ alias, type, expression }: the expression is checked against the declared type.

    Narrower types and non-null values are accepted (an integer expression in a
    decimal column). Declaring the type is what lets a reference to the item
    (a subquery column, a group key) be checked by lookup, without inference.
    """
    return {
        **obj(
            required,
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


# A group key declares its type; `{ "key": i, "type": … }` must repeat it exactly.
defs["groupKey"] = typed_item("row", ["type", "expression"])

for ctx in ["projection", "group"]:
    defs[f"selectItem@{ctx}"] = typed_item(ctx, ["alias", "type", "expression"])
    defs[f"orderItem@{ctx}"] = obj(
        ["expression"], {"expression": ref(f"value@{ctx}"), "direction": DIRECTION}
    )

common = {
    "from": ref("from"),
    "joins": array_of(ref("join"), 1),
    "where": expr("boolean", "row"),
    "distinct": {"type": "boolean", "default": False},
    "pagination": ref("pagination"),
}
plain = {
    "select": array_of(ref("selectItem@projection"), 1),
    "orderBy": array_of(ref("orderItem@projection"), 1),
}
grouped = {
    "groupBy": array_of(ref("groupKey"), 1),
    "having": expr("boolean", "group"),
    "select": array_of(ref("selectItem@group"), 1),
    "orderBy": array_of(ref("orderItem@group"), 1),
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
# The same text as JSON.stringify(schema, null, 2) + "\n", which CI checks:
# 2-space indent, non-ASCII characters written as is, a final newline.
out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{out.name}: {len(defs)} definitions")
