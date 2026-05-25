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

### Two families of predicates

PureQL has **two parallel predicate families** that you choose between based on whether you're working with single values or with columns/rows:

| Need | Family | Returns | Operators |
|---|---|---|---|
| Combine/compare **single-value** expressions (aggregates, scalars) | Single-value family | one boolean | `and`, `or`, `not`, `equal`, `greaterThan`, `lessThan`, … |
| Filter/compare values **per row** of a column | Per-row (`each*`) family | one boolean **per row** | `eachAnd`, `eachOr`, `eachNot`, `eachEqual`, `eachGreaterThan`, `eachLessThan`, … |

`where` and `join.on` accept either family (they evaluate per row, but a literal `true` is also valid). `having` accepts only the single-value family. `and` / `or` / `not` themselves only accept single-value children — do not mix the two families inside the same boolean operator; use `eachAnd` / `eachOr` / `eachNot` to compose per-row predicates.

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

### Arithmetic operators

Arithmetic works on **numeric single-value-returning** expressions. Use aggregates to bridge field data into arithmetic.

| Operator    | Meaning |
|-------------|---------|
| `add`       | `+`     |
| `subtract`  | `-`     |
| `multiply`  | `*`     |
| `divide`    | `/`     |

All operators take a `values` array with at least 2 operands.

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
