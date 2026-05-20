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

### Fields live in `arrayReturning`, not `singleValueReturning`

A field reference (`{ entity, field, type }`) is an **array-returning** expression — it represents a whole column. Consequently:

- Fields go in `select`, `groupBy`, `orderBy`, `join.on`, and as `arg` to aggregate functions.
- Fields **cannot** appear directly as operands of `arithmetic` (`add`, `multiply`, etc.) — use an aggregate like `sum` to reduce them first.
- Fields **cannot** appear as operands of `comparison` (`greaterThan`, etc.) — those operators accept `numericReturning` / `stringReturning` (scalars, aggregates, arithmetic), not field references.

### Field equality uses `arrayEquality`

Comparing a field to a literal requires the literal to be an **array scalar**:

```json
{
  "operator": "equal",
  "left":  { "entity": "users", "field": "status", "type": { "name": "string" } },
  "right": { "type": { "name": "stringArray" }, "value": ["active"] }
}
```

The type on the right is `stringArray`, not `string`. This is `string_array_equality` under `arrayEquality`.

`singleValueEquality` (with `stringReturning` / `numericReturning`) is for comparing aggregates or scalars to each other, not for field comparisons.

### Range comparisons only on single-value expressions

`greaterThan` / `lessThan` etc. operate on `numericReturning` / `stringReturning` / `dateReturning` / etc. — scalars, parameters, and aggregates only. Use them in `having` to filter groups by aggregate results.

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
