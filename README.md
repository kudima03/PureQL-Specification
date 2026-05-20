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

Fields carry their type as an **array type** in the schema — they represent a column of values. Use them in `select`, `groupBy`, `orderBy`, `join.on` conditions (via array equality), and as arguments to aggregate functions.

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

Both accept any **boolean-returning expression**: a boolean scalar, boolean parameter, boolean operation (`and`/`or`/`not`), an equality, or a comparison.

```json
"where": {
  "operator": "and",
  "conditions": [
    { "operator": "equal",
      "left":  { "entity": "orders", "field": "status", "type": { "name": "string" } },
      "right": { "type": { "name": "stringArray" }, "value": ["completed"] } },
    { "operator": "equal",
      "left":  { "entity": "orders", "field": "is_paid", "type": { "name": "boolean" } },
      "right": { "type": { "name": "booleanArray" }, "value": [true] } }
  ]
}
```

### `joins`

Each join specifies its type (`inner`, `left`, `right`, `full`), the entity to join, and a boolean `on` condition.

```json
"joins": [
  {
    "type": "inner",
    "entity": "users",
    "on": {
      "operator": "equal",
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

### Boolean operations

| Operator | Shape |
|----------|-------|
| `and`    | `{ "operator": "and", "conditions": [ ...booleanExpressions ] }` |
| `or`     | `{ "operator": "or",  "conditions": [ ...booleanExpressions ] }` |
| `not`    | `{ "operator": "not", "condition": booleanExpression }` |

### Equality

`equal` compares two values of the same type. To compare a **field** to a literal, use an array scalar on the right-hand side.

```json
{
  "operator": "equal",
  "left":  { "entity": "users", "field": "role", "type": { "name": "string" } },
  "right": { "type": { "name": "stringArray" }, "value": ["admin"] }
}
```

To compare two fields (e.g. in a join condition):

```json
{
  "operator": "equal",
  "left":  { "entity": "orders", "field": "user_id", "type": { "name": "uuid" } },
  "right": { "entity": "users",  "field": "id",      "type": { "name": "uuid" } }
}
```

### Comparison operators

Comparisons work on **single-value-returning** expressions (scalars, parameters, aggregates). They return a boolean.

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
| [`03_where_equality.json`](samples/03_where_equality.json) | Filter rows with a single `equal` condition |
| [`04_boolean_logic.json`](samples/04_boolean_logic.json) | Nested `and` / `or` / `not` conditions |
| [`05_joins.json`](samples/05_joins.json) | `inner` join and `left` join in one query |
| [`06_count_aggregate.json`](samples/06_count_aggregate.json) | `count` aggregate with a `where` filter |
| [`07_group_by.json`](samples/07_group_by.json) | Multiple aggregates with `groupBy` |
| [`08_having.json`](samples/08_having.json) | `having` clause with `and` of two comparisons |
| [`09_arithmetic.json`](samples/09_arithmetic.json) | `add`, `multiply`, `divide` on aggregate results |
| [`10_parameters.json`](samples/10_parameters.json) | Named parameters for dynamic query execution |
| [`11_distinct.json`](samples/11_distinct.json) | `distinct: true` to deduplicate results |
| [`12_complex_query.json`](samples/12_complex_query.json) | Full query: joins, where, groupBy, having, arithmetic, parameters, orderBy, pagination |
