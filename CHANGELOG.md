# Changelog

All notable changes to PureQL are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows Semantic Versioning with preview suffix `major.minor.patch-preview.major.minor.patch`.

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
