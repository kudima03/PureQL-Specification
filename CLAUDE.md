# PureQL Specification — Project Info

## What this project is

A JSON Schema specification (`PureQL-Specification.json`) for a JSON-based relational query language. The goal is a type system enforced by the schema alone: every typing and placement rule is checked by a JSON Schema validator. The interpreter is left with name resolution (entities, fields, parameters, group keys, subqueries) and a few checks that need no type inference, listed under Validation in `README.md`. `samples/valid/` holds queries that must stay valid; `samples/invalid/` holds queries that must stay invalid.

## Key files

- `tools/generate_schema.py` — **source of truth** for the schema. Generates `PureQL-Specification.json`
- `PureQL-Specification.json` — the generated JSON Schema (draft 2020-12). **Never edit it by hand**
- `samples/valid/*.json` — samples: valid queries, numbered from simple to complex. Formatting is checked by CI and they ship as `samples.zip`
- `samples/valid/*.jsonc` — valid tests: valid queries that are not worth a sample (`001_deep_nesting.jsonc` guards against exponential validation)
- `samples/invalid/` — invalid queries, written by hand, each a valid base with exactly one thing broken. Every file is JSONC: a `//` comment with the description, then the bare query
- `README.md` — human-readable language reference

## Schema validation

Regenerate the schema after changing the generator (Python is needed only for this), then validate with ajv, exactly as CI does:

```bash
python3 tools/generate_schema.py
npx --yes @prantlf/jsonlint@17.0.1 --check --indent 2 --trailing-newline --no-duplicate-keys PureQL-Specification.json
npx --yes @prantlf/jsonlint@17.0.1 --check --continue --indent 2 --trailing-newline --no-duplicate-keys "samples/valid/*.json"
npx --yes ajv-cli@5.0.0 test --spec=draft2020 --strict=false -s PureQL-Specification.json -d "samples/valid/*.json" -d "samples/valid/*.jsonc" --valid
npx --yes ajv-cli@5.0.0 test --spec=draft2020 --strict=false -s PureQL-Specification.json -d "samples/invalid/*.jsonc" --invalid
```

On every pull request, `validate.yml` first checks that the schema is formatted exactly as the generator writes it and that every sample has the same format (`jsonlint --check`: 2-space indent, every object and array expanded, final newline, no duplicate keys), then runs the two ajv commands: valid queries must pass, then invalid ones must fail. `release.yml` runs the ajv commands before publishing. CI does not regenerate anything, so always commit the regenerated schema together with the generator change, and never edit the schema by hand.

## Critical design rules (read before editing the generator, samples or tests)

### One operator set, contexts by position

There is no single-value / `each*` split. Each operator (`equal`, `add`, `dateDiffDays`, …) exists once. Where it may appear and what its operands may be is fixed by the **context**, which the schema passes down through `$ref`. Every expression is validated by `expr@<context>`; a position that expects a type refers to `<type>@<context>` or `<type>.nullable@<context>`.

| Context | Used in | Fields | Group keys | Aggregates |
|---|---|---|---|---|
| `row` | `where`, `join.on`, `groupBy` keys, aggregate `selector` / `predicate` | yes | no | no |
| `projection` | `select` / `orderBy` of a plain query (one row per row) | yes | no | over all rows, no `over` |
| `group` | `select` / `having` / `orderBy` with `groupBy` | no | yes | over the group (default) or `over: "all"` |
| `total` | `aggregate` (a total query: exactly one row) | no | no | over all rows, no `over` |

### Declared types and dispatch

Every expression declares its `type`, operators included: `{ "operator": "add", "type": { "name": "integer" }, "values": [ … ] }`. An operator's declared type is **exact**: the type it yields from its operands' declared types, never wider (`add` of integers is `integer`, a lifted operator is nullable exactly when an operand is, `coalesce` is non-null exactly when an operand is, `min` over a group is non-null exactly under the aggregate rules). Implicit conversions apply at the position, not in the declaration. A `select` column and a `groupBy` key have no `type` of their own: they have the type their expression declares.

The schema reads as tables of named definitions, and validation is linear by construction. Keep both:

- `expr@<ctx>` is the only entry to a node: `operator` present → `operator@<ctx>`, otherwise `leaf@<ctx>` (`value` → `literal`, `param` → `param`, `field` → `field`, `key` → `key`).
- `operator@<ctx>` sends each `operator` value to `<operator>@<ctx>`, which checks the node's shape and picks a signature by its declared type: `{ "if": declares.decimal.nullable, "then": add.decimal.nullable@row }`. A signature validates each operand once against its type and makes the declared type exact with shallow checks on the operands. `equal`, `notEqual`, `in` and comparisons have one result type, so they pick `<operator>.<family>@<ctx>` by the type the first operand declares instead.
- `<type>[.nullable]@<ctx>` is a position: `allOf` of `accepts.<type>[.nullable]` (shallow) and `expr@<ctx>`.
- Shallow checks are named definitions that read only the node's `type`: `declares.<type>[.nullable]` (exactly that type), `accepts.<type>[.nullable]` (the type or a subtype, non-null unless nullable), `accepts.equatable` / `accepts.comparable`, `declares.nullable` / `declares.nonNull`. They may be repeated anywhere (`contains`, `anyOf`, `if`) at no cost in depth. Type names are an `enum` even when there is one, so errors say which type was expected.

Dispatch on a value (`operator`, the declared type, an operand's family) is always `if` / `then` with a shallow `if`, never `anyOf` / `oneOf` over branches that reach `expr@…`. ajv stops at the first matching `anyOf` branch only without `allErrors`; Python `jsonschema` and `allErrors` evaluate every branch in full, which is exponential in depth: an `anyOf` prototype took over a minute at depth 2 in Python and ran out of memory at depth 4 with `allErrors`. Likewise never reference `expr@…` or a position from two branches that can both apply to one node. `samples/valid/001_deep_nesting.jsonc`, `samples/valid/010_deep_operand_chains.jsonc` and `samples/invalid/330_deep_malformed_operand_type.jsonc` check this under the CI timeout; when touching dispatch, also time a 30-level query with `allErrors` and with Python `jsonschema`.

### Aggregates

`{ "operator": "sum", "type": …, "over"?: "all", "selector": <row expr>, "predicate"?: <row boolean> }`. An aggregate runs over the group in a grouped query and over all rows otherwise; `over` exists only in group context and only as `"all"`, the default is never written. `count` has no selector; `any` / `all` require a predicate. The body is in row context, which has no aggregates, so aggregates cannot nest. `average`, `min` and `max` are non-null in a plain or grouped query (a result row exists only if a source row does, so every aggregate sees one) with no predicate and a non-null selector; otherwise, and always in a total query, they are nullable. `count` and `sum` are never null.

### Types and nulls

- Types: `integer`, `decimal`, `string`, `boolean`, `date`, `time`, `datetime`, `uuid`, each non-null (`{ "name": T }`) or nullable (`{ "name": T, "nullable": true }`). `"nullable": false` is rejected: one spelling per type. `integer` literals, `skip` and `take` are within 64 bits (`INT64`). A `decimal` literal is a string in one spelling (`DECIMAL`: no exponent, no leading or trailing zeros, no `-0`). Every type is ordered: comparisons and `min` / `max` accept all of them.
- Implicit conversions: `T → T?` and `integer → decimal`. No others.
- Null literals are always typed (`{ "type": { "name": T, "nullable": true }, "value": null }`); there is no `null` type. A literal is nullable exactly when its value is `null`.
- Invariant: the type of an expression is determined by its subtree and its context (fixed by position, passed down by `$ref`), and every expression declares it. Besides what may appear where, the context decides only an aggregate's rows: whether `over` may be written, and so whether `average` / `min` / `max` can be null (always in `total`). Never add a rule that infers a type from surrounding expressions.
- Null semantics: arithmetic, `concat`, date math, `round` / `floor` / `ceiling` are lifted (null if any operand is null). `if` is nullable when either branch is, and yields the branch taken. `equal` / comparisons / `in` return a non-null boolean. Every condition requires a non-null boolean.
- `divide` is always `decimal`; `integerDivide` / `modulo` / `floor` / `ceiling` / `round` (without `digits`) give `integer`.
- Every literal value has one spelling (`VALUE`, one `value.<type>` definition each): `time` fractions without trailing zeros, `datetime` always in UTC with `Z`, `uuid` in lower case; a list literal has no repeated value (`uniqueItems`). A `decimal` is m × 10^-s with |m| < 10^28 and 0 <= s <= 28 (`DECIMAL_DIGITS`), so every interpreter holds it exactly. `coalesce` has at most one non-null operand (`maxContains`): one after it is never reached. Equivalences between expressions (`and(a, and(b, c))`, `not(not(x))`, `not(equal)`, `if(true, …)`) are deliberately accepted, as in any language. Literal patterns use `[0-9]`, never `\d`, no lookahead, and go through `pattern()`, which rejects newlines (Python's `$` matches before a final one).

### Query structure

- Field reference: `{ "source": <entity, subquery or alias>, "field": …, "type": … }`.
- `from` / `join` name exactly one of `entity` or `subquery`, plus an optional `alias`. A join's kind is `kind` (`inner` / `left` / `right` / `full`): `type` always means a type object.
- A parameter is `{ "param": …, "type": … }`. A unary operator's operand is `operand` (`floor`, `ceiling`, `round`, `in`), so `value` only ever means a literal's value.
- Defaults are never written: no `"direction": "asc"` (ascending is the absence of `direction`).
- `distinctBy` lists `select` aliases (each once, checked by `uniqueItems`); of the rows equal on them it keeps the first in `orderBy` order, so it applies after `orderBy` and before `pagination`. Listing every alias is SQL `DISTINCT`; there is no `distinct` flag. Select aliases must be unique: the interpreter checks this, a schema cannot compare items by one property.
- `equal` keeps its null semantics in `join.on`: two null keys match. Samples that join on keys nullable on both sides guard with `notEqual(key, null)`.
- A field is nullable at a point if it is stored nullable or its source is on the optional side of an outer join before that point (`left`: joined source; `right`: earlier sources; `full`: both). A join's own `on` comes before the join, so it keeps the joined source's stored nullability; a later join's `on` does not. References declare exactly this nullability, never more or less, and the same stored field is declared the same way in every sample.
- Three kinds of query, by shape: plain (`select`: one row per row), grouped (`groupBy` + `select`: one row per group), total (`aggregate` instead of `select`: exactly one row; no `orderBy`, `distinctBy`, `pagination`, `having`). The root and `query` dispatch on `groupBy`, then `aggregate`.
- `select` / `aggregate` columns are `{ alias, expression }`, both required. A column has the type its expression declares, so a query's result schema is `select[i].alias` and `select[i].expression.type`.
- `groupBy` items are `{ alias, expression }`: any row expression can be a key, and the alias is required. Keys are referenced by alias as `{ "key": "user_id", "type": … }`, repeating that key's `expression.type` exactly, and are never emitted automatically.
- Every expression declares its type, and the schema checks each declaration that does not depend on the catalog. Anything referenced from elsewhere (subquery columns, group keys) takes the type its expression declares. Otherwise the interpreter would need type inference, which breaks the design goal.
- `orderBy` items are `{ expression, direction? }`. Repeat an expression rather than referencing a `select` alias.
- Lists (`stringList`, …, or a subquery column `{ subquery, field, type }`) are values accepted only by `in`.
- `subqueries` is a flat array of `{ name, query }` on the main query only. A subquery reads only from earlier ones; there is no recursion.
- Every object has `additionalProperties: false`. Every array (`select`, `joins`, `groupBy`, `orderBy`, `subqueries`) has at least one item: an absent clause is omitted, never empty. `and` / `or` take at least two conditions.
- `pagination` requires `orderBy` (`dependentRequired`); in a subquery `orderBy` also requires `pagination` or `distinctBy`, since a subquery's result is unordered.
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
   - Validate `samples/valid/` (must pass) and `samples/invalid/` (must fail) with ajv.
   - Verify the `version` field in the schema matches the tag (fails fast if they differ).
   - Extract the matching section from `CHANGELOG.md` as the release body.
   - Publish a GitHub Release with `PureQL-Specification.json`, `samples.zip`, `CHANGELOG.md`, and `README.md` as assets.
   - Mark the release as **pre-release** if the tag contains `-preview`.

### Execution semantics

What an interpreter computes is defined under **Semantics** in `README.md`: evaluation order and laziness, execution errors, 64-bit `integer` and exact `decimal` arithmetic, code-point strings, the order of every type, microsecond times with wrap-around, dates from year 0001, aggregate results on no rows, parameter binding and source names. Change it there, never only in a sample. Samples and tests must not depend on anything listed under *Not specified yet*, and every query in `samples/valid/` should also pass name resolution: declared subqueries, unique source names, aliased sources referenced by alias.

## Adding samples and tests

1. **Sample:** add a bare query as `samples/valid/NN_name.json` at the position matching its complexity, and renumber the following files if needed. Format it with `npx --yes @prantlf/jsonlint@17.0.1 --in-place --indent 2 --trailing-newline samples/valid/NN_name.json`, which CI checks; declare every operator's type by hand (`"type"` right after `"operator"`); columns and group keys have no `type`, and update the samples table in `README.md`.
2. **Invalid test:** write `samples/invalid/NNN_name.jsonc` by hand with the next free number: a `//` comment describing what is broken, then the bare query. Test formatting is not checked; keep the compact style of the existing tests (an object or array on one line while it fits in 110 columns). Break exactly one thing in a valid base, and check that it is rejected for the intended reason: ajv prints the failing path when you validate the file on its own with `ajv validate`.
3. **Valid test:** a valid query that is not worth a sample (an edge case, a corner of the type rules) goes to `samples/valid/NNN_name.jsonc`, in the same JSONC format.
4. Use the e-commerce domain (users, orders, order_items, products, coupons, referrals) for consistency.
5. Run both ajv commands from [Schema validation](#schema-validation) before committing.
