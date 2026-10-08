# Model D prototype

A typed-by-schema prototype: every rule about where an expression may appear and what type it has is enforced by the JSON Schema validator alone. Only name resolution is left to the interpreter: whether an entity, alias, field, parameter or group key actually exists, and whether its declared type matches.

## Files

| File | Purpose |
|---|---|
| `generate.py` | Source of truth. Generates `schema.json` |
| `schema.json` | Generated schema (draft 2020-12). Do not edit by hand |
| `tests/valid/` | Queries that must validate, numbered from simple to complex: basics, expressions, nulls, joins, aggregates, grouping, subqueries |
| `tests/invalid/` | Queries that must be rejected. Each is a valid base with one thing broken, numbered from structural mistakes to context, grouping and subquery rules |
| `make_invalid_tests.py` | Generates `tests/invalid/` (numbering follows the order of its case list) |
| `jsonfmt.py` | Compact JSON formatting used for the test files |
| `run_tests.py` | Runs both suites and prints the node each invalid query is rejected at |

```bash
python3 generate.py && python3 make_invalid_tests.py && python3 run_tests.py
```

## Types

`integer`, `decimal`, `string`, `boolean`, `date`, `time`, `datetime`, `uuid`. Each one is either non-null or nullable:

```jsonc
{ "name": "decimal" }                    // non-null
{ "name": "decimal", "nullable": true }  // nullable
```

A field reference names the source it reads from (an entity, a subquery, or the alias of either), the field, and its type: `{ "source": "orders", "field": "total", "type": { "name": "decimal" } }`.

Fields, parameters and group keys declare nullability in their `type`. A literal is nullable exactly when its value is `null`, and `null` is always typed:

```json
{ "type": { "name": "uuid", "nullable": true }, "value": null }
```

There is no `null` type. `{ "name": "null" }` is rejected everywhere. A literal typed `decimal?` with a non-null value is rejected too.

**Invariant:** the type of every expression is determined by its subtree alone, never by its context. With implicit conversions this is the narrowest type: an `integer` expression is also a valid `decimal`.

Each expression definition is named `<type>@<context>` or `<type>.nullable@<context>`.

### Implicit conversions

| From | To |
|---|---|
| `T` | `T` nullable |
| `integer` | `decimal` (also `integer?` to `decimal?`) |

There are no other conversions. `date` and `datetime`, for example, are not interchangeable.

### Temporal types

| Type | Meaning | Literal |
|---|---|---|
| `date` | local calendar date | `2024-01-31` |
| `time` | local time of day, no offset | `18:30:00`, `18:30:00.125` |
| `datetime` | instant in time, as `DateTimeOffset` in C# | `2024-01-31T18:30:00Z`, `2024-01-31T18:30:00.5+03:00` |

- **The `datetime` offset is mandatory:** `Z` or `±hh:mm` up to `±23:59`, with `T` and `Z` in upper case only. `-00:00` is rejected: in RFC 3339 it means "offset unknown", which is a naive datetime under another name. `+00:00` is the same as `Z`.
- **Comparisons work on the instant.** `equal`, ordering, `*DiffSeconds`, `min` / `max`, `orderBy`, `groupBy` and `distinct` compare the instant itself, so `03:00+03:00` equals `00:00Z`. The offset only affects how a value is written, and an interpreter may normalise results to `Z`.
- **Missing offsets are errors.** A `datetime` parameter bound at run time without an offset is an error. If the storage holds naive timestamps, how they map to instants is part of the interpreter configuration and is never guessed.
- **Patterns use `[0-9]`, never `\d`.** In Python's `re`, `\d` also matches non-ASCII digits, while in ECMA-262 it does not. The patterns also avoid lookahead, so they behave the same in every validator.

### Null semantics (C# / LINQ to Objects)

- **Lifted:** arithmetic, `concat`, date/time math, `if`, `round`/`floor`/`ceiling`. Any nullable operand makes the result nullable, and it is `null` if any operand is `null`.
- **Non-null `boolean` from nullable operands:** `equal`, `notEqual`, comparisons and `in`. `null == null` is `true`, and any ordering against `null` is `false`.
- **Non-null `boolean` required in conditions:** `where`, `having`, `join.on`, `and`/`or`/`not`, `if.condition`, aggregate `predicate`. A nullable boolean is turned into a condition with `equal(x, true)` or `coalesce(x, false)`.
- **`coalesce`:** non-null as soon as one operand is non-null.

### Numbers

| Operation | Result |
|---|---|
| `add` / `subtract` / `multiply` | `integer` if all operands are `integer`, otherwise `decimal` |
| `divide` | always `decimal` (no truncating division by accident) |
| `integerDivide`, `modulo` | `integer`, operands `integer` |
| `floor`, `ceiling`, `round` | `integer`. `round` with `digits` gives `decimal` |
| `count` | `integer` |
| `sum` | type of the selector |
| `average` | `decimal` for numbers. Keeps the type for `date` / `time` / `datetime` |
| `min` / `max` | type of the selector |
| `dateAddDays` | the day count must be `integer`. `dateDiffDays` gives `integer` |
| `timeAddSeconds`, `datetimeAddSeconds` | seconds are `decimal`. The `*DiffSeconds` operators give `decimal` |

## Contexts

There is one set of operators, with no `each*` family. Where an operator may appear and what its operands may be is decided by the **context**. The context is fixed by position and passed down through `$ref`.

| Context | Used in | Fields | Group keys | Aggregates |
|---|---|---|---|---|
| `row` | `where`, `join.on`, `groupBy` keys, aggregate `selector` / `predicate` | yes | no | no |
| `projection` | `select` / `orderBy` without `groupBy` | yes | no | `over: "all"` |
| `group` | `select` / `having` / `orderBy` with `groupBy` | no | yes | `over: "group"` or `"all"` |

Aggregates take their input explicitly, as in LINQ (`g.Sum(x => …)`, `g.Count(x => …)`):

```json
{ "operator": "sum", "over": "group", "selector": <decimal@row>, "predicate": <boolean@row> }
```

- The aggregate body is always in `row` context, and `row` has no aggregates, so aggregates cannot nest.
- `null` values from the selector are skipped.
- `count` and `sum` are never null: the sum of no rows is `0`.
- `average`, `min` and `max` are non-null only with `over: "group"`, no `predicate` and a non-null selector, because a group always has at least one row. In every other case they are nullable.

## Select columns

Every `select` column declares its alias and type:

```json
{ "alias": "total", "type": { "name": "decimal" }, "expression": <…> }
```

The validator checks the expression against the declared type, with the usual implicit conversions: an `integer` expression fits a `decimal` column, and a non-null expression fits a nullable one. So every query, including each subquery, has a declared and verified result schema. `orderBy` items are `{ expression, direction }`, and `groupBy` items are `{ expression, alias? }`.

## Subqueries

The main query may declare `subqueries`: named queries it can read from.

```json
{
  "subqueries": [
    { "name": "user_totals", "query": { "from": …, "groupBy": …, "select": … } },
    { "name": "big_spenders", "query": { "from": { "subquery": "user_totals" }, … } }
  ],
  "from": { "entity": "users" },
  "joins": [ { "type": "inner", "subquery": "big_spenders", "on": … } ],
  "select": …
}
```

- **Reading from a subquery.** A subquery is read with `from` / `join` `{ "subquery": <name> }`. A stored entity is `{ "entity": <name> }`; exactly one of the two is given, so a subquery name never collides with a table name. Its columns are referenced as fields: `{ "source": <name or alias>, "field": <column alias>, "type": … }`.
- **Semi-join.** `in` accepts one column of a subquery as its list: `{ "subquery": <name>, "field": <column alias>, "type": … }`. The column type may be nullable.
- **Flat list.** Subqueries cannot declare subqueries of their own, and there is no recursion.

The validator checks every query on its own, including each subquery's output types. Matching references against subqueries is name resolution, done by the interpreter before execution. This is a dictionary lookup over the subquery headers (name, column aliases and types), with no type inference:

| Rule | Checked by |
|---|---|
| Types inside each query, and each column's expression against its declared type | validator |
| Only the main query declares subqueries; each has a `name`; a source is an entity or a subquery | validator |
| Subquery names are unique | interpreter |
| A subquery only reads from earlier subqueries; the main query may read from any | interpreter |
| A referenced subquery and column exist, and the reference declares the column's exact type (nullable after an outer join) | interpreter |
| Column aliases are unique within a `select` | interpreter |

## Differences from the current spec

- No `each*` operators. `equal`, `add`, `dateDiffDays`, etc. work in every context.
- `number` is split into `integer` and `decimal`, and every type has a nullable form.
- Aggregates: `count`, `sum`, `average`, `min`, `max`, `any`, `all`. Each has `over` (`"group"` or `"all"` rows) and an optional `predicate`.
- Lists (`stringList`, …) are values, not columns. They are accepted only by `in`. An `integerList` is accepted where a `decimalList` is expected.
- `groupBy` items are `{ expression, alias }`, and any row expression can be a key. Keys are referenced as `{ "key": <index>, "type": … }` and are **not** emitted automatically: select them explicitly.
- `null` is always typed. The `null` type is gone, and the `datetime` offset is mandatory.
- `select` items are `{ alias, type, expression }`, with alias and type required. `orderBy` items are `{ expression, direction }`, and any type can be an `orderBy` key. `greaterThan` / `lessThan` / `min` / `max` exclude `boolean` and `uuid`.
- New operators: `if`, `coalesce`, `concat`, `in`, `notEqual`, `integerDivide`, `modulo`, `floor`, `ceiling`, `round`. They are available in every context.
- Field references are `{ source, field, type }` (was `entity`).
- Joins can have an `alias` (self-join). `from` and `join` name either an `entity` or a `subquery`.
- Subqueries: named queries declared by the main query.
- Every object has `additionalProperties: false`. `date`, `time`, `datetime` and `uuid` literals are checked by `pattern`.
- The root dispatches on whether `groupBy` is present (`if` / `then` / `else`).
- Operator nodes dispatch on `operator` before trying operand types, so validation does not branch exponentially.

## Not covered yet

String functions beyond `concat`, conversions between types (`datetime` to `date`, number to string), date parts, correlated subqueries, set operations, the rules for `distinct` + `orderBy`, and column naming.
