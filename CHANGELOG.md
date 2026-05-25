# Changelog

All notable changes to PureQL are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows Semantic Versioning with preview suffix `major.minor.patch-preview.major.minor.patch`.

---

## [0.1.0-preview.0.5.0] - 2026-05-25

Introduces sort direction control for `orderBy`. Previously `orderBy` accepted bare field references, making sort direction implementation-defined. Queries that used bare fields in `orderBy` must be migrated to the new `orderByItem` wrapper.

Tracking issue: #27.

### Added

- **`orderByItem` definition** — object with required `field` (a `$ref` to `#/definitions/field`) and optional `direction` (`"asc"` | `"desc"`, default `"asc"`).

### Changed

- **`orderBy.items`** now references `orderByItem` instead of `field` directly. Bare field objects in `orderBy` are no longer valid; wrap each field in `{ "field": <field>, "direction": "asc" }`.

---

## [0.1.0-preview.0.4.0] - 2026-05-25

Renames the internal `integer_equality` definition to `number_equality` for consistency with the `number` scalar type.

Tracking issue: #28.

### Changed

- **`integer_equality` renamed to `number_equality`** in `definitions/equalities`. The `$ref` in `singleValueEquality` updated accordingly.

---

## [0.1.0-preview.0.3.0] - 2026-05-25

Adds the per-row arithmetic and date/datetime math operators to the `each*` family established in `0.2.0`. Together with the existing per-row boolean/comparison operators, this closes the gap that previously made per-row computed columns inexpressible (e.g. `unit_price * quantity AS subtotal`, `sum(unit_price * quantity)`, `order_date + 30 days`, `shipped_at - ordered_at > 48h`). Purely additive on top of `0.2.0`.

Tracking issue: #47.

### Added

- **Per-row numeric arithmetic**: `eachAdd`, `eachSubtract`, `eachMultiply`, `eachDivide`. `values` is an array of `numericReturning | numericArrayReturning` items (broadcast scalars, zip arrays), `minItems: 2`. Result is `numericArrayReturning`. Mirrors the existing single-value `arithmetic` family but accepts fields directly. Slots into `select` (computed columns), aggregate `arg`, and the right operand of any `each*` comparison. Added to `numericArrayReturning`.
- **Per-row date math**:
  - `eachDateAddDays` — `{ left: date \| dateArray, right: number \| numberArray }` → `dateArrayReturning`. Adds N days per row.
  - `eachDateDiffDays` — `{ left: date \| dateArray, right: date \| dateArray }` → `numericArrayReturning`. Difference in days.
- **Per-row datetime math**:
  - `eachDatetimeAddSeconds` — `{ left: datetime \| datetimeArray, right: number \| numberArray }` → `dateTimeArrayReturning`. Adds N seconds per row.
  - `eachDatetimeDiffSeconds` — `{ left: datetime \| datetimeArray, right: datetime \| datetimeArray }` → `numericArrayReturning`. Difference in seconds.
- **Per-row time math**:
  - `eachTimeAddSeconds` — `{ left: time \| timeArray, right: number \| numberArray }` → `timeArrayReturning`. Adds N seconds per row; wrap/saturate/error behaviour around `00:00:00` is interpreter-defined.
  - `eachTimeDiffSeconds` — `{ left: time \| timeArray, right: time \| timeArray }` → `numericArrayReturning`. Difference in seconds.
- New schema groups `eachArithmetics`, `eachDateArithmetics`, `eachTimeArithmetics`, `eachDatetimeArithmetics`, plus the `eachArithmetic` union. The three diff operators are referenced from `numericArrayReturning`; `eachDateAddDays` from `dateArrayReturning`; `eachTimeAddSeconds` from `timeArrayReturning`; `eachDatetimeAddSeconds` from `dateTimeArrayReturning`.
- Five new reference samples:
  - `17_each_arithmetic_select.json` — `eachMultiply(unit_price, quantity)` as a computed `select` column.
  - `18_aggregate_of_each_multiply.json` — `sum(eachMultiply(unit_price, quantity))` grouped by user — the textbook line-item revenue query.
  - `19_each_date_add_days.json` — `eachDateAddDays(order_date, 30)` derives a `delivery_eta` column.
  - `20_each_datetime_diff_where.json` — `eachDatetimeDiffSeconds` inside `eachGreaterThan` filters orders whose ship time exceeds 48 hours.
  - `21_each_time_math.json` — `eachTimeAddSeconds` and `eachTimeDiffSeconds` over `clock_in` / `clock_out` time fields.

### Changed

- **`CLAUDE.md` rewritten around the "two operator families" model.** The old "fields cannot appear in arithmetic / comparison" rules — outdated since `0.2.0` and now wrong for arithmetic too — were replaced with explicit guidance on when to use each family. A new "Where each family fits" table maps clauses to accepted families. The "Field equality uses `arrayEquality`" rule is now "prefer `eachEqual`; `arrayEquality` is reserved for whole-sequence equality".
- **README "Operations" section** extended with per-operator subsections for `eachAdd`/`eachSubtract`/`eachMultiply`/`eachDivide`, `eachDateAddDays`/`eachDateDiffDays`, `eachDatetimeAddSeconds`/`eachDatetimeDiffSeconds`. The "Two families" overview now lists arithmetic alongside booleans/comparisons.

### Interpreter notes

- **Result type of per-row arithmetic**: every `eachX` arithmetic / date / time / datetime operator returns a numeric / date / time / datetime *column* aligned with the current row set. Maps to SQL projection expressions, LINQ row lambdas, or in-memory column transforms — same model as `0.2.0`'s `each*` comparisons.
- **Broadcast vs zip semantics (mixed `*Returning` and `*ArrayReturning` operands)**: every `each*` slot that admits both kinds uses one shared evaluation rule:
  1. The surrounding row set fixes a row count `N` — determined by `from` + `joins` + `where` for `where` / `select` / `join.on` expressions, or by the group size for expressions nested inside an aggregate `arg` after `groupBy`.
  2. Each `*Returning` operand is **broadcast** — repeated `N` times so it has one value per row. (In SQL backends, this is implicit — a scalar in a projection IS the value for every row.)
  3. Each `*ArrayReturning` operand is already aligned with the same `N` rows by construction (it comes from the same row set / group).
  4. The operator runs **element-wise across all operands**, producing a length-`N` result vector.

  So `eachAdd([fieldA, scalar, fieldB])` over 3 rows with `fieldA = [10, 20, 30]`, `scalar = 5`, `fieldB = [1, 2, 3]` evaluates to `[16, 27, 38]`. This is what makes `eachMultiply(unit_price, 1.05)` (5% per-row markup) and `eachAdd(base_price, tax, shipping)` (sum three columns per row) work in one place.

  The return type is always `*ArrayReturning` even if every operand is a `*Returning`: `eachAdd(2, 3)` in a `select` over a 4-row table yields `[5, 5, 5, 5]`, not `5`. Interpreters should not optimize this away as a constant — the row-count alignment is structural. Use single-value `add` for purely scalar work.

  Backend implementation hints:
  - SQL: scalars become literals in the projection / `WHERE` predicate; `*ArrayReturning` operands become column references. The SQL engine handles broadcast natively. No special case needed.
  - LINQ / row-lambda backends: emit `row => operator(arg1(row), arg2(row), …)` where each `arg_i` resolves to either a captured constant (broadcast) or a row-accessor (zip).
  - Column-vector backends (in-memory analytics): determine `N` from the parent context; materialize each scalar as a length-`N` vector via broadcast; then run the operator element-wise.
- **Subtract / divide ordering**: same as their single-value siblings — left-to-right fold over the `values` array. For `eachSubtract([a, b, c])` over `N` rows, position `i` evaluates `a[i] - b[i] - c[i]`.
- **Aggregate over per-row arithmetic**: `sum` / `min_*` / `max_*` / `average_*` already accepted `*ArrayReturning` as `arg`; with `eachX` now in those unions, the same dispatch covers expressions like `sum(eachMultiply(field_a, field_b))` without additional cases.
- **Unit choice for date / time / datetime math**: days for `date`; seconds for `time` and `datetime`. Larger units are obtained by composition — e.g. "add N hours to a datetime" is `eachDatetimeAddSeconds(dt, eachMultiply(n, 3600))`. There is intentionally no `interval` type and no per-unit operator family; interpreters should not emulate one. Negative `right` values produce subtraction.
- **Diff operator direction**: `eachDateDiffDays` / `eachTimeDiffSeconds` / `eachDatetimeDiffSeconds` all compute `left - right`, so a positive result means `left` is later. The schema fixes this convention.
- **`eachTimeAddSeconds` overflow**: time-of-day is bounded (`00:00:00`–`23:59:59.…`). Wrap / saturate / error behaviour around the day boundary is interpreter-defined — pick one and document it.
- **Division by zero / numeric overflow / null propagation**: schema doesn't constrain. Define per-backend.
- **No `each*` arithmetic on `string`**: out of scope for this release; addable later without breakage.
- **CLAUDE.md interpreter rule**: any backend that previously rejected fields under `add` / `multiply` / etc. should keep rejecting them there — the *single-value* arithmetic family is unchanged. Fields now flow exclusively through the per-row family.

### Versioning

Minor preview bump (`0.1.0-preview.0.2.0` → `0.1.0-preview.0.3.0`). All schema changes are additive; no existing operator or shape was renamed, removed, or tightened. Both `version` and `$id` updated.

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
