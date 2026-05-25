# PureQL Specification — Project Info

## What this project is

A JSON Schema specification (`PureQL-Specification.json`) for a JSON-based relational query language. The spec is the source of truth; `samples/` holds reference queries that must remain valid against it.

## Key files

- `PureQL-Specification.json` — the JSON Schema (draft 2020-12)
- `samples/` — example queries, numbered by complexity
- `README.md` — human-readable language reference

## Schema validation

To validate a sample against the spec (requires `ajv-cli`):

```bash
npx ajv-cli validate -s PureQL-Specification.json -d samples/01_simple_select.json
```

Or with Python's `jsonschema`:

```bash
python3 -c "
import json, jsonschema
spec = json.load(open('PureQL-Specification.json'))
doc  = json.load(open('samples/12_complex_query.json'))
jsonschema.validate(doc, spec)
print('valid')
"
```

## Critical design rules (read before editing samples)

### Two predicate / expression families

Every operator in the schema belongs to one of two parallel families:

- **Single-value family** (`and`, `or`, `not`, `equal`, `greaterThan`, …, `add`, `subtract`, `multiply`, `divide`) — operands and result are single values. Use when both sides reduce to one value per query (or per group, inside `having`): typically scalars, parameters, aggregates, or arithmetic over them.
- **Per-row (`each*`) family** (`eachAnd`, `eachOr`, `eachNot`, `eachEqual`, `eachGreaterThan`, …, `eachAdd`, `eachMultiply`, `eachDateAddDays`, `eachDatetimeDiffSeconds`, …) — operate per row of the current row set; result is a vector aligned with the input rows. Use when at least one operand is a field, or to build computed per-row columns.

**Do not mix families inside the same boolean operator.** `and`/`or`/`not` take only single-boolean children; `eachAnd`/`eachOr`/`eachNot` take only per-row boolean children.

### Where each family fits

| Clause | Accepts |
|---|---|
| `where` | single-value boolean **or** per-row boolean (per-row is the common case) |
| `join.on` | single-value boolean **or** per-row boolean (per-row equi-join is the common case) |
| `having` | single-value boolean **only** — operands must reduce to one value per group |
| `select` | any value-returning expression, including per-row computed columns |
| `groupBy` / `orderBy` | field references only |

### Fields are `arrayReturning`

A field reference (`{ entity, field, type }`) is an **array-returning** expression — it represents a whole column. Fields:

- Go in `select`, `groupBy`, `orderBy`, as `arg` to aggregate functions, and as operands of any `each*` operator.
- **Cannot** appear directly in single-value `add`/`multiply`/`greaterThan`/`equal`/etc. — use the per-row `eachX` variant for the row context, or reduce with an aggregate (`sum`, `count`, `max_*`, …) for the single-value context.

### Field equality: prefer `eachEqual` over `arrayEquality`

For "field = literal" or "field = field" filtering, use **`eachEqual`** with an unwrapped scalar on the right:

```json
{
  "operator": "eachEqual",
  "left":  { "entity": "users", "field": "status", "type": { "name": "string" } },
  "right": { "type": { "name": "string" }, "value": "active" }
}
```

`arrayEquality` (the `equal` operator with `*ArrayReturning` on both sides) still validates and is semantically distinct — it asks "are these two **whole sequences** equal as wholes?" and returns one boolean. Reserve it for that intent (e.g. comparing two parameter arrays). The historical idiom of `equal(field, [singleValue])` as a per-row filter has been migrated out of all bundled samples.

### Per-row equality vs single-value equality

| Operator | Operands | Result | Typical placement |
|---|---|---|---|
| `equal` (single-value) | two `*Returning` | one boolean | `having` against aggregates |
| `equal` (whole-array) | two `*ArrayReturning` | one boolean | rare — whole-sequence equality |
| `eachEqual` | `*ArrayReturning` left, `*Returning` or `*ArrayReturning` right | one boolean per row | `where`, `join.on` |

### Range comparisons

Two parallel sets, same convention:

- Single-value: `greaterThan` / `lessThan` / `greaterThanOrEqual` / `lessThanOrEqual` over `numericReturning` / `stringReturning` / `dateReturning` / etc. Use in `having`.
- Per-row: `eachGreaterThan` / `eachLessThan` / `eachGreaterThanOrEqual` / `eachLessThanOrEqual`. `left` is `*ArrayReturning` (typically a field); `right` is `*Returning` (broadcast scalar) **or** `*ArrayReturning` (element-wise other field). Use in `where` / `join.on`.

### Arithmetic and date math

Same convention:

- Single-value `add` / `subtract` / `multiply` / `divide` — `values` items are `numericReturning` only. Use to combine aggregates and constants (e.g. `multiply(sum(total), 0.05)`).
- Per-row `eachAdd` / `eachSubtract` / `eachMultiply` / `eachDivide` — `values` items are `numericReturning | numericArrayReturning`. Use for computed per-row columns (e.g. `eachMultiply(unit_price field, quantity field)`).
- Date math: `eachDateAddDays(date, n_days) → date`, `eachDateDiffDays(date1, date2) → number`.
- Datetime math: `eachDatetimeAddSeconds(datetime, n_seconds) → datetime`, `eachDatetimeDiffSeconds(dt1, dt2) → number`.

Larger date/time units are expressed via composition with `eachMultiply` (e.g. `eachDatetimeAddSeconds(dt, eachMultiply(days, 86400))`). No `interval` type exists.

### `joinItem` has no alias

Only the root `from` expression supports an `alias`. Joined entities are always referenced by their `entity` name string.

### `groupBy` and `orderBy` take `field` objects

Not select expressions — just plain `{ entity, field, type }` field references. No aliases, no operators.

## Workflow rules

- Never commit directly to `main`. Always create a new branch and open a pull request.
- Do not mention yourself (Claude) in commit messages. Commit messages describe the change, not the author.

## Release flow

### Version format

| Channel | Format | Example |
|---|---|---|
| Stable | `major.minor.patch` | `1.0.0` |
| Preview | `major.minor.patch-preview.major.minor.patch` | `0.1.0-preview.0.1.0` |

Tags have no `v` prefix.

### Versioning rules

| Change | Bump |
|---|---|
| New optional field or expression type | minor |
| Rename, remove, or tighten any constraint | major |
| Fix a validation bug without changing intent | patch |

### Steps to release

1. Create a branch and open a PR as normal.
2. In the same PR, update **both**:
   - `version` and `$id` in `PureQL-Specification.json` — set them to the new version string. The `$id` URL pattern is `https://github.com/kudima03/PureQL-Specification/releases/download/<version>/PureQL-Specification.json`.
   - `CHANGELOG.md` — add a new `## [<version>] - YYYY-MM-DD` section above the previous one with `### Added / Changed / Removed / Fixed` entries as appropriate.
3. Merge the PR into `main`.
4. Push a tag from `main` matching the version exactly:
   ```bash
   git tag 0.1.0-preview.0.1.0
   git push origin 0.1.0-preview.0.1.0
   ```
5. The CD workflow (`release.yml`) fires automatically. It will:
   - Validate all samples against the schema.
   - Verify the `version` field in the schema matches the tag (fails fast if they differ).
   - Extract the matching section from `CHANGELOG.md` as the release body.
   - Publish a GitHub Release with `PureQL-Specification.json`, `samples.zip`, `CHANGELOG.md`, and `README.md` as assets.
   - Mark the release as **pre-release** if the tag contains `-preview`.

## Adding new samples

1. Number the file (`13_my_sample.json`) to keep ordering clear.
2. Run schema validation before committing.
3. Update the samples table in `README.md`.
4. Use the e-commerce domain (users, orders, order_items, products, coupons, referrals) for consistency with existing samples.
