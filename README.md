# PureQL Specification

PureQL is a JSON-based declarative query language for relational data. Queries are plain JSON objects validated against a JSON Schema, making them easy to generate programmatically, serialize, transmit, and validate without a parser.

## Quick Reference

| Property   | Required | Description |
|------------|----------|-------------|
| `from`     | yes      | Entity (table) to query from, with optional alias |
| `select`   | yes      | Array of expressions to return |
| `where`    | no       | Boolean filter applied before grouping |
| `joins`    | no       | Array of join clauses |
| `groupBy`  | no       | Fields to group rows by |
| `having`   | no       | Boolean filter applied after grouping |
| `orderBy`  | no       | Fields to order results by |
| `pagination` | no     | `skip` and `take` for paging |
| `distinct` | no       | When `true`, deduplicate result rows (default: `false`) |

---

## Type System

### Scalar types

| Type name   | JSON representation |
|-------------|---------------------|
| `string`    | `"name": "string"` |
| `number`    | `"name": "number"` |
| `boolean`   | `"name": "boolean"` |
| `null`      | `"name": "null"` |
| `date`      | `"name": "date"` — ISO 8601 date string |
| `time`      | `"name": "time"` — ISO 8601 time string |
| `datetime`  | `"name": "datetime"` — ISO 8601 date-time string |
| `uuid`      | `"name": "uuid"` — UUID string |

### Array types

Each scalar type has a corresponding array variant: `stringArray`, `numberArray`, `booleanArray`, `nullArray`, `dateArray`, `timeArray`, `datetimeArray`, `uuidArray`.

---

## Core Concepts

### Field references

A field reference selects a column from an entity. The `entity` value should match the entity name (or `from` alias). Fields are typed using the scalar type name.

```json
{ "entity": "users", "field": "email", "type": { "name": "string" } }
```

Fields carry their type as an **array type** in the schema — they represent a column of values. Use them in `select`, `groupBy`, `orderBy`, as operands of per-row predicates (`eachEqual`, `eachGreaterThan`, etc.), and as arguments to aggregate functions.

### Scalars

A scalar is a literal constant value embedded in the query.

```json
{ "type": { "name": "number" }, "value": 42 }
{ "type": { "name": "string" }, "value": "active" }
{ "type": { "name": "date" },   "value": "2024-01-01" }
```

Array scalars hold an array of literal values:

```json
{ "type": { "name": "stringArray" }, "value": ["active", "pending"] }
```

### Parameters

Parameters are named placeholders resolved at execution time, analogous to prepared statement bindings.

```json
{ "param_name": "user_role",   "type": { "name": "stringArray" } }
{ "param_name": "min_amount",  "type": { "name": "number" } }
```

---

## Query Clauses

### `from`

```json
{ "entity": "orders" }
{ "entity": "orders", "alias": "o" }
```

### `select`

Each item in `select` is a value-returning expression (field, scalar, aggregate, arithmetic, boolean expression) with an optional `alias`.

```json
"select": [
  { "entity": "users", "field": "name",  "type": { "name": "string" } },
  { "entity": "users", "field": "email", "type": { "name": "string" }, "alias": "contact_email" },
  { "operator": "count", "arg": { "entity": "orders", "field": "id", "type": { "name": "uuid" } }, "alias": "order_count" }
]
```

### `where` / `having`

They accept different shapes because they evaluate in different scopes:

- **`where`** is evaluated per row. It accepts either a **boolean-returning** expression (single boolean) or a **boolean-array-returning** expression (per-row boolean column). Use the `each*` family for per-row predicates against fields.
- **`having`** is evaluated per group, after `groupBy`. It accepts only a **boolean-returning** expression. Operands must reduce to a single value per group — typically aggregates compared with `greaterThan` / `equal` / etc. Per-row `each*` operators do **not** fit in `having`.

`where` example using per-row predicates:

```json
"where": {
  "operator": "eachAnd",
  "conditions": [
    { "operator": "eachEqual",
      "left":  { "entity": "orders", "field": "status", "type": { "name": "string" } },
      "right": { "type": { "name": "string" }, "value": "completed" } },
    { "operator": "eachEqual",
      "left":  { "entity": "orders", "field": "is_paid", "type": { "name": "boolean" } },
      "right": { "type": { "name": "boolean" }, "value": true } }
  ]
}
```

### `joins`

Each join specifies its type (`inner`, `left`, `right`, `full`), the entity to join, and an `on` condition. Like `where`, `on` accepts either a **boolean-returning** or a **boolean-array-returning** expression. For column-to-column matching (the typical join), use `eachEqual`:

```json
"joins": [
  {
    "type": "inner",
    "entity": "users",
    "on": {
      "operator": "eachEqual",
      "left":  { "entity": "o",     "field": "user_id", "type": { "name": "uuid" } },
      "right": { "entity": "users", "field": "id",      "type": { "name": "uuid" } }
    }
  }
]
```

### `groupBy` / `orderBy`

Both accept an array of field references.

```json
"groupBy": [
  { "entity": "orders", "field": "user_id", "type": { "name": "uuid" } }
],
"orderBy": [
  { "entity": "users", "field": "name", "type": { "name": "string" } }
]
```

### `pagination`

```json
"pagination": { "skip": 0, "take": 25 }
```

---

## Operations

### Two operator families

Every operator in the schema belongs to one of two parallel families that you choose between based on whether you're working with single values or with columns/rows:

| Family | Operands | Result | Operators |
|---|---|---|---|
| **Single-value** | reduce to one value per query (or per group) | one value | `and`, `or`, `not`, `equal`, `greaterThan`/`lessThan`/…, `add`/`subtract`/`multiply`/`divide`, aggregates |
| **Per-row (`each*`)** | at least one operand is a field or per-row computed column | one value **per row** | `eachAnd`/`eachOr`/`eachNot`, `eachEqual`, `eachGreaterThan`/`eachLessThan`/…, `eachAdd`/`eachSubtract`/`eachMultiply`/`eachDivide`, `eachDateAddDays`/`eachDateDiffDays`, `eachTimeAddSeconds`/`eachTimeDiffSeconds`, `eachDatetimeAddSeconds`/`eachDatetimeDiffSeconds` |

Where each family fits:

| Clause | Accepts |
|---|---|
| `where` / `join.on` | per-row boolean (typical) or single-value boolean |
| `having` | single-value boolean only — non-aggregated fields are structurally rejected |
| `select` | any value-returning expression, including per-row computed columns |
| `sum.arg` / `min_*.arg` / `max_*.arg` / `average_*.arg` | any array-returning expression (field, per-row computation) |
| right operand of any `each*` comparison | matching `*Returning` (broadcast scalar) or `*ArrayReturning` (element-wise) |

**Do not mix families inside the same boolean operator.** `and`/`or`/`not` accept only single-value boolean children; `eachAnd`/`eachOr`/`eachNot` accept only per-row boolean children. The schema enforces this via type.

### Single-value boolean operations

| Operator | Shape |
|----------|-------|
| `and`    | `{ "operator": "and", "conditions": [ ...booleanReturning ] }` |
| `or`     | `{ "operator": "or",  "conditions": [ ...booleanReturning ] }` |
| `not`    | `{ "operator": "not", "condition": booleanReturning }` |

Conditions must be **single-boolean** expressions: a boolean scalar, parameter, single-value equality, or single-value comparison. Typical use: combining aggregate comparisons in `having`.

```json
"having": {
  "operator": "and",
  "conditions": [
    { "operator": "greaterThan",
      "left":  { "operator": "count", "arg": { "entity": "orders", "field": "id", "type": { "name": "uuid" } } },
      "right": { "type": { "name": "number" }, "value": 5 } }
  ]
}
```

### Per-row boolean operations (`eachAnd` / `eachOr` / `eachNot`)

| Operator  | Shape |
|-----------|-------|
| `eachAnd` | `{ "operator": "eachAnd", "conditions": [ ...booleanArrayReturning ] }` |
| `eachOr`  | `{ "operator": "eachOr",  "conditions": [ ...booleanArrayReturning ] }` |
| `eachNot` | `{ "operator": "eachNot", "condition": booleanArrayReturning }` |

These combine per-row boolean columns element-wise. The result is also a per-row boolean column. Use them to compose multiple `each*` predicates in `where` or `join.on`. There is no dedicated `eachNotEqual` — express it as `eachNot(eachEqual(...))`.

### Single-value equality (`equal`)

Compares two **single-value** expressions of the same type and returns one boolean. Useful in `having` against aggregates, or anywhere both operands reduce to scalars.

```json
{
  "operator": "equal",
  "left":  { "operator": "max_number", "arg": { "entity": "orders", "field": "total", "type": { "name": "number" } } },
  "right": { "param_name": "target_max", "type": { "name": "number" } }
}
```

### Whole-sequence equality (`equal` on arrays)

The same `equal` operator, when both sides are array-returning expressions of the same type, asks **"are these two sequences equal as wholes?"** and returns one boolean. This is rarely needed; most "field equals value" filtering should use `eachEqual` instead.

```json
{
  "operator": "equal",
  "left":  { "param_name": "expected_ids", "type": { "name": "uuidArray" } },
  "right": { "param_name": "received_ids", "type": { "name": "uuidArray" } }
}
```

### Per-row equality (`eachEqual`)

For each row, returns `true` when `left` equals `right`. The `left` operand is an **array-returning** expression (typically a field). The `right` operand is either a **single-value-returning** expression (the threshold/literal case) or another **array-returning** expression (element-wise field-to-field comparison).

Supported types: `boolean`, `number`, `string`, `date`, `time`, `datetime`, `uuid`.

Field-to-literal:

```json
{
  "operator": "eachEqual",
  "left":  { "entity": "users", "field": "role", "type": { "name": "string" } },
  "right": { "type": { "name": "string" }, "value": "admin" }
}
```

Field-to-field (per-row, used in joins or cross-column filters):

```json
{
  "operator": "eachEqual",
  "left":  { "entity": "orders", "field": "user_id", "type": { "name": "uuid" } },
  "right": { "entity": "users",  "field": "id",      "type": { "name": "uuid" } }
}
```

### Single-value range comparisons

Range comparisons on **single-value-returning** expressions (scalars, parameters, aggregates). They return a boolean.

| Operator             | Meaning |
|----------------------|---------|
| `greaterThan`        | `>`     |
| `lessThan`           | `<`     |
| `greaterThanOrEqual` | `>=`    |
| `lessThanOrEqual`    | `<=`    |

Supported types: `number`, `string`, `date`, `time`, `datetime`.

```json
{
  "operator": "greaterThan",
  "left":  { "operator": "sum", "arg": { "entity": "orders", "field": "total", "type": { "name": "number" } } },
  "right": { "type": { "name": "number" }, "value": 500 }
}
```

### Per-row range comparisons (`each*`)

Per-row analogues of the range comparisons. `left` is array-returning (typically a field), `right` is either single-value-returning (one threshold for all rows) or array-returning (element-wise field-to-field).

| Operator                 | Meaning |
|--------------------------|---------|
| `eachGreaterThan`        | `>`     |
| `eachLessThan`           | `<`     |
| `eachGreaterThanOrEqual` | `>=`    |
| `eachLessThanOrEqual`    | `<=`    |

Supported types: `number`, `string`, `date`, `time`, `datetime`.

Field vs literal:

```json
{
  "operator": "eachGreaterThan",
  "left":  { "entity": "orders", "field": "total", "type": { "name": "number" } },
  "right": { "type": { "name": "number" }, "value": 100 }
}
```

Field vs field (per-row):

```json
{
  "operator": "eachGreaterThan",
  "left":  { "entity": "order_items", "field": "unit_price", "type": { "name": "number" } },
  "right": { "entity": "order_items", "field": "sale_price", "type": { "name": "number" } }
}
```

### Single-value arithmetic

Combines **single-value-returning** numeric expressions. Use aggregates to bridge field data into single-value arithmetic.

| Operator    | Meaning |
|-------------|---------|
| `add`       | `+`     |
| `subtract`  | `-`     |
| `multiply`  | `*`     |
| `divide`    | `/`     |

`values` is an array with at least 2 operands. For `subtract` and `divide`, evaluation is left-to-right (`[a, b, c]` means `a - b - c` / `a / b / c`).

```json
{
  "operator": "multiply",
  "values": [
    { "operator": "sum", "arg": { "entity": "orders", "field": "amount", "type": { "name": "number" } } },
    { "type": { "name": "number" }, "value": 0.9 }
  ],
  "alias": "discounted_total"
}
```

### Per-row arithmetic (`eachAdd` / `eachSubtract` / `eachMultiply` / `eachDivide`)

Per-row analogues of arithmetic. Each `values[i]` is `numericReturning` (broadcast scalar) or `numericArrayReturning` (zipped per-row column). Result is a numeric column aligned with the row set.

Use in `select` for computed columns, inside aggregates (`sum(eachMultiply(unit_price, quantity))`), or on the right side of any `each*` comparison.

```json
{
  "operator": "eachMultiply",
  "values": [
    { "entity": "order_items", "field": "unit_price", "type": { "name": "number" } },
    { "entity": "order_items", "field": "quantity",   "type": { "name": "number" } }
  ],
  "alias": "subtotal"
}
```

#### Broadcast and zip: mixing single-value and array operands

Any `each*` slot that accepts both `*Returning` and `*ArrayReturning` follows the same evaluation rule. The surrounding row set fixes a row count `N` (from `from` + `joins` + `where`, or from the group size when nested inside an aggregate after `groupBy`). Then:

- Each `*Returning` operand is **broadcast** — repeated `N` times so it has one value per row.
- Each `*ArrayReturning` operand is already aligned with `N` rows by construction (same query context).
- The operator runs **element-wise** across all operands, producing a length-`N` result vector.

So `eachAdd([fieldA, scalar, fieldB])` over three rows with `fieldA = [10, 20, 30]`, `scalar = 5`, `fieldB = [1, 2, 3]` evaluates to `[16, 27, 38]`. This is what makes patterns like `eachMultiply(unit_price, 1.05)` (5% per-row markup) and `eachAdd(base_price, tax, shipping)` (sum three columns per row) work naturally.

The return type is always `*ArrayReturning` even if every operand is a scalar — `eachAdd(2, 3)` in a `select` over a 4-row table yields the vector `[5, 5, 5, 5]`, not the scalar `5`. Use the single-value `add` for purely scalar work.

### Date math (`eachDateAddDays` / `eachDateDiffDays`)

Per-row date arithmetic, days as the unit.

| Operator | Shape | Returns |
|---|---|---|
| `eachDateAddDays` | `{ left: date, right: number }` | `date` (per row) |
| `eachDateDiffDays` | `{ left: date, right: date }` | `number` (per row) |

`left` / `right` accept the broadcast vs zipped polymorphism (`*Returning | *ArrayReturning`).

```json
{
  "operator": "eachDateAddDays",
  "left":  { "entity": "orders", "field": "order_date", "type": { "name": "date" } },
  "right": { "type": { "name": "number" }, "value": 30 },
  "alias": "delivery_eta"
}
```

### Datetime math (`eachDatetimeAddSeconds` / `eachDatetimeDiffSeconds`)

Per-row datetime arithmetic, seconds as the unit. Larger units are expressed by composing with `eachMultiply` (e.g. add `N` hours via `eachDatetimeAddSeconds(dt, eachMultiply(n, 3600))`).

| Operator | Shape | Returns |
|---|---|---|
| `eachDatetimeAddSeconds` | `{ left: datetime, right: number }` | `datetime` (per row) |
| `eachDatetimeDiffSeconds` | `{ left: datetime, right: datetime }` | `number` (per row) |

```json
{
  "operator": "eachGreaterThan",
  "left": {
    "operator": "eachDatetimeDiffSeconds",
    "left":  { "entity": "orders", "field": "shipped_at", "type": { "name": "datetime" } },
    "right": { "entity": "orders", "field": "ordered_at", "type": { "name": "datetime" } }
  },
  "right": { "type": { "name": "number" }, "value": 172800 }
}
```

### Time math (`eachTimeAddSeconds` / `eachTimeDiffSeconds`)

Per-row time-of-day arithmetic, seconds as the unit. Same broadcast / zip rules as the rest of the `each*` family.

| Operator | Shape | Returns |
|---|---|---|
| `eachTimeAddSeconds` | `{ left: time, right: number }` | `time` (per row) |
| `eachTimeDiffSeconds` | `{ left: time, right: time }` | `number` (per row) |

`eachTimeAddSeconds` overflow behaviour around `00:00:00` (wrap, saturate, error) is interpreter-defined — the schema doesn't constrain it.

```json
{
  "operator": "eachTimeAddSeconds",
  "left":  { "entity": "shifts", "field": "clock_in", "type": { "name": "time" } },
  "right": { "type": { "name": "number" }, "value": 1800 },
  "alias": "break_start"
}
```

### Aggregates

Aggregates reduce an array of field values to a single value. The `arg` is any array-returning expression (typically a field reference).

| Operator          | Input type  | Returns  |
|-------------------|-------------|----------|
| `count`           | any array   | number   |
| `sum`             | number      | number   |
| `average_number`  | number      | number   |
| `min_number`      | number      | number   |
| `max_number`      | number      | number   |
| `min_string`      | string      | string   |
| `max_string`      | string      | string   |
| `min_date`        | date        | date     |
| `max_date`        | date        | date     |
| `average_date`    | date        | date     |
| `min_time`        | time        | time     |
| `max_time`        | time        | time     |
| `average_time`    | time        | time     |
| `min_datetime`    | datetime    | datetime |
| `max_datetime`    | datetime    | datetime |
| `average_datetime`| datetime    | datetime |

```json
{ "operator": "sum",    "arg": { "entity": "items", "field": "price",    "type": { "name": "number" } } }
{ "operator": "count",  "arg": { "entity": "items", "field": "id",       "type": { "name": "uuid" } } }
{ "operator": "max_date","arg": { "entity": "orders","field": "order_date","type": { "name": "date" } } }
```

---

## Samples

The [`samples/`](samples/) directory contains query examples ordered by complexity.

| File | Description |
|------|-------------|
| [`01_simple_select.json`](samples/01_simple_select.json) | Select several fields from a single entity |
| [`02_aliases_and_pagination.json`](samples/02_aliases_and_pagination.json) | `from` alias, field aliases, and `pagination` |
| [`03_where_equality.json`](samples/03_where_equality.json) | Filter rows with a single `eachEqual` condition |
| [`04_boolean_logic.json`](samples/04_boolean_logic.json) | Nested `eachAnd` / `eachOr` / `eachNot` over field equalities |
| [`05_joins.json`](samples/05_joins.json) | `inner` and `left` joins using `eachEqual` for per-row key matching |
| [`06_count_aggregate.json`](samples/06_count_aggregate.json) | `count` aggregate with a `where` filter |
| [`07_group_by.json`](samples/07_group_by.json) | Multiple aggregates with `groupBy` |
| [`08_having.json`](samples/08_having.json) | `having` clause with `and` of two aggregate comparisons |
| [`09_arithmetic.json`](samples/09_arithmetic.json) | `add`, `multiply`, `divide` on aggregate results |
| [`10_parameters.json`](samples/10_parameters.json) | Named scalar parameters in per-row predicates |
| [`11_distinct.json`](samples/11_distinct.json) | `distinct: true` to deduplicate results |
| [`12_complex_query.json`](samples/12_complex_query.json) | Full query: joins, per-row `where`, groupBy, single-value `having`, arithmetic, parameters, orderBy, pagination |
| [`13_range_filter.json`](samples/13_range_filter.json) | `eachGreaterThan` and `eachLessThan` combined with `eachAnd` |
| [`14_each_field_to_field.json`](samples/14_each_field_to_field.json) | Per-row range comparison between two fields (no scalar threshold) |
| [`15_each_not_equal.json`](samples/15_each_not_equal.json) | `eachNot` wrapping `eachEqual` — the idiom for "field ≠ literal" |
| [`16_each_or_composition.json`](samples/16_each_or_composition.json) | Mixing `eachEqual` and `eachGreaterThan` via `eachAnd` + `eachOr` |
| [`17_each_arithmetic_select.json`](samples/17_each_arithmetic_select.json) | `eachMultiply` of two fields as a computed `select` column (`subtotal`) |
| [`18_aggregate_of_each_multiply.json`](samples/18_aggregate_of_each_multiply.json) | `sum(eachMultiply(unit_price, quantity))` grouped by user — line-item revenue |
| [`19_each_date_add_days.json`](samples/19_each_date_add_days.json) | `eachDateAddDays` to derive a `delivery_eta` column from `order_date + 30 days` |
| [`20_each_datetime_diff_where.json`](samples/20_each_datetime_diff_where.json) | `eachDatetimeDiffSeconds` inside `eachGreaterThan` to filter orders by ship-time |
| [`21_each_time_math.json`](samples/21_each_time_math.json) | `eachTimeAddSeconds` (time + offset) and `eachTimeDiffSeconds` (shift duration) |
