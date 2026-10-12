#!/usr/bin/env python3
"""Generates PureQL-Specification.json. Never edit the schema by hand: change this file and rerun it.

Every expression declares its result type: a field, parameter, literal or
group key as before, and an operator node too:

  {"operator": "add", "type": {"name": "decimal", "nullable": true}, "values": [...]}

The declared type is exact. The schema checks it against the types the
operands declare, so it is the type the operator yields from them, never a
wider one: adding two integers is `integer`, not `decimal`, and a lifted
operator is nullable exactly when one of its operands is. So an expression has
one valid declared type, and an interpreter reads the type of any node without
computing it. Redundant spellings are rejected too: a non-null type has no
`nullable` key, `and` / `or` take at least two conditions, and `over` is
written only when it changes the rows of an aggregate.

Each node is validated in full once, by `expr@<context>`, which dispatches on
`operator` (or on the kind of leaf) and then on the declared type. A position
that expects a type, `<type>@<context>` or `<type>.nullable@<context>`, only
reads the `type` the node declares, which is a shallow check. So validation is
linear in the size of the query, whatever its depth.

Contexts:
  row         where, join.on, groupBy keys, aggregate selector/predicate.
              Fields allowed, aggregates not.
  projection  select / orderBy of a plain query: one row per row.
              Fields allowed, aggregates over all rows (broadcast), without
              `over`.
  group       select / having / orderBy of a grouped query: one row per group.
              No fields; group keys and aggregates over the group, or over
              all rows with `"over": "all"`.
  total       aggregate of a total query: exactly one row.
              No fields, no keys; aggregates over all rows, without `over`.

Subtyping (each arrow means "accepted wherever the right side is expected"):
  T -> T.nullable                      a non-null value is a valid T?
  integer -> decimal                   implicit widening

There is no untyped null: a null literal is written with its type,
{"type": {"name": "uuid", "nullable": true}, "value": null}. So the type of
every expression is determined by its subtree and its context, never inferred
from surrounding expressions. The context only decides whether min / max /
average can be null: a row of a plain or grouped query exists only if a row
of its source does, so there every aggregate sees at least one row, while a
total query returns its row even when there are none.

A document is the main query plus optional `subqueries`: named queries the
main query and later subqueries can read from (`from` / `join` with
`subquery`, or `in` over one of their columns). Every select column has an
alias and the type its expression declares, which the validator has checked,
so each subquery has a verified output schema. Matching a reference to that
schema is name resolution and is left to the interpreter.

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

VERSION = "0.1.0-preview.2.0.0"
SCHEMA_ID = f"https://github.com/kudima03/PureQL-Specification/releases/download/{VERSION}/PureQL-Specification.json"

TYPES = ["integer", "decimal", "string", "boolean", "date", "time", "datetime", "uuid"]
SUBTYPES = {"decimal": ["integer"]}
# Families of operand types for equal, in and comparisons: integer operands are
# compared through decimal. Every type is ordered, so every family is
# comparable as well as equatable.
EQUATABLE = ["decimal", "string", "boolean", "date", "time", "datetime", "uuid"]
COMPARABLE = EQUATABLE
# min / max keep the selector type, so integer is listed separately.
ORDERED = TYPES
# average: selector type -> result type
AVERAGEABLE = {"decimal": "decimal", "date": "date", "time": "time", "datetime": "datetime"}

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
# A decimal as a string: no exponent, no leading zeros, no trailing zeros in the
# fraction and no "-0", so each value has one spelling and every client reads it
# exactly. 0, 12, -0.5 and 19.99 are decimals; 1.50, 01, -0, .5 and 1e3 are not.
DECIMAL = r"(0|-?[1-9][0-9]*(\.[0-9]*[1-9])?|-?0\.[0-9]*[1-9])"
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
    # `type` inside `not` too, or a non-string would fail it with a vague error
    return {"type": "string", "pattern": f"^{body}$", "not": {"type": "string", "pattern": r"\n"}}


# A signed 64-bit integer, as far as a schema can tell. The bounds are written
# as JavaScript prints ±2^63 (CI formats the schema with a JavaScript tool), so
# they are exactly ±2^63 for a validator that reads numbers as doubles, and
# ±(2^63 + 192) for one that reads them exactly. The few values between those
# and the real bounds are rejected by the interpreter.
INT64 = {"type": "integer", "minimum": -9223372036854776000, "maximum": 9223372036854776000}

VALUE = {
    "integer": INT64,
    "decimal": pattern(DECIMAL),
    "string": {"type": "string"},
    "boolean": {"type": "boolean"},
    "date": pattern(DATE),
    "time": pattern(TIME),
    "datetime": pattern(f"{DATE}T{TIME}{OFFSET}"),
    "uuid": pattern(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
}

# `aggregates`: whether aggregates may appear, and the `over` values that may
# be written: none in projection (always all rows), "all" in group (the group
# is the default).
CONTEXTS = {
    "row": {"fields": True, "keys": False, "aggregates": False, "over": []},
    "projection": {"fields": True, "keys": False, "aggregates": True, "over": []},
    "group": {"fields": False, "keys": True, "aggregates": True, "over": ["all"]},
    "total": {"fields": False, "keys": False, "aggregates": True, "over": []},
}

# An entity, field, alias, parameter or subquery name: not empty, no leading
# or trailing space or tab, no line break. Inner spaces and any other
# characters are allowed, so stored names that need quoting stay expressible.
NAME = pattern(r"[^ \t\n\r]([^\n\r]*[^ \t\n\r])?")

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


def members(t):
    """A type and its subtypes: what a position of type `t` accepts."""
    return [t] + SUBTYPES.get(t, [])


def expr(t, ctx, nullable=False):
    return ref(f"{t}{suffix(nullable)}@{ctx}")


def array_of(item, min_items):
    return {"type": "array", "items": item, "minItems": min_items}


def type_check(names=None, nullable=None):
    """A check on a declared type: `names` (one type or a list), and nullable
    (True), non-null (False) or either (None). Names are an `enum` even when
    there is one, so a validator's error says which type was expected."""
    t = {"type": "object", "required": ["name"], "properties": {}}
    if names is not None:
        t["properties"]["name"] = {"enum": names if isinstance(names, list) else [names]}
    if nullable is True:
        t["required"] = ["name", "nullable"]
        t["properties"]["nullable"] = {"const": True}
    elif nullable is False:
        # `type` only allows `"nullable": true`, so this means: no `nullable` key
        t["properties"]["nullable"] = {"const": False}
    return t


def check(name, names=None, nullable=None):
    """A named shallow check on the `type` an expression declares. It reads
    nothing else, so it costs the same at any depth and may be repeated."""
    if name not in defs:
        defs[name] = {"type": "object", "required": ["type"], "properties": {"type": type_check(names, nullable)}}
    return ref(name)


def declares(t, nullable):
    """`declares.<type>[.nullable]`: the expression declares exactly this type."""
    return check(f"declares.{t}{suffix(nullable)}", t, nullable)


def declares_name(t):
    """The expression declares `t`, nullable or not."""
    return {"anyOf": [declares(t, False), declares(t, True)]}


def accepts(t, nullable):
    """`accepts.<type>[.nullable]`: the declared type fits a position of this
    type: the type or a subtype, and non-null unless the position is nullable."""
    return check(f"accepts.{t}{suffix(nullable)}", members(t), None if nullable else False)


NULLABLE = check("declares.nullable", nullable=True)
NON_NULL = check("declares.nonNull", nullable=False)


def merged(checks):
    """Checks as one schema: `required` / `properties` checks merged into one
    where they do not clash, nested `allOf` flattened, the rest in `allOf`."""
    props, required, rest = {}, [], []
    for c in checks:
        if list(c) == ["allOf"]:
            rest += c["allOf"]
        elif set(c) <= {"required", "properties"} and all(
            p not in props or not props[p].keys() & v.keys() for p, v in c.get("properties", {}).items()
        ):
            required += [p for p in c.get("required", []) if p not in required]
            for p, v in c.get("properties", {}).items():
                props[p] = {**props.get(p, {}), **v}
        else:
            rest.append(c)
    out = {"required": required} if required else {}
    if props:
        out["properties"] = props
    if rest:
        out["allOf"] = rest
    return out


def some(props, check):
    """At least one operand passes a shallow check: one of `props`, or an item of
    `values`. The operand is required, so a missing one never passes vacuously."""
    if props == ["values"]:
        return {"required": ["values"], "properties": {"values": {"contains": check}}}
    if len(props) == 1:
        return {"required": props, "properties": {props[0]: check}}
    return {"anyOf": [{"required": [p], "properties": {p: check}} for p in props]}


# --- leaves ---------------------------------------------------------------

# The type an expression declares; which ones a position accepts is checked
# with `declares.*` and `accepts.*`.
# A non-null type is written without `nullable`, so each type has one spelling.
defs["type"] = obj(["name"], {"name": {"enum": TYPES}, "nullable": {"const": True}})
# A literal is nullable exactly when its value is null.
defs["literal"] = {
    **obj(["type", "value"], {"type": ref("type"), "value": True}),
    "allOf": [
        {
            "if": declares(t, nullable),
            "then": {"properties": {"value": {"type": "null"} if nullable else VALUE[t]}},
        }
        for t in TYPES
        for nullable in [False, True]
    ],
}
defs["param"] = obj(["param", "type"], {"param": NAME, "type": ref("type")})
# `source` is the entity, subquery or alias the column comes from.
defs["field"] = obj(
    ["source", "field", "type"], {"source": NAME, "field": NAME, "type": ref("type")}
)
# A group key is referenced by its alias.
defs["key"] = obj(["key", "type"], {"key": NAME, "type": ref("type")})

for t in TYPES:
    defs[f"type.{t}List"] = obj(["name"], {"name": {"const": f"{t}List"}})
    # A list is a value (List<T>), not a column: it is accepted only by `in`.
    defs[f"list.{t}"] = {
        "anyOf": [
            obj(
                ["type", "value"],
                {"type": ref(f"type.{t}List"), "value": {"type": "array", "items": VALUE[t]}},
            ),
            obj(["param", "type"], {"param": NAME, "type": ref(f"type.{t}List")}),
            # Every value of one column of a subquery's result.
            obj(
                ["subquery", "field", "type"],
                {"subquery": NAME, "field": NAME, "type": {**ref("type"), "properties": {"name": {"const": t}}}},
            ),
        ]
        + [ref(f"list.{sub}") for sub in SUBTYPES.get(t, [])]
    }

# --- operators, per context -----------------------------------------------
# `<operator>@<context>` checks the shape of the node, then picks the
# signature by the type the node declares, one `if` / `then` per signature:
# `add.decimal.nullable@row` is `add` declared `decimal?` in row context. A
# signature validates each operand against its type in full, and makes the
# declared type exact with shallow checks on the operands' declared types: a
# nullable result needs a nullable operand, a `decimal` result of `add` needs a
# `decimal` operand, and so on. equal, in and comparisons have one signature
# per family of operands instead, picked by the type the first operand declares.

OPERANDS = {"type": "array", "minItems": 2}

for ctx, rules in CONTEXTS.items():
    # operator name -> (required properties, properties)
    shapes = {}
    # operator name -> [(result type, result nullable, checks)]
    signatures = {}

    def shape(name, required, props):
        # an operator called again (another result type) must keep its shape
        assert shapes.get(name, (required, props)) == (required, props), name
        shapes[name] = (required, props)

    def signature(name, t, nullable, *checks):
        signatures.setdefault(name, []).append((t, nullable, checks))

    def operands(types, nullable):
        """Every operand validated against its type; `values` is an array of operands."""
        return {
            "properties": {
                p: {"items": expr(t, ctx, nullable)} if p == "values" else expr(t, ctx, nullable)
                for p, t in types.items()
            }
        }

    def lifted(name, types, t, *checks, extra=None, optional=None):
        """Non-null operands give T, nullable ones T?: then at least one of them is nullable.
        `extra` / `optional`: required / optional properties of the node besides
        its operands (if.condition, round.digits), never null."""
        shape(name, list(types) + list(extra or {}),
              {p: OPERANDS if p == "values" else True for p in types} | (extra or {}) | (optional or {}))
        signature(name, t, False, operands(types, False), *checks)
        signature(name, t, True, operands(types, True), some(list(types), NULLABLE), *checks)

    def by_family(name, prop, families, build):
        """`<operator>.<family>@<ctx>` per family, chosen by the type `prop` declares."""
        for f in families:
            defs[f"{name}.{f}@{ctx}"] = build(f)
        return {
            "allOf": [
                {
                    "if": {"required": [prop], "properties": {prop: accepts(f, True)}},
                    "then": ref(f"{name}.{f}@{ctx}"),
                }
                for f in families
            ]
        }

    # numbers: integer operands give integer, a decimal operand gives decimal
    for name in ["add", "subtract", "multiply"]:
        lifted(name, {"values": "integer"}, "integer")
        lifted(name, {"values": "decimal"}, "decimal", some(["values"], declares_name("decimal")))
    lifted("divide", {"values": "decimal"}, "decimal")
    for name in ["integerDivide", "modulo"]:
        lifted(name, {"left": "integer", "right": "integer"}, "integer")
    for name in ["floor", "ceiling"]:
        lifted(name, {"operand": "decimal"}, "integer")
    # round gives integer, or decimal with digits
    digits = {"digits": expr("integer", ctx)}
    lifted("round", {"operand": "decimal"}, "integer", {"not": {"required": ["digits"]}}, optional=digits)
    lifted("round", {"operand": "decimal"}, "decimal", {"required": ["digits"]}, optional=digits)

    # strings
    lifted("concat", {"values": "string"}, "string")

    # date / time / datetime math
    lifted("dateAddDays", {"left": "date", "right": "integer"}, "date")
    lifted("dateDiffDays", {"left": "date", "right": "date"}, "integer")
    lifted("timeAddSeconds", {"left": "time", "right": "decimal"}, "time")
    lifted("timeDiffSeconds", {"left": "time", "right": "time"}, "decimal")
    lifted("datetimeAddSeconds", {"left": "datetime", "right": "decimal"}, "datetime")
    lifted("datetimeDiffSeconds", {"left": "datetime", "right": "datetime"}, "decimal")

    # booleans: conditions are always non-null
    for name in ["and", "or"]:
        # one condition would be the condition itself
        shape(name, ["conditions"], {"conditions": array_of(expr("boolean", ctx), 2)})
        signature(name, "boolean", False)
    shape("not", ["condition"], {"condition": expr("boolean", ctx)})
    signature("not", "boolean", False)

    # equal, in and comparisons take nullable operands of one family, picked by
    # the type the first operand declares.
    for name, families in [
        *[(n, EQUATABLE) for n in ["equal", "notEqual"]],
        *[(n, COMPARABLE) for n in ["greaterThan", "lessThan", "greaterThanOrEqual", "lessThanOrEqual"]],
    ]:
        shape(name, ["left", "right"], {
            "left": check(f"accepts.{'equatable' if families is EQUATABLE else 'comparable'}",
                          [m for f in families for m in members(f)]),
            "right": True,
        })
        signature(name, "boolean", False, by_family(
            name, "left", families, lambda f: operands({"left": f, "right": f}, True)
        ))
    shape("in", ["operand", "list"], {"operand": check("accepts.equatable"), "list": True})
    signature("in", "boolean", False, by_family(
        "in", "operand", EQUATABLE,
        lambda f: {"properties": {"operand": expr(f, ctx, True), "list": ref(f"list.{f}")}},
    ))

    # conditional and null handling, for every type
    for t in TYPES:
        wide = [some(["then", "else"], declares_name(t))] if t in SUBTYPES else []
        lifted("if", {"then": t, "else": t}, t, *wide, extra={"condition": expr("boolean", ctx)})
        wide = [some(["values"], declares_name(t))] if t in SUBTYPES else []
        # coalesce is non-null as soon as one operand is non-null.
        signature("coalesce", t, False, operands({"values": t}, True), some(["values"], NON_NULL), *wide)
        signature("coalesce", t, True, operands({"values": t}, True), {
            "properties": {"values": {"items": NULLABLE}}
        }, *wide)
    shape("coalesce", ["values"], {"values": OPERANDS})

    # Aggregates: the body (selector / predicate) is always `row` context,
    # which has no aggregates, so aggregates cannot nest. Nulls produced by the
    # selector are skipped. An aggregate runs over the group in a grouped query
    # and over all rows otherwise; `"over": "all"` is written only for a total
    # over all rows inside a grouped query.
    if rules["aggregates"]:
        aggregate_props = {"predicate": expr("boolean", "row")}
        if rules["over"]:
            aggregate_props["over"] = {"enum": rules["over"]}
        # A row of a plain or grouped query comes from at least one row; a total
        # query returns its one row even over no rows.
        some_row = ctx != "total"

        def selector(t, nullable, exact):
            """The selector, of type `t` or (unless `exact`) one of its subtypes."""
            checks = [{"properties": {"selector": expr(t, "row", nullable)}}]
            if exact and t in SUBTYPES:
                checks.append({"properties": {"selector": declares_name(t)}})
            return checks

        def aggregate(name, selector_t, result_t, exact):
            # Where a row exists, an aggregate sees at least one row: a group
            # has one, and so do all rows when any result row exists. So an
            # unfiltered non-null selector gives T, over the group or over all
            # rows. A predicate or a nullable selector may leave no value, and
            # gives T?. A total query may have no rows at all: always T?.
            if some_row:
                signature(name, result_t, False, *selector(selector_t, False, exact),
                          {"not": {"required": ["predicate"]}})
                signature(name, result_t, True, *selector(selector_t, True, exact), {"anyOf": [
                    {"required": ["predicate"]},
                    {"required": ["selector"], "properties": {"selector": NULLABLE}},
                ]})
            else:
                signature(name, result_t, True, *selector(selector_t, True, exact))

        shape("count", [], aggregate_props)
        signature("count", "integer", False)
        # Sum of no rows is 0, never null.
        shape("sum", ["selector"], {**aggregate_props, "selector": True})
        for t in ["integer", "decimal"]:
            signature("sum", t, False, *selector(t, True, exact=True))
        shape("average", ["selector"], {**aggregate_props, "selector": True})
        # average of integers is decimal: the selector may be either.
        for selector_t, result_t in AVERAGEABLE.items():
            aggregate("average", selector_t, result_t, exact=False)
        for name in ["min", "max"]:
            shape(name, ["selector"], {**aggregate_props, "selector": True})
            for t in ORDERED:
                aggregate(name, t, t, exact=True)
        for name in ["any", "all"]:
            shape(name, ["predicate"], aggregate_props)
            signature(name, "boolean", False)

    for name, (required, props) in shapes.items():
        sigs = signatures[name]
        names = list(dict.fromkeys(t for t, _, _ in sigs))
        nullables = {n for _, n, _ in sigs}
        # Every result type has the same nullabilities, so the declared type can
        # be checked by name and nullability separately, with plain errors.
        assert {(t, n) for t, n, _ in sigs} == {(t, n) for t in names for n in nullables}, name
        result = type_check(names, nullables.pop() if len(nullables) == 1 else None)
        del result["type"], result["required"][0]
        if not result["required"]:
            del result["required"]
        defs[f"{name}@{ctx}"] = obj(["operator", "type", *required], {
            "operator": {"const": name},
            "type": {**ref("type"), **result},
            **props,
        })
        if len(sigs) == 1:
            # one result type (equal, in, comparisons): its checks apply as they are
            defs[f"{name}@{ctx}"].update(merged([{"properties": {}}, *sigs[0][2]]) if sigs[0][2] else {})
            continue
        dispatch = []
        for t, n, checks in sigs:
            sig = f"{name}.{t}{suffix(n)}@{ctx}"
            defs[sig] = merged(checks)
            dispatch.append({"if": declares(t, n), "then": ref(sig)})
        defs[f"{name}@{ctx}"]["allOf"] = dispatch

    # `operator@<ctx>`: an operator node of the context, sent to its definition.
    defs[f"operator@{ctx}"] = {
        "properties": {"operator": {"enum": list(shapes)}},
        "allOf": [
            {"if": {"properties": {"operator": {"const": name}}}, "then": ref(f"{name}@{ctx}")}
            for name in shapes
        ],
    }
    # `leaf@<ctx>`: a literal, parameter, field or group key, told apart by
    # the property only it has.
    leaves = [("value", "literal"), ("param", "param")]
    if rules["fields"]:
        leaves.append(("field", "field"))
    if rules["keys"]:
        leaves.append(("key", "key"))
    defs[f"leaf@{ctx}"] = {
        "anyOf": [{"required": [prop]} for prop, _ in leaves],
        "allOf": [{"if": {"required": [prop]}, "then": ref(d)} for prop, d in leaves],
    }
    # `expr@<ctx>`: any expression of the context: an operator, or a leaf.
    defs[f"expr@{ctx}"] = {
        "type": "object",
        "if": {"required": ["operator"]},
        "then": ref(f"operator@{ctx}"),
        "else": ref(f"leaf@{ctx}"),
    }

    # `<type>[.nullable]@<ctx>`: an expression of the context that declares the
    # type or one of its subtypes, nullable only in a nullable position.
    for t in TYPES:
        for nullable in [False, True]:
            defs[f"{t}{suffix(nullable)}@{ctx}"] = {"allOf": [accepts(t, nullable), ref(f"expr@{ctx}")]}

# --- query ----------------------------------------------------------------

# Defaults are never written: ascending order is the absence of `direction`.
DIRECTION = {"enum": ["desc"]}

# A source is either a stored entity or a subquery, named explicitly so the two
# can never be confused.
SOURCE = {"entity": NAME, "subquery": NAME, "alias": NAME}
ONE_SOURCE = {"oneOf": [{"required": ["entity"]}, {"required": ["subquery"]}]}

defs["from"] = {**obj([], SOURCE), **ONE_SOURCE}
defs["join"] = {
    **obj(
        ["kind", "on"],
        {"kind": {"enum": ["inner", "left", "right", "full"]}, **SOURCE, "on": expr("boolean", "row")},
    ),
    **ONE_SOURCE,
}
# skip / take are a number or a non-null integer parameter, so a page can be
# chosen at execution time. The schema checks a number's range; a parameter's
# value is checked by the interpreter when it is bound.
INTEGER_PARAM = {"allOf": [declares("integer", False), ref("param")]}
defs["pagination"] = obj(
    ["skip", "take"],
    {
        "skip": {"anyOf": [{**INT64, "minimum": 0}, INTEGER_PARAM]},
        "take": {"anyOf": [{**INT64, "minimum": 1}, INTEGER_PARAM]},
    },
)


# A column or a group key has the type its expression declares: a subquery
# column is read from `select[j].expression.type`, and a key reference
# `{ "key": <alias>, "type": … }` repeats that key's `expression.type` exactly.
defs["groupKey"] = obj(["alias", "expression"], {"alias": NAME, "expression": ref("expr@row")})

for ctx in ["projection", "group", "total"]:
    defs[f"selectItem@{ctx}"] = obj(
        ["alias", "expression"], {"alias": NAME, "expression": ref(f"expr@{ctx}")}
    )
for ctx in ["projection", "group"]:
    defs[f"orderItem@{ctx}"] = obj(
        ["expression"], {"expression": ref(f"expr@{ctx}"), "direction": DIRECTION}
    )

sources = {
    "from": ref("from"),
    "joins": array_of(ref("join"), 1),
    "where": expr("boolean", "row"),
}
# Shaping the rows of a plain or grouped query; a total query has one row.
# `distinctBy` lists `select` aliases: of the rows equal on those columns, the
# first in `orderBy` order is kept. Listing every alias removes duplicate rows.
rows = {
    "distinctBy": {"type": "array", "items": NAME, "minItems": 1, "uniqueItems": True},
    "pagination": ref("pagination"),
}
plain = {
    **sources, **rows,
    "select": array_of(ref("selectItem@projection"), 1),
    "orderBy": array_of(ref("orderItem@projection"), 1),
}
grouped = {
    **sources, **rows,
    "groupBy": array_of(ref("groupKey"), 1),
    "having": expr("boolean", "group"),
    "select": array_of(ref("selectItem@group"), 1),
    "orderBy": array_of(ref("orderItem@group"), 1),
}
# A total query folds every row into exactly one, even over no rows.
total = {**sources, "aggregate": array_of(ref("selectItem@total"), 1)}
# Subqueries are flat: only the main query may declare them.
main = {"subqueries": array_of(ref("subquery"), 1)}

# A page is chosen by an order, or two interpreters may return different pages.
# A subquery's result is unordered, so its orderBy only serves pagination and
# the choice of the first row by distinctBy.
PAGE_NEEDS_ORDER = {"dependentRequired": {"pagination": ["orderBy"]}}
SUBQUERY_ORDER = {
    "dependentRequired": {"pagination": ["orderBy"]},
    "dependentSchemas": {"orderBy": {"anyOf": [{"required": ["pagination"]}, {"required": ["distinctBy"]}]}},
}

defs["plainQuery"] = {**obj(["from", "select"], plain), **SUBQUERY_ORDER}
defs["groupedQuery"] = {**obj(["from", "groupBy", "select"], grouped), **SUBQUERY_ORDER}
defs["totalQuery"] = obj(["from", "aggregate"], total)
defs["mainPlainQuery"] = {**obj(["from", "select"], {**main, **plain}), **PAGE_NEEDS_ORDER}
defs["mainGroupedQuery"] = {**obj(["from", "groupBy", "select"], {**main, **grouped}), **PAGE_NEEDS_ORDER}
defs["mainTotalQuery"] = obj(["from", "aggregate"], {**main, **total})


def kind_of_query(prefix):
    """A grouped query has `groupBy`, a total query `aggregate`, a plain query neither."""
    def name(kind):
        return f"{prefix}{kind}Query" if prefix else f"{kind.lower()}Query"
    return {
        "if": {"required": ["groupBy"]},
        "then": ref(name("Grouped")),
        "else": {"if": {"required": ["aggregate"]}, "then": ref(name("Total")), "else": ref(name("Plain"))},
    }


defs["query"] = kind_of_query("")
defs["subquery"] = obj(["name", "query"], {"name": NAME, "query": ref("query")})

schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": SCHEMA_ID,
    "version": VERSION,
    "title": "PureQL specification",
    **kind_of_query("main"),
    "$defs": dict(sorted(defs.items())),
}

out = Path(__file__).resolve().parent.parent / "PureQL-Specification.json"
# The form CI checks with jsonlint --check: 2-space indent, a final newline,
# no duplicate keys, non-ASCII characters written as is.
out.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{out.name}: {len(defs)} definitions")
