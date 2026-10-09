# PureQL Specification — Project Info

## What this project is

A JSON Schema specification (`PureQL-Specification.json`) for a JSON-based relational query language. The goal is a type system enforced by the schema alone: every typing and placement rule is checked by a JSON Schema validator. The interpreter is left with name resolution (entities, fields, parameters, group keys, subqueries) and a few checks that need no type inference, listed under Validation in `README.md`. `samples/` holds queries that must stay valid; `tests/invalid/` holds queries that must stay invalid.

## Key files

- `tools/generate_schema.py` — **source of truth** for the schema. Generates `PureQL-Specification.json`
- `PureQL-Specification.json` — the generated JSON Schema (draft 2020-12). **Never edit it by hand**
- `tools/jsonfmt.py` — compact JSON formatting used for samples and tests
- `samples/` — valid queries, numbered from simple to complex
- `tests/valid/` — valid queries that are not samples (`001_deep_nesting.jsonc` guards against exponential validation)
- `tests/invalid/` — invalid queries, written by hand, each a valid base with exactly one thing broken. Every file is JSONC: a `//` comment with the description, then the bare query
- `README.md` — human-readable language reference

## Schema validation

Regenerate the schema after changing the generator (Python is needed only for this), then validate with ajv, exactly as CI does:

```bash
python3 tools/generate_schema.py
npx --yes ajv-cli@5.0.0 test --spec=draft2020 --strict=false -s PureQL-Specification.json -d "samples/*.json" -d "tests/valid/*.jsonc" --valid
npx --yes ajv-cli@5.0.0 test --spec=draft2020 --strict=false -s PureQL-Specification.json -d "tests/invalid/*.jsonc" --invalid
```

CI (`validate.yml`, and `release.yml` before publishing) runs only the two ajv commands: valid queries must pass, then invalid ones must fail. It does not regenerate anything, so always commit the regenerated schema together with the generator change.

## Critical design rules (read before editing the generator, samples or tests)

### One operator set, contexts by position

There is no single-value / `each*` split. Each operator (`equal`, `add`, `dateDiffDays`, …) exists once. Where it may appear and what its operands may be is fixed by the **context**, which the schema passes down through `$ref`. Each expression definition is generated as `<type>@<context>` or `<type>.nullable@<context>`.

| Context | Used in | Fields | Group keys | Aggregates |
|---|---|---|---|---|
| `row` | `where`, `join.on`, `groupBy` keys, aggregate `selector` / `predicate` | yes | no | no |
| `projection` | `select` / `orderBy` without `groupBy` | yes | no | over all rows (default) |
| `group` | `select` / `having` / `orderBy` with `groupBy` | no | yes | over the group (default) or `over: "all"` |

The root dispatches on whether `groupBy` is present, and operator nodes dispatch on `operator` (`if` / `then`). Operators generated per operand type (`equal`, `notEqual`, `in`, comparisons) and `orderBy` keys then pick their variant with `probe.<family>`, which reads the operand's type without validating it: a leaf's `type.name`, a fixed-type operator, or the operand named in `SPINE` (`if.then`, `coalesce.values[0]`, aggregate `selector`). Probes require the operand and its `type` to be objects and match one family at most, so a malformed node cannot fan out. Subtypes are merged into their supertype's definition (`decimal@ctx` holds the `integer` leaves and the integer-only operators), never added as a separate `anyOf` branch: ajv in draft 2020-12 mode evaluates every branch, so a duplicated branch doubles the work at each level. So each subtree is validated in full once. When adding an operator whose result type depends on an operand, add it to `SPINE` (the generator asserts this); when adding one generated per operand type, register a `guard`. Otherwise validation becomes exponential in query depth, which `tests/valid/001_deep_nesting.jsonc` checks under the CI timeout.

### Aggregates

`{ "operator": "sum", "over"?: "group" | "all", "selector": <row expr>, "predicate"?: <row boolean> }`. `over` defaults to `"group"` in a grouped query and `"all"` otherwise; samples and examples omit it unless it is `"all"` inside a grouped query. `count` has no selector; `any` / `all` require a predicate. The body is in row context, which has no aggregates, so aggregates cannot nest. `average`, `min` and `max` are non-null only over a group (omitted or `"group"` over, in a grouped query), with no predicate and a non-null selector. Otherwise they are nullable. `count` and `sum` are never null.

### Types and nulls

- Types: `integer`, `decimal`, `string`, `boolean`, `date`, `time`, `datetime`, `uuid`, each non-null (`{ "name": T }`) or nullable (`{ "name": T, "nullable": true }`).
- Implicit conversions: `T → T?` and `integer → decimal`. No others.
- Null literals are always typed (`{ "type": { "name": T, "nullable": true }, "value": null }`); there is no `null` type. A literal is nullable exactly when its value is `null`.
- Invariant: the type of an expression is determined by its subtree and its context (fixed by position, passed down by `$ref`). The context only decides an aggregate's default `over`. Never add a rule that infers a type from surrounding expressions.
- Null semantics: arithmetic, `concat`, date math, `round` / `floor` / `ceiling` are lifted (null if any operand is null). `if` is nullable when either branch is, and yields the branch taken. `equal` / comparisons / `in` return a non-null boolean. Every condition requires a non-null boolean.
- `divide` is always `decimal`; `integerDivide` / `modulo` / `floor` / `ceiling` / `round` (without `digits`) give `integer`.
- `datetime` literals need an offset (`Z` or `±hh:mm`, not `-00:00`). Literal patterns use `[0-9]`, never `\d`, no lookahead, and go through `pattern()`, which rejects newlines (Python's `$` matches before a final one).

### Query structure

- Field reference: `{ "source": <entity, subquery or alias>, "field": …, "type": … }`.
- `from` / `join` name exactly one of `entity` or `subquery`, plus an optional `alias`.
- `equal` keeps its null semantics in `join.on`: two null keys match. Samples that join on keys nullable on both sides guard with `notEqual(key, null)`.
- A field is nullable at a point if it is stored nullable or its source is on the optional side of an outer join before that point (`left`: joined source; `right`: earlier sources; `full`: both). A join's own `on` comes before the join, so it keeps the joined source's stored nullability; a later join's `on` does not. References declare exactly this nullability, never more or less, and the same stored field is declared the same way in every sample.
- `select` columns are `{ alias, type, expression }` with alias and type required. The schema checks the expression against the declared type.
- `groupBy` items are `{ alias?, type, expression }`: any row expression can be a key, and its declared type is checked like a `select` column. Keys are referenced as `{ "key": i, "type": … }`, repeating that declared type exactly, and are never emitted automatically.
- Anything referenced from elsewhere (subquery columns, group keys) must declare its type and have it checked by the schema. Otherwise the interpreter would need type inference, which breaks the design goal.
- `orderBy` items are `{ expression, direction? }`. Repeat an expression rather than referencing a `select` alias.
- Lists (`stringList`, …, or a subquery column `{ subquery, field, type }`) are values accepted only by `in`.
- `subqueries` is a flat array of `{ name, query }` on the main query only. A subquery reads only from earlier ones; there is no recursion.
- Every object has `additionalProperties: false`. Every array (`select`, `joins`, `groupBy`, `orderBy`, `subqueries`) has at least one item: an absent clause is omitted, never empty.
- Names (`NAME`) are non-empty with no leading or trailing space or tab and no line break; inner spaces are allowed.

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
   - `VERSION` in `tools/generate_schema.py`, then rerun it. This sets `version` and `$id` in `PureQL-Specification.json`; the `$id` URL pattern is `https://github.com/kudima03/PureQL-Specification/releases/download/<version>/PureQL-Specification.json`.
   - `CHANGELOG.md` — add a new `## [<version>] - YYYY-MM-DD` section above the previous one with `### Added / Changed / Removed / Fixed` entries as appropriate.
3. Merge the PR into `main`.
4. Push a tag from `main` matching the version exactly:
   ```bash
   git tag 0.1.0-preview.0.1.0
   git push origin 0.1.0-preview.0.1.0
   ```
5. The CD workflow (`release.yml`) fires automatically. It will:
   - Validate `samples/` and `tests/valid/` (must pass) and `tests/invalid/` (must fail) with ajv.
   - Verify the `version` field in the schema matches the tag (fails fast if they differ).
   - Extract the matching section from `CHANGELOG.md` as the release body.
   - Publish a GitHub Release with `PureQL-Specification.json`, `samples.zip`, `CHANGELOG.md`, and `README.md` as assets.
   - Mark the release as **pre-release** if the tag contains `-preview`.

### Execution semantics

What an interpreter computes is defined under **Semantics** in `README.md`: evaluation order and laziness, execution errors, 64-bit `integer` and exact `decimal` arithmetic, code-point strings, the order of every type, nanosecond times with wrap-around, aggregate results on no rows, parameter binding and source names. Change it there, never only in a sample. Samples and tests must not depend on anything listed under *Not specified yet*, and every query in `samples/` and `tests/valid/` should also pass name resolution: declared subqueries, unique source names, aliased sources referenced by alias.

## Adding samples and tests

1. **Sample:** add a bare query as `samples/NN_name.json` at the position matching its complexity, and renumber the following files if needed. Use `tools/jsonfmt.py` formatting, declare every column's type by hand, and update the samples table in `README.md`.
2. **Invalid test:** write `tests/invalid/NNN_name.jsonc` by hand with the next free number: a `//` comment describing what is broken, then the bare query in `tools/jsonfmt.py` formatting. Break exactly one thing in a valid base, and check that it is rejected for the intended reason: ajv prints the failing path when you validate the file on its own with `ajv validate`.
3. **Valid test:** a valid query that is not worth a sample (an edge case, a corner of the type rules) goes to `tests/valid/NNN_name.jsonc`, in the same JSONC format.
4. Use the e-commerce domain (users, orders, order_items, products, coupons, referrals) for consistency.
5. Run both ajv commands from [Schema validation](#schema-validation) before committing.
