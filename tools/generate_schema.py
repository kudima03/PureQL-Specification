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
written only when it changes the rows of an aggregate: a window that names no
partition, order or frame is the absence of `over`.

Each node is validated in full once, by `expr@<context>`, which dispatches on
`operator` (or on the kind of leaf) and then on the declared type. A position
that expects a type, `<type>@<context>` or `<type>.nullable@<context>`, only
reads the `type` the node declares, which is a shallow check. So validation is
linear in the size of the query, whatever its depth.

Contexts:
  row         where, join.on, groupBy keys, aggregate selector/predicate/orderBy.
              Fields allowed, aggregates not.
  projection  select / orderBy of a plain query: one row per row.
              Fields allowed, aggregates over all rows (broadcast) or, with
              `over`, over a window: the rows of the current row's partition,
              or a frame of them around the current row. The ranking
              functions and previous / next exist only here.
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
average / first / last and the statistics typed like them can be null: a row of a plain or grouped query exists only if a row
of its source does, so there every aggregate sees at least one row, while a
total query returns its row even when there are none.

A query is plain, grouped or total, or it combines the rows of other queries
with a set operation (unionAll, union, intersect, except). A document is the
main query plus optional `subqueries`: named queries, named rows of literals, or
recursive queries that read their own rows, which the main query and later
subqueries can read from (`from` / `join` with `subquery`, or `in` over one of
their columns). Every select column has an
alias and the type its expression declares, which the validator has checked,
so each subquery has a verified output schema. Matching a reference to that
schema is name resolution and is left to the interpreter.

Null semantics:
  - arithmetic, abs, sign, powers and logarithms, greatest, least, concat, length, upper/lower, foldCase, normalize, removeDiacritics, trim,
    substring, replace, position,
    splitPart, padStart/padEnd, repeat, reverse, replaceRegex, date/time math, parts and startOf,
    conversions, round/truncate/floor/ceiling are lifted:
    nullable operands give a nullable result (null if any operand is null);
  - if is nullable when either branch is, and yields the branch taken, so
    if(true, 1, null) is 1;
  - equal / notEqual / comparisons / in accept nullable operands and return a
    non-null boolean (null == null is true, so >= and <= of two nulls are true
    too; any ordering against one null is false);
  - contains / startsWith / endsWith accept nullable strings and return a
    non-null boolean, false when either operand is null;
  - concatWith accepts nullable strings and returns a non-null string: null
    operands are skipped;
  - matchesRegex accepts a nullable string and returns a non-null boolean, false
    for null; extractRegex accepts one too and is always nullable: null when
    nothing matches;
  - nullIfEqual accepts nullable operands and is always nullable: null when its
    operands are equal, as `equal` compares them, otherwise its left operand;
  - tryAs<Type> accepts a nullable string and is always nullable: null when
    the string is null or is not a literal of the type;
  - every condition (where, having, on, and/or/not, if.condition, aggregate
    predicate) requires a non-null boolean.

Windows:
  A window is written on the function that reads it, in a plain query only:
  {"partitionBy": [row expressions], "orderBy": [sort keys], "frame": {...}}.
  A frame counts rows before and after the current row, which is always
  inside, so a window is never empty and an aggregate over one is typed as an
  aggregate over all rows is. An aggregate's window has an order exactly when
  it has a frame; the ranking functions (rowNumber, rank, denseRank,
  percentRank, cumulativeDistribution, ntile) and previous / next need an
  order and take no frame. previous / next read another row of the partition:
  where there is none they are null, or the `default`, so they are non-null
  exactly with a default and a non-null operand.
"""
import json
from pathlib import Path

VERSION = "0.1.0-preview.2.0.1"
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
# Parts of a date or a datetime, and of a time or a datetime. `day` is the day of
# the month; `week` and `weekYear` are the ISO 8601 week and its week-numbering year.
DATE_PARTS = ["year", "quarter", "month", "day", "dayOfWeek", "dayOfYear", "week", "weekYear"]
TIME_PARTS = ["hour", "minute", "second", "microsecond"]
# The start of the period that contains a value, for the types it changes: a
# date has no time of day to truncate, a time no calendar period.
START_OF = {
    **{f"startOf{unit}": ["date", "datetime"] for unit in ["Year", "Quarter", "Month", "Week"]},
    "startOfDay": ["datetime"],
    **{f"startOf{unit}": ["time", "datetime"] for unit in ["Hour", "Minute", "Second"]},
}
# The Unicode normalization forms: canonical (C, D) and compatibility (KC, KD),
# composed (C) or decomposed (D).
NORMALIZATION_FORMS = ["NFC", "NFD", "NFKC", "NFKD"]
# The midpoint rules of round besides its default, half away from zero.
ROUNDING_MODES = ["halfEven"]
# average: selector type -> result type
AVERAGEABLE = {"decimal": "decimal", "date": "date", "time": "time", "datetime": "datetime"}

# [0-9] rather than \d: in Python's `re` \d also matches non-ASCII digits,
# in ECMA-262 it does not. No lookahead, for the same portability reason.
# A real calendar date from 0001-01-01 to 9999-12-31: 31-day and 30-day months,
# February up to the 28th, and February 29 only in leap years (divisible by 4,
# centuries only by 400). Year 0000 is not stored by System.DateTime, Python's
# date, PostgreSQL or SQL Server, so no year has a value some interpreter lacks.
YEAR = r"[0-9]{3}[1-9]|[0-9]{2}[1-9]0|[0-9][1-9]00|[1-9]000"
MONTH_DAY = (
    r"(0[13578]|1[02])-(0[1-9]|[12][0-9]|3[01])"
    r"|(0[469]|11)-(0[1-9]|[12][0-9]|30)"
    r"|02-(0[1-9]|1[0-9]|2[0-8])"
)
LEAP_YEAR = r"[0-9]{2}(0[48]|[2468][048]|[13579][26])|(0[48]|[2468][048]|[13579][26])00"
DATE = rf"(({YEAR})-({MONTH_DAY})|({LEAP_YEAR})-02-29)"
# Up to microseconds, without trailing zeros: 18:30:00.5, never 18:30:00.500.
# Microseconds are held exactly by every common store and runtime (PostgreSQL,
# MySQL, SQL Server, Python, .NET, Java); nanoseconds are not.
TIME = r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{0,5}[1-9])?"
# A decimal as a string: no exponent, no leading zeros, no trailing zeros in the
# fraction and no "-0", so each value has one spelling and every client reads it
# exactly. 0, 12, -0.5 and 19.99 are decimals; 1.50, 01, -0, .5 and 1e3 are not.
DECIMAL = r"(0|-?[1-9][0-9]*(\.[0-9]*[1-9])?|-?0\.[0-9]*[1-9])"


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

# A decimal is m × 10^-s with |m| < 10^28 and 0 <= s <= 28: at most 28
# significant digits and 28 decimal places, which every interpreter holds
# exactly (System.Decimal does). DECIMAL fixes the spelling; these bound it.
DECIMAL_DIGITS = [
    # a whole number: at most 28 digits
    {"if": {"pattern": r"^-?[1-9][0-9]*$"}, "then": {"pattern": r"^-?[0-9]{1,28}$"}},
    # 1 or more with a fraction: at most 28 digits and the point
    {"if": {"pattern": r"^-?[1-9][0-9]*\."}, "then": {"pattern": r"^-?[0-9.]{1,29}$"}},
    # below 1: at most 28 decimal places
    {"if": {"pattern": r"^-?0\."}, "then": {"pattern": r"^-?0\.[0-9]{1,28}$"}},
]

# The literal form of each type: one spelling for each value.
VALUE = {
    "integer": INT64,
    "decimal": {**pattern(DECIMAL), "allOf": DECIMAL_DIGITS},
    "string": {"type": "string"},
    "boolean": {"type": "boolean"},
    "date": pattern(DATE),
    "time": pattern(TIME),
    # always in UTC: an instant has one spelling
    "datetime": pattern(f"{DATE}T{TIME}Z"),
    "uuid": pattern(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
}

# `aggregates`: whether aggregates may appear, and `over`: what may be written
# there. A window in projection (all rows is the default), "all" in group (the
# group is the default), nothing in a total query, which has one row.
CONTEXTS = {
    "row": {"fields": True, "keys": False, "aggregates": False, "over": None},
    "projection": {"fields": True, "keys": False, "aggregates": True, "over": "window"},
    "group": {"fields": False, "keys": True, "aggregates": True, "over": "all"},
    "total": {"fields": False, "keys": False, "aggregates": True, "over": None},
}

# The regular expressions of matchesRegex, extractRegex and replaceRegex, as far as
# one pattern can tell a pattern of the dialect from another: every token is one
# the dialect has, and a quantifier follows something it can repeat. An atom is
# a literal code point, an escape, a class, `.` or the `)` that closes a group.
# An escape is a class of characters (\d \w \s and their negations), a word
# boundary, a control character, or a special character standing for
# itself: so no backreference, property class or code point escape. `(` opens a
# group, capturing or `(?:`: nothing else may follow `(?`, so no lookaround,
# named group or flag. A quantifier takes one optional `?`, so none is
# possessive. Whether parentheses balance, a range or a `{n,m}` is in order and a
# group exists is checked by the interpreter, before it reads any row.
REGEX_ATOM = (
    r"[^\\()\[\]{}*+?|^$.]"
    r"|\\([dDwWsSbBnrt]|[\\()\[\]{}*+?|^$./])"
    r"|\[\^?([^\]\[\\^]|\\([dDwWsSnrt]|[\\()\[\]{}*+?|^$./-]))+\]"
    r"|\.|\)"
)
REGEX_QUANTIFIER = r"([*+?]|\{[0-9]+(,[0-9]*)?\})\??"
REGEX = rf"(({REGEX_ATOM})({REGEX_QUANTIFIER})?|\((\?:)?|[|^$])*"

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
            "then": {"properties": {"value": {"type": "null"} if nullable else ref(f"value.{t}")}},
        }
        for t in TYPES
        for nullable in [False, True]
    ],
}
for t in TYPES:
    defs[f"value.{t}"] = VALUE[t]
defs["param"] = obj(["param", "type"], {"param": NAME, "type": ref("type")})
# `source` is the entity, subquery or alias the column comes from.
defs["field"] = obj(
    ["source", "field", "type"], {"source": NAME, "field": NAME, "type": ref("type")}
)
# A group key is referenced by its alias.
defs["key"] = obj(["key", "type"], {"key": NAME, "type": ref("type")})

# The pattern of a regular expression is a string literal or a string parameter,
# never a computed string: it is known before any row is read, so an invalid one
# fails the query up front. A literal is held to the dialect here.
defs["regexPattern"] = {
    "type": "object",
    "allOf": [declares("string", False)],
    "if": {"required": ["value"]},
    "then": {"allOf": [ref("literal"), {"properties": {"value": pattern(REGEX)}}]},
    "else": ref("param"),
}
# A capture group is named by its number, from 1: the whole match is the
# absence of `group`.
defs["regexGroup"] = {
    "type": "object",
    "allOf": [declares("integer", False)],
    "if": {"required": ["value"]},
    "then": {"allOf": [ref("literal"), {"properties": {"value": {"minimum": 1}}}]},
    "else": ref("param"),
}

# The separator of concatAll is a string literal or a string parameter: an
# aggregate has one separator, not one for each row.
defs["separator"] = {
    "type": "object",
    "allOf": [declares("string", False)],
    "if": {"required": ["value"]},
    "then": ref("literal"),
    "else": ref("param"),
}
# The fraction of a percentile is a decimal literal from 0 to 1 or a decimal
# parameter, never computed per row: an aggregate has one fraction.
defs["fraction"] = {
    "type": "object",
    "allOf": [declares("decimal", False)],
    "if": {"required": ["value"]},
    "then": {"allOf": [ref("literal"), {"properties": {"value": pattern(r"(0|1|0\.[0-9]*[1-9])")}}]},
    "else": ref("param"),
}

# A count of rows is a number or a non-null integer parameter, so it can be
# chosen at execution time. The schema checks a number's range; a parameter's
# value is checked by the interpreter when it is bound.
INTEGER_PARAM = {"allOf": [declares("integer", False), ref("param")]}

# A window: the rows a function of a plain query reads for the current row.
# `partitionBy` keeps the rows equal to it on every key (every row without it),
# `orderBy` sorts them, and `frame` keeps those from `preceding` rows before the
# current row to `following` rows after it. The current row is always inside,
# so no window is empty. A side is a number of rows from 1, or "all" for every
# row on that side; no rows on a side is the absence of the property.
defs["frameRows"] = {"anyOf": [{"const": "all"}, {**INT64, "minimum": 1}, INTEGER_PARAM]}
defs["frame"] = {
    **obj([], {"preceding": ref("frameRows"), "following": ref("frameRows")}),
    # a frame of the current row alone is no window
    "minProperties": 1,
    # every row on both sides is the whole partition: no order, no frame
    "not": {
        "type": "object",
        "required": ["preceding", "following"],
        "properties": {"preceding": {"const": "all"}, "following": {"const": "all"}},
    },
}
WINDOW = {
    "partitionBy": array_of(ref("expr@row"), 1),
    "orderBy": array_of(ref("orderItem@row"), 1),
}
# The window of an aggregate. Without an order it is the whole partition; with
# one the frame is always stated, so there is no default frame to remember. A
# window that names nothing is all rows: the absence of `over`.
defs["window"] = {
    **obj([], {**WINDOW, "frame": ref("frame")}),
    "minProperties": 1,
    "dependentRequired": {"orderBy": ["frame"], "frame": ["orderBy"]},
}
# The window of a function that reads the position of a row (the ranking
# functions, previous / next): an order is required, and there is no frame.
defs["orderedWindow"] = obj(["orderBy"], WINDOW)
# previous / next read the row `offset` rows away: an integer literal or an
# integer parameter, never computed. One row away is the absence of `offset`.
defs["offset"] = {
    "type": "object",
    "allOf": [declares("integer", False)],
    "if": {"required": ["value"]},
    "then": {"allOf": [ref("literal"), {"properties": {"value": {"minimum": 2}}}]},
    "else": ref("param"),
}
# The number of buckets of ntile, from 1.
defs["buckets"] = {
    "type": "object",
    "allOf": [declares("integer", False)],
    "if": {"required": ["value"]},
    "then": {"allOf": [ref("literal"), {"properties": {"value": {"minimum": 1}}}]},
    "else": ref("param"),
}

for t in TYPES:
    defs[f"type.{t}List"] = obj(["name"], {"name": {"const": f"{t}List"}})
    # A list is a value (List<T>), not a column: it is accepted only by `in`.
    defs[f"list.{t}"] = {
        "anyOf": [
            obj(
                ["type", "value"],
                # a set: a repeated value adds nothing. At least one value, as every array
                # of the language: `in` over no values is the literal false, and a set that
                # may be empty is a list parameter
                {"type": ref(f"type.{t}List"),
                 "value": {"type": "array", "items": ref(f"value.{t}"), "minItems": 1, "uniqueItems": True}},
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
    # section name -> operator names. Operators are declared section by section,
    # and `operator@<ctx>` sends a node to its section first: see the dispatch below.
    sections = {}

    def shape(name, required, props):
        # an operator called again (another result type) must keep its shape
        assert shapes.get(name, (required, props)) == (required, props), name
        if name not in shapes:
            sections.setdefault(section, []).append(name)
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

    def lifted(name, types, t, *checks, maybe=None, extra=None, optional=None):
        """Non-null operands give T, nullable ones T?: then at least one of them is nullable.
        `types` are the operands, those named by their role included (power.exponent,
        substring.start); `maybe` are operands that may be absent (round.digits,
        substring.length), lifted over when they are written. `extra` / `optional`:
        required / optional properties of the node that are not operands and are
        never null (if.condition, trim.removables, round.mode, a regex pattern)."""
        typed = types | (maybe or {})
        shape(name, list(types) + list(extra or {}),
              {p: OPERANDS if p == "values" else True for p in typed} | (extra or {}) | (optional or {}))
        signature(name, t, False, operands(typed, False), *checks)
        # `some` requires the operand it reads, so an absent one is never the nullable one
        signature(name, t, True, operands(typed, True), some(list(typed), NULLABLE), *checks)

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

    section = "arithmetic"
    # numbers: integer operands give integer, a decimal operand gives decimal
    for name in ["add", "subtract", "multiply"]:
        lifted(name, {"values": "integer"}, "integer")
        lifted(name, {"values": "decimal"}, "decimal", some(["values"], declares_name("decimal")))
    lifted("divide", {"values": "decimal"}, "decimal")
    # integerDivide is the exact quotient truncated toward zero: an integer, whatever
    # its operands. modulo is what is left, left - right * integerDivide(left, right),
    # and is typed as add: integer operands give integer, a decimal operand decimal.
    lifted("integerDivide", {"left": "decimal", "right": "decimal"}, "integer")
    lifted("modulo", {"left": "integer", "right": "integer"}, "integer")
    lifted("modulo", {"left": "decimal", "right": "decimal"}, "decimal", some(["left", "right"], declares_name("decimal")))
    # Rounding to a whole number takes a decimal: an integer is one already, and an
    # operator that cannot change its operand is rejected, as asString of a string is.
    # With digits an integer is accepted: round(1250, -2) is 1300.
    whole = {"properties": {"operand": declares_name("decimal")}}
    for name in ["floor", "ceiling"]:
        lifted(name, {"operand": "decimal"}, "integer", whole)
    # round gives integer, or decimal with digits
    digits = {"digits": "integer"}
    # `mode` names the rule for a value exactly halfway. Its absence is half away from
    # zero, which is never written; the enum holds the other rules. It is a name,
    # like the form of normalize, and changes neither the type nor the nullability.
    rounding = {"mode": {"enum": ROUNDING_MODES}}
    lifted("round", {"operand": "decimal"}, "integer", {"not": {"required": ["digits"]}}, whole, maybe=digits, optional=rounding)
    lifted("round", {"operand": "decimal"}, "decimal", {"required": ["digits"]}, maybe=digits, optional=rounding)
    # truncate drops digits, toward zero, and is typed as round is
    lifted("truncate", {"operand": "decimal"}, "integer", {"not": {"required": ["digits"]}}, whole, maybe=digits)
    lifted("truncate", {"operand": "decimal"}, "decimal", {"required": ["digits"]}, maybe=digits)
    # abs keeps the type of its operand; sign is -1, 0 or 1, an integer whatever the operand
    lifted("abs", {"operand": "integer"}, "integer")
    lifted("abs", {"operand": "decimal"}, "decimal", some(["operand"], declares_name("decimal")))
    lifted("sign", {"operand": "decimal"}, "integer")
    # Powers, roots and logarithms are always decimal, like divide: the exact value
    # rounded to the decimal precision. `exponent` and `base` are never null.
    lifted("power", {"operand": "decimal", "exponent": "decimal"}, "decimal")
    for name in ["sqrt", "exp", "ln", "log10"]:
        lifted(name, {"operand": "decimal"}, "decimal")
    lifted("log", {"operand": "decimal", "base": "decimal"}, "decimal")

    section = "string"
    # strings
    lifted("concat", {"values": "string"}, "string")
    # the number of code points
    lifted("length", {"operand": "string"}, "integer")
    # Unicode default case conversion, full mappings, no locale: upper("ß") is "SS"
    for name in ["upper", "lower"]:
        lifted(name, {"operand": "string"}, "string")
    # Unicode full case folding, no locale: strings that differ only in case fold to
    # the same string, so a match that ignores case compares folded strings
    lifted("foldCase", {"operand": "string"}, "string")
    # Unicode normalization: the same text written with other code points (a letter
    # with an accent as one code point or as two) becomes one string. `form` names
    # the normalization form and is always written: there is no default form.
    lifted("normalize", {"operand": "string"}, "string", extra={"form": {"enum": NORMALIZATION_FORMS}})
    # a string without its accents: decomposed, its nonspacing marks dropped, composed again
    lifted("removeDiacritics", {"operand": "string"}, "string")
    # trim removes the strings of `removables` from the ends, the longest match first;
    # at least one is listed, and none is null
    removables = {"removables": array_of(expr("string", ctx), 1)}
    for name in ["trim", "trimStart", "trimEnd"]:
        lifted(name, {"operand": "string"}, "string", extra=removables)
    # code points from `start`, counted from 1, to the end or for `length` of them
    lifted("substring", {"operand": "string", "start": "integer"}, "string", maybe={"length": "integer"})
    # every occurrence of `pattern`, which is literal text, replaced by `replacement`
    lifted("replace", {"operand": "string", "pattern": "string", "replacement": "string"}, "string")
    # the position, counted from 1, of the first occurrence of `pattern` at or after
    # `start`; 0 when there is none
    lifted("position", {"operand": "string", "pattern": "string"}, "integer", maybe={"start": "integer"})
    # part number `index` of the string split at `delimiter`, counted from 1, or from
    # the end when negative
    lifted("splitPart", {"operand": "string", "delimiter": "string", "index": "integer"}, "string")
    # padStart / padEnd add repetitions of `fill` before or after the string until it
    # has `length` code points; a longer string is never cut
    for name in ["padStart", "padEnd"]:
        lifted(name, {"operand": "string", "length": "integer", "fill": "string"}, "string")
    lifted("repeat", {"operand": "string", "count": "integer"}, "string")
    # the code points in reverse order
    lifted("reverse", {"operand": "string"}, "string")
    # concatWith joins its operands with `separator` between them and skips the null
    # ones, so it takes nullable operands and is never null
    shape("concatWith", ["values", "separator"],
          {"values": array_of(expr("string", ctx, True), 2), "separator": expr("string", ctx)})
    signature("concatWith", "string", False)
    # Regular expressions. matchesRegex is a condition as it is, false for a null
    # string; extractRegex is null when nothing matches, so always nullable;
    # replaceRegex is lifted, and its replacement is literal text.
    shape("matchesRegex", ["operand", "pattern"],
          {"operand": expr("string", ctx, True), "pattern": ref("regexPattern")})
    signature("matchesRegex", "boolean", False)
    shape("extractRegex", ["operand", "pattern"],
          {"operand": expr("string", ctx, True), "pattern": ref("regexPattern"), "group": ref("regexGroup")})
    signature("extractRegex", "string", True)
    lifted("replaceRegex", {"operand": "string", "replacement": "string"}, "string", extra={"pattern": ref("regexPattern")})

    section = "dateMath"
    # date / time / datetime math
    lifted("dateAddDays", {"left": "date", "right": "integer"}, "date")
    lifted("dateDiffDays", {"left": "date", "right": "date"}, "integer")
    lifted("timeAddSeconds", {"left": "time", "right": "decimal"}, "time")
    lifted("timeDiffSeconds", {"left": "time", "right": "time"}, "decimal")
    lifted("datetimeAddSeconds", {"left": "datetime", "right": "decimal"}, "datetime")
    lifted("datetimeDiffSeconds", {"left": "datetime", "right": "datetime"}, "decimal")
    # calendar months, the day clamped to the last day of the month; years are 12 months
    lifted("dateAddMonths", {"left": "date", "right": "integer"}, "date")
    lifted("datetimeAddMonths", {"left": "datetime", "right": "integer"}, "datetime")
    # whole months from right to left: the inverse of adding months
    lifted("dateDiffMonths", {"left": "date", "right": "date"}, "integer")
    lifted("datetimeDiffMonths", {"left": "datetime", "right": "datetime"}, "integer")

    section = "datePart"
    # Parts, each an integer: calendar parts of a date or a datetime, clock parts of a
    # time or a datetime (a datetime is read in UTC). The type the operand declares
    # picks the position it is validated against; the result is lifted.
    for names, families in [(DATE_PARTS, ["date", "datetime"]), (TIME_PARTS, ["time", "datetime"])]:
        for name in names:
            shape(name, ["operand"], {"operand": check(f"accepts.{families[0]}OrDatetime", families)})
            operand = by_family(name, "operand", families, lambda f: {"properties": {"operand": expr(f, ctx, True)}})
            signature(name, "integer", False, {"properties": {"operand": NON_NULL}}, operand)
            signature(name, "integer", True, some(["operand"], NULLABLE), operand)
    section = "startOf"
    # Truncation keeps the type of its operand: the declared type picks the signature.
    for name, types in START_OF.items():
        for t in types:
            lifted(name, {"operand": t}, t)

    section = "conversion"
    # Conversions. asString writes a value of any other type as its literal is
    # spelled; the type its operand declares picks the position, as for the parts.
    families = [f for f in EQUATABLE if f != "string"]
    shape("asString", ["operand"], {"operand": check("accepts.nonString", [m for f in families for m in members(f)])})
    operand = by_family("asString", "operand", families, lambda f: {"properties": {"operand": expr(f, ctx, True)}})
    signature("asString", "string", False, {"properties": {"operand": NON_NULL}}, operand)
    signature("asString", "string", True, some(["operand"], NULLABLE), operand)
    # asDate, asTime and asDatetime convert between the temporal types, in UTC (the
    # day or the time of day of a datetime, midnight of a date), and read a string
    # written as asString writes a value of the type. The type the operand declares
    # picks the position.
    for name, source in [("asDate", "datetime"), ("asTime", "datetime"), ("asDatetime", "date")]:
        sources = [source, "string"]
        shape(name, ["operand"], {"operand": check(f"accepts.{source}OrString", sources)})
        operand = by_family(name, "operand", sources, lambda f: {"properties": {"operand": expr(f, ctx, True)}})
        signature(name, name[2:].lower(), False, {"properties": {"operand": NON_NULL}}, operand)
        signature(name, name[2:].lower(), True, some(["operand"], NULLABLE), operand)
    # The other types are read from a string only: an integer is already a decimal,
    # and a decimal becomes an integer by rounding. as<Type> of a string is lifted and
    # fails the query on text that is not a literal of the type.
    for t in ["integer", "boolean", "uuid"]:
        lifted(f"as{t.capitalize()}", {"operand": "string"}, t)
    # asDecimal reads a string too, and also widens an integer, for the places that
    # have no position to widen it: a column, a group key, the operand of previous.
    # The type the operand declares picks the position; a decimal matches neither.
    sources = ["integer", "string"]
    shape("asDecimal", ["operand"], {"operand": check("accepts.integerOrString", sources)})
    operand = by_family("asDecimal", "operand", sources, lambda f: {"properties": {"operand": expr(f, ctx, True)}})
    signature("asDecimal", "decimal", False, {"properties": {"operand": NON_NULL}}, operand)
    signature("asDecimal", "decimal", True, some(["operand"], NULLABLE), operand)
    # asNullable declares a non-null value nullable, and changes nothing else: the
    # name of the type is the operand's, so an integer gives integer?, never decimal?.
    # A nullable operand is rejected: it is the one type the operator would not change.
    shape("asNullable", ["operand"], {"operand": True})
    for t in TYPES:
        signature("asNullable", t, True, {"properties": {"operand": {"allOf": [declares(t, False), expr(t, ctx)]}}})
    # tryAs<Type> reads a nullable string and yields null instead of failing, so it
    # is always nullable. It takes only strings: no other conversion can fail.
    for t in TYPES:
        if t != "string":
            shape(f"tryAs{t.capitalize()}", ["operand"], {"operand": expr("string", ctx, True)})
            signature(f"tryAs{t.capitalize()}", t, True)

    section = "boolean"
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
    # string matching, code point by code point: nullable operands, false when either is null
    for name in ["contains", "startsWith", "endsWith"]:
        shape(name, ["operand", "pattern"],
              {"operand": expr("string", ctx, True), "pattern": expr("string", ctx, True)})
        signature(name, "boolean", False)
    shape("in", ["operand", "list"], {"operand": check("accepts.equatable"), "list": True})
    signature("in", "boolean", False, by_family(
        "in", "operand", EQUATABLE,
        lambda f: {"properties": {"operand": expr(f, ctx, True), "list": ref(f"list.{f}")}},
    ))

    section = "conditional"
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
    # An operand after a non-null one is never reached, so at most one is
    # non-null. (That it comes last is beyond a schema: it cannot address the
    # last item of an array.)
    shape("coalesce", ["values"], {"values": {**OPERANDS, "contains": NON_NULL, "minContains": 0, "maxContains": 1}})
    # nullIfEqual yields its left operand, or null when the right one equals it: always
    # nullable, and of the type the left operand declares, whatever the right one
    # is in its family (an integer stays an integer next to a decimal).
    shape("nullIfEqual", ["left", "right"], {"left": True, "right": True})
    for t in TYPES:
        family = next(f for f in EQUATABLE if t in members(f))
        exact = [{"properties": {"left": declares_name(t)}}] if t in SUBTYPES else []
        signature("nullIfEqual", t, True, operands({"left": t, "right": family}, True), *exact)
    # greatest / least: the largest or the smallest of the values of one row, by the
    # order of their type. Lifted, and typed as add is for numbers: integer operands
    # give integer, a decimal operand gives decimal.
    for name in ["greatest", "least"]:
        for t in TYPES:
            wide = [some(["values"], declares_name(t))] if t in SUBTYPES else []
            lifted(name, {"values": t}, t, *wide)

    section = "aggregate"
    # Aggregates: the body (selector / predicate) is always `row` context,
    # which has no aggregates, so aggregates cannot nest. Nulls produced by the
    # selector are skipped. An aggregate runs over the group in a grouped query
    # and over all rows otherwise; `"over": "all"` is written only for a total
    # over all rows inside a grouped query. In a plain query `over` is a window:
    # the rows of the current row's partition, or a frame of them.
    if rules["aggregates"]:
        aggregate_props = {"predicate": expr("boolean", "row")}
        if rules["over"]:
            aggregate_props["over"] = ref("window") if rules["over"] == "window" else {"enum": [rules["over"]]}
        # A row of a plain or grouped query comes from at least one row; a total
        # query returns its one row even over no rows. A window holds the current
        # row, so an aggregate over one sees a row as well.
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
        # first / last: the selector's value in the first or last of the aggregate's
        # rows, sorted by its own orderBy of row expressions. The value of that row is
        # returned even when it is null, so the result is typed as for min / max: null
        # only with a nullable selector, or when a predicate may leave no row.
        for name in ["first", "last"]:
            shape(name, ["selector", "orderBy"],
                  {**aggregate_props, "selector": True, "orderBy": array_of(ref("orderItem@row"), 1)})
            for t in ORDERED:
                aggregate(name, t, t, exact=True)
        # Statistics. median and the continuous percentile interpolate between two
        # values, so they take the types average takes and are typed as it is.
        fraction = {"fraction": ref("fraction")}
        for name, extra in [("median", {}), ("percentileContinuous", fraction)]:
            shape(name, ["selector", *extra], {**aggregate_props, "selector": True, **extra})
            for selector_t, result_t in AVERAGEABLE.items():
                aggregate(name, selector_t, result_t, exact=False)
        # The discrete percentile and the mode yield one of the values: any type, kept.
        for name, extra in [("percentileDiscrete", fraction), ("mode", {})]:
            shape(name, ["selector", *extra], {**aggregate_props, "selector": True, **extra})
            for t in ORDERED:
                aggregate(name, t, t, exact=True)
        # Variance and standard deviation of numbers are decimal. Over a population
        # they are typed as average; over a sample one value gives null, so they are
        # nullable wherever they are.
        for name in ["variancePopulation", "standardDeviationPopulation"]:
            shape(name, ["selector"], {**aggregate_props, "selector": True})
            aggregate(name, "decimal", "decimal", exact=False)
        for name in ["varianceSample", "standardDeviationSample"]:
            shape(name, ["selector"], {**aggregate_props, "selector": expr("decimal", "row", True)})
            signature(name, "decimal", True)
        # concatAll joins the strings of its rows with a separator, in the order of its
        # own orderBy, as first and last have one. Null values are skipped and no row
        # gives the empty string, so it is never null, as sum is never null.
        # `distinct` drops a value equal to an earlier one; false is never written.
        shape("concatAll", ["selector", "separator", "orderBy"], {
            **aggregate_props,
            "selector": expr("string", "row", True),
            "separator": ref("separator"),
            "orderBy": array_of(ref("orderItem@row"), 1),
            "distinct": {"const": True},
        })
        signature("concatAll", "string", False)
        for name in ["any", "all"]:
            shape(name, ["predicate"], aggregate_props)
            signature(name, "boolean", False)

    section = "window"
    # Functions of a row's position in its window: only where a window exists,
    # and always over an ordered one. They are never null: every row has a
    # position.
    if rules["over"] == "window":
        ordered = {"over": ref("orderedWindow")}
        # rowNumber counts rows; rank and denseRank give tied rows one number
        for name in ["rowNumber", "rank", "denseRank"]:
            shape(name, ["over"], ordered)
            signature(name, "integer", False)
        # the share of the partition before a row, and up to it: exact decimals
        for name in ["percentRank", "cumulativeDistribution"]:
            shape(name, ["over"], ordered)
            signature(name, "decimal", False)
        # the bucket of a row when the partition is cut into `buckets` equal parts
        shape("ntile", ["buckets", "over"], {"buckets": ref("buckets"), **ordered})
        signature("ntile", "integer", False)
        # previous / next: `operand` in the row `offset` rows before or after the
        # current one. Where the partition has no such row the result is `default`,
        # or null without one. So it is non-null exactly with a default and a
        # non-null operand; the default is never null, and the type is the operand's.
        for name in ["previous", "next"]:
            shape(name, ["operand", "over"], {"operand": True, "offset": ref("offset"), "default": True, **ordered})
            for t in TYPES:
                exact = [{"properties": {"operand": declares_name(t)}}] if t in SUBTYPES else []
                signature(name, t, False, {
                    "required": ["default"],
                    "properties": {"operand": expr(t, "row"), "default": expr(t, "row")},
                }, *exact)
                signature(name, t, True, {
                    "properties": {"operand": expr(t, "row", True), "default": expr(t, "row")},
                }, {"anyOf": [
                    {"not": {"required": ["default"]}},
                    {"required": ["operand"], "properties": {"operand": NULLABLE}},
                ]}, *exact)

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
            # one result type (equal, in, comparisons): its checks apply as they are,
            # next to the shape, never in place of its properties
            checks = merged(list(sigs[0][2])) if sigs[0][2] else {}
            if checks:
                defs[f"{name}@{ctx}"]["allOf"] = checks["allOf"] if list(checks) == ["allOf"] else [checks]
            continue
        dispatch = []
        for t, n, checks in sigs:
            sig = f"{name}.{t}{suffix(n)}@{ctx}"
            defs[sig] = merged(checks)
            dispatch.append({"if": declares(t, n), "then": ref(sig)})
        defs[f"{name}@{ctx}"]["allOf"] = dispatch

    # `operator@<ctx>`: an operator node of the context, sent to its section, and
    # `operator.<section>@<ctx>`, which sends it on to its definition. Two short
    # lists instead of one long one: a validator that compiles a schema to code
    # (ajv) keeps every branch of a definition in one stack frame, and that frame
    # is entered once for each level of nesting of a query. With one list of every
    # operator, each operator added to the language made every level cost more
    # stack, so a query could nest less deeply; with sections, a level costs the
    # few sections plus the operators of one of them.
    for section, names in sections.items():
        defs[f"operator.{section}@{ctx}"] = {
            "allOf": [
                {"if": {"properties": {"operator": {"const": name}}}, "then": ref(f"{name}@{ctx}")}
                for name in names
            ],
        }
    defs[f"operator@{ctx}"] = {
        "properties": {"operator": {"enum": list(shapes)}},
        "allOf": [
            {"if": {"properties": {"operator": {"enum": names}}}, "then": ref(f"operator.{section}@{ctx}")}
            for section, names in sections.items()
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
# chosen at execution time. Each is optional and its absence is its default:
# no rows skipped, every row after them returned. So a first page has no
# `skip`, `"skip": 0` is never written, and a pagination names at least one.
PAGE_ROWS = {"anyOf": [{**INT64, "minimum": 1}, INTEGER_PARAM]}
defs["pagination"] = {**obj([], {"skip": PAGE_ROWS, "take": PAGE_ROWS}), "minProperties": 1}


# A column or a group key has the type its expression declares: a subquery
# column is read from `select[j].expression.type`, and a key reference
# `{ "key": <alias>, "type": … }` repeats that key's `expression.type` exactly.
defs["groupKey"] = obj(["alias", "expression"], {"alias": NAME, "expression": ref("expr@row")})

# `selectItem@row` is a column of the `next` query of a recursive subquery, which
# has no aggregates and no windows.
for ctx in ["row", "projection", "group", "total"]:
    defs[f"selectItem@{ctx}"] = obj(
        ["alias", "expression"], {"alias": NAME, "expression": ref(f"expr@{ctx}")}
    )
# `orderItem@row` is a sort key of an aggregate's own `orderBy` (first / last /
# concatAll) and of a window.
for ctx in ["row", "projection", "group"]:
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


# A combined query puts the rows of two or more queries with the same columns
# together: all of them (unionAll), each distinct row once (union), the rows
# that every query returns (intersect), or the rows of the first that no other
# returns (except). It names exactly one operation. Its result is unordered, and
# it has no clause of its own to order, deduplicate or page it: that is done by
# a query that reads it as a subquery. Its inputs are queries of any kind, a
# combined one included, and like a subquery each is unordered.
SET_OPERATIONS = ["unionAll", "union", "intersect", "except"]
combined = {operation: array_of(ref("query"), 2) for operation in SET_OPERATIONS}
ONE_OPERATION = {"oneOf": [{"required": [operation]} for operation in SET_OPERATIONS]}
defs["combinedQuery"] = {**obj([], combined), **ONE_OPERATION}
defs["mainCombinedQuery"] = {**obj([], {**main, **combined}), **ONE_OPERATION}


def kind_of_query(prefix):
    """A combined query has a set operation, a grouped query `groupBy`, a total
    query `aggregate`, a plain query none of them."""
    def name(kind):
        return f"{prefix}{kind}Query" if prefix else f"{kind.lower()}Query"
    return {
        "if": {"anyOf": [{"required": [operation]} for operation in SET_OPERATIONS]},
        "then": ref(name("Combined")),
        "else": {
            "if": {"required": ["groupBy"]},
            "then": ref(name("Grouped")),
            "else": {"if": {"required": ["aggregate"]}, "then": ref(name("Total")), "else": ref(name("Plain"))},
        },
    }


defs["query"] = kind_of_query("")
# A subquery is a named query, a recursive one, or named rows written in the document: a short
# reference list that no entity holds. Each row is a list of { alias, expression }
# like a select, where an expression is a literal or a parameter, so every cell
# carries its type. The rows have the same columns, matched by alias, which the
# interpreter checks, as it does for the inputs of a set operation.
defs["cell"] = {"type": "object", "if": {"required": ["value"]}, "then": ref("literal"), "else": ref("param")}
defs["rowItem"] = obj(["alias", "expression"], {"alias": NAME, "expression": ref("cell")})
# A recursive subquery reads its own rows, to follow a hierarchy of any depth.
# `seed` is a query that gives the first rows. `next` is run on the rows of each
# level in turn, reading them under the subquery's own name, and gives the rows
# of the following level, until a level is empty. Every row of every level is
# returned. `next` is a plain query without aggregates, windows, orderBy,
# distinctBy or pagination: its columns are row expressions. `maxDepth` is the
# last level that may hold rows, a number or a non-null integer parameter: rows
# beyond it fail the query, so a cycle in the data never runs forever. That
# `next` reads the subquery itself, once, and repeats the columns of `seed` is
# checked by the interpreter, like every other reference to a subquery.
defs["nextQuery"] = obj(["from", "select"], {**sources, "select": array_of(ref("selectItem@row"), 1)})
defs["recursion"] = obj(["seed", "next", "maxDepth"], {
    "seed": ref("query"),
    "next": ref("nextQuery"),
    "maxDepth": {"anyOf": [{**INT64, "minimum": 1}, INTEGER_PARAM]},
})
defs["subquery"] = {
    **obj(["name"], {
        "name": NAME,
        "query": ref("query"),
        "rows": array_of(array_of(ref("rowItem"), 1), 1),
        "recursive": ref("recursion"),
    }),
    "oneOf": [{"required": ["query"]}, {"required": ["rows"]}, {"required": ["recursive"]}],
}

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
