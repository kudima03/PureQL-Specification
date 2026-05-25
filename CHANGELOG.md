# Changelog

All notable changes to PureQL are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows Semantic Versioning with preview suffix `major.minor.patch-preview.major.minor.patch`.

---

## [0.1.0-preview.0.2.0] - 2026-05-25

This release establishes the **per-row predicate family (`each*`)** as a first-class, type-distinct set of expressions. All `each*` operators now return a per-row boolean *column* (`booleanArrayReturning`), not a single boolean — making PureQL's type system express the row-vs-scalar distinction that SQL hides. This is purely additive on top of `0.1.0-preview.0.1.0`: no operator existing in that release was removed or renamed in a user-visible way.

### Added

- **`eachEqual` operator** for all seven comparable types (`boolean`, `number`, `string`, `date`, `time`, `datetime`, `uuid`). Per-row equality between an array-returning expression (typically a field) on `left` and either a single value or another array-returning expression on `right`. Replaces the previous idiom of writing `equal` with a single-element array literal (which kept working but was semantically a whole-sequence comparison, not a per-row one).
- **`eachAnd`, `eachOr`, `eachNot` operators**. Element-wise boolean composition over `booleanArrayReturning` operands; result is itself `booleanArrayReturning`. `eachAnd.conditions` and `eachOr.conditions` are arrays with `minItems: 1`; `eachNot.condition` is a single `booleanArrayReturning`. Use these to compose multiple `each*` predicates inside `where` or `join.on`.
- **Field-to-field per-row comparisons.** The `right` operand of every `each*` comparison now accepts either `*Returning` (a scalar/parameter/aggregate, broadcast to every row) **or** `*ArrayReturning` (another field, compared element-wise). Enables predicates like `order_items.unit_price > order_items.sale_price` directly, without aggregates or workarounds. See `samples/14_each_field_to_field.json`.
- **`where` and `joinItem.on` now accept `booleanArrayReturning`** in addition to `booleanReturning`. This lets `each*` predicates appear directly as the top of a `where` clause or a join condition without a wrapping `and`/`or`.
- New schema definitions: `eachComparison` and `eachEquality` unions; `eachComparisons`, `eachEqualities`, and `eachBooleanOperations` groups. All are referenced from `booleanArrayReturning`.
- Four new reference samples:
  - `13_range_filter.json` — `eachGreaterThan` / `eachLessThan` combined with `eachAnd`.
  - `14_each_field_to_field.json` — per-row range comparison between two fields (no scalar threshold).
  - `15_each_not_equal.json` — `eachNot(eachEqual(...))`, the canonical idiom for "field ≠ literal".
  - `16_each_or_composition.json` — `eachAnd` + `eachOr` mixing `eachEqual` and `eachGreaterThan` of different types.

### Changed

- **Sample migration to the new convention.** Samples 03–06, 10–12 previously expressed per-row field-to-literal filtering as `equal` with a single-element array literal on `right` (e.g. `{ "type": "stringArray", "value": ["active"] }`). They now use `eachEqual` with an unwrapped scalar (`{ "type": "string", "value": "active" }`). Join conditions in samples 05, 10, 11, 12 likewise switched from `equal` to `eachEqual`. Parameter samples in 10 and 12 dropped their array wrappers (`stringArray` parameter → `string` parameter, etc.). The schema still accepts the old shape — this is a recommended-style migration, not a forced one.
- **README documentation reorganized** around the "two predicate families" model: a single-value family (`and`/`or`/`not`, `equal`, `greaterThan`, …) and a per-row family (`eachAnd`/`eachOr`/`eachNot`, `eachEqual`, `eachGreaterThan`, …). The `where` / `having` section now states explicitly that `having` accepts only single-value expressions (so non-aggregated fields can never appear there).

### Interpreter notes

Highlights for downstream interpreter implementations migrating from `0.1.0-preview.0.1.0` (or extending an interpreter that has never seen `each*`):

- **Result type of `each*`**: every `each*` expression evaluates to a vector of booleans aligned with the current row set, not a single boolean. Concretely, `eachEqual(field, scalar)` produces one boolean per input row; in a SQL backend this maps to a `WHERE` predicate, in a LINQ backend to a row-level lambda body, in an in-memory backend to a `bool[]` mask.
- **`right` operand polymorphism**: `right` is now `oneOf [*Returning, *ArrayReturning]`. Implementations must dispatch on the shape:
  - `*Returning` (scalar / parameter / aggregate) → evaluate once, broadcast to every row.
  - `*ArrayReturning` (typically another field) → align per row and compare element-wise. In SQL, both forms collapse to the same predicate text; in evaluators that materialize columns, the broadcast vs. zip distinction matters.
- **`eachAnd` / `eachOr` semantics**: element-wise AND / OR over equal-length boolean vectors. With `minItems: 1`, a single-element `eachAnd` is the identity on its operand (interpreters may treat as a no-op).
- **`eachNot` semantics**: element-wise negation of a boolean vector. Distinct from `not`, which inverts a single boolean.
- **`where` dispatch**: the `where` value is either `booleanReturning` (single bool — include all rows if true, none if false) or `booleanArrayReturning` (per-row mask — filter by the mask). Interpreters should branch on which `oneOf` arm matched.
- **`joinItem.on` dispatch**: same polymorphism as `where`. Per-row case is the typical equi-join (`eachEqual(leftField, rightField)`); single-value case is a constant join predicate.
- **`having` is unchanged**: still `booleanReturning` only. The schema now structurally rejects placing an `each*` expression directly in `having`, which earlier could validate by accident. Any interpreter that relied on the looser rule must move row-level predicates to `where`.
- **No `eachNotEqual` operator**: by design, express "field ≠ X" as `eachNot(eachEqual(field, X))`. Interpreters can pattern-match this idiom for optimization if desired.
- **Single-value `and` / `or` / `not` are unchanged** and only accept `booleanReturning` children. Do not allow mixing the two families inside the same boolean operator; the `each*` variants exist precisely so the type system separates them.
- **`equal` (whole-sequence array equality) is unchanged**. It still validates with `*ArrayReturning` on both sides and returns a single boolean. With the new `eachEqual` available, the historical pattern of `equal(field, [singleValue])` should be read as "are these two sequences equal as wholes" rather than "filter rows where field = singleValue" — the latter is now `eachEqual(field, singleValue)`.

### Versioning

Minor preview bump (`0.1.0-preview.0.1.0` → `0.1.0-preview.0.2.0`). All changes are additive at the schema level; the migration of bundled samples to the new convention is a recommended-style change, not a constraint tightening. Both `version` and `$id` updated accordingly.

---

## [0.1.0-preview.0.1.0] - 2026-05-20

### Added
- Initial preview release of the PureQL JSON Schema specification (draft 2020-12)
- Core query structure: `from`, `select`, `where`, `joins`, `groupBy`, `having`, `orderBy`, `pagination`, `distinct`
- Complete type system: scalar types (`string`, `number`, `boolean`, `null`, `date`, `time`, `datetime`, `uuid`) and their array variants
- Expression types: field references, scalar literals, arithmetic operators, comparison operators, aggregate functions (`count`, `sum`, `avg`, `min`, `max`), and named parameters
- Boolean logic: `and`, `or`, `not` composable predicates
- Array equality for field-to-literal comparisons; single-value equality for aggregate/scalar comparisons
- Range comparisons (`greaterThan`, `lessThan`, `greaterThanOrEqual`, `lessThanOrEqual`) for numeric, string, and date single-value expressions
- Join support (`inner`, `left`, `right`, `full`) with array equality conditions
- 12 reference sample queries covering the e-commerce domain (`users`, `orders`, `order_items`, `products`, `coupons`, `referrals`)
