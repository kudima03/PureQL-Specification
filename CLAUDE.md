# PureQL Specification — Project Info

## What this project is

A JSON Schema specification (`PureQL-Specification.json`) for a JSON-based relational query language with LINQ-like semantics. The goal is a type system enforced by the schema alone: every typing and placement rule is checked by a JSON Schema validator, and only name resolution (entities, fields, parameters, group keys, subqueries) is left to the interpreter. `samples/` holds queries that must stay valid; `tests/invalid/` holds queries that must stay invalid.

## Key files

- `tools/generate_schema.py` — **source of truth** for the schema. Generates `PureQL-Specification.json`
- `PureQL-Specification.json` — the generated JSON Schema (draft 2020-12). **Never edit it by hand**
- `tools/make_invalid_tests.py` — generates `tests/invalid/` from its ordered case list
- `tools/run_tests.py` — validates `samples/` (must pass) and `tests/invalid/` (must fail)
- `tools/jsonfmt.py` — compact JSON formatting used for samples and tests
- `samples/` — valid queries, numbered from simple to complex
- `tests/invalid/` — invalid queries, each a valid base with exactly one thing broken
- `README.md` — human-readable language reference

## Schema validation

```bash
python3 tools/generate_schema.py && python3 tools/make_invalid_tests.py && python3 tools/run_tests.py
```

CI (`validate.yml`) regenerates both artifacts and fails if they differ from the committed files, then runs the tests. After changing a generator, always commit the regenerated output. To cross-check with a second validator, use ajv 8 in draft 2020-12 mode with `strict: false`.

## Critical design rules (read before editing the generator, samples or tests)

### One operator set, contexts by position

There is no single-value / `each*` split. Each operator (`equal`, `add`, `dateDiffDays`, …) exists once. Where it may appear and what its operands may be is fixed by the **context**, which the schema passes down through `$ref`. Each expression definition is generated as `<type>@<context>` or `<type>.nullable@<context>`.

| Context | Used in | Fields | Group keys | Aggregates |
|---|---|---|---|---|
| `row` | `where`, `join.on`, `groupBy` keys, aggregate `selector` / `predicate` | yes | no | no |
| `projection` | `select` / `orderBy` without `groupBy` | yes | no | `over: "all"` |
| `group` | `select` / `having` / `orderBy` with `groupBy` | no | yes | `over: "group"` or `"all"` |

The root dispatches on whether `groupBy` is present, and operator nodes dispatch on `operator` (`if` / `then`), so validation never tries every branch. Keep this dispatch when adding operators, or validation becomes exponential in query depth.

### Aggregates

`{ "operator": "sum", "over": "group" | "all", "selector": <row expr>, "predicate"?: <row boolean> }`. `count` has no selector; `any` / `all` require a predicate. The body is in row context, which has no aggregates, so aggregates cannot nest. `average`, `min` and `max` are non-null only with `over: "group"`, no predicate and a non-null selector. Otherwise they are nullable. `count` and `sum` are never null.

### Types and nulls

- Types: `integer`, `decimal`, `string`, `boolean`, `date`, `time`, `datetime`, `uuid`, each non-null (`{ "name": T }`) or nullable (`{ "name": T, "nullable": true }`).
- Implicit conversions: `T → T?` and `integer → decimal`. No others.
- Null literals are always typed (`{ "type": { "name": T, "nullable": true }, "value": null }`); there is no `null` type. A literal is nullable exactly when its value is `null`.
- Invariant: the type of an expression is determined by its subtree alone. Never add a rule that infers a type from the context.
- C# null semantics. Arithmetic, `concat`, date math, `if`, `round` / `floor` / `ceiling` are lifted. `equal` / comparisons / `in` return a non-null boolean. Every condition requires a non-null boolean.
- `divide` is always `decimal`; `integerDivide` / `modulo` / `floor` / `ceiling` / `round` (without `digits`) give `integer`.
- `datetime` literals need an offset (`Z` or `±hh:mm`, not `-00:00`). Literal patterns use `[0-9]`, never `\d`, and no lookahead.

### Query structure

- Field reference: `{ "source": <entity, subquery or alias>, "field": …, "type": … }`.
- `from` / `join` name exactly one of `entity` or `subquery`, plus an optional `alias`.
- Inside `join.on`, fields keep their stored nullability. After an outer join, fields of the optional side are declared nullable.
- `select` columns are `{ alias, type, expression }` with alias and type required. The schema checks the expression against the declared type.
- `groupBy` items are `{ expression, alias? }`, and any row expression can be a key. Keys are referenced as `{ "key": i, "type": … }` and are never emitted automatically.
- `orderBy` items are `{ expression, direction? }`. Repeat an expression rather than referencing a `select` alias.
- Lists (`stringList`, …, or a subquery column `{ subquery, field, type }`) are values accepted only by `in`.
- `subqueries` is a flat array of `{ name, query }` on the main query only. A subquery reads only from earlier ones; there is no recursion.
- Every object has `additionalProperties: false`.

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
   - Validate all samples against the schema.
   - Verify the `version` field in the schema matches the tag (fails fast if they differ).
   - Extract the matching section from `CHANGELOG.md` as the release body.
   - Publish a GitHub Release with `PureQL-Specification.json`, `samples.zip`, `CHANGELOG.md`, and `README.md` as assets.
   - Mark the release as **pre-release** if the tag contains `-preview`.

## Adding samples and tests

1. **Sample:** add a bare query as `samples/NN_name.json` at the position matching its complexity, and renumber the following files if needed. Use `tools/jsonfmt.py` formatting, declare every column's type by hand, and update the samples table in `README.md`.
2. **Invalid test:** add a case to the ordered `CASES` list in `tools/make_invalid_tests.py`, then rerun it; numbering follows the list. Break exactly one thing in a valid base, and check with `tools/run_tests.py` that it is rejected at the intended node.
3. Use the e-commerce domain (users, orders, order_items, products, coupons, referrals) for consistency.
4. Run `tools/run_tests.py` before committing.
