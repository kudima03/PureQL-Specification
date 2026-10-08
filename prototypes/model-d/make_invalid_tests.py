#!/usr/bin/env python3
"""Writes tests/invalid/*.json: each case is a valid base query with exactly one thing broken.

Cases are numbered in the order of CASES, from structural mistakes to context,
grouping and subquery rules.
"""
import copy
from pathlib import Path

from jsonfmt import dumps


def T(name, nullable=False):
    return {"name": name, "nullable": True} if nullable else {"name": name}


def F(field, t, source="orders", nullable=False):
    return {"source": source, "field": field, "type": T(t, nullable)}


def L(t, value):
    return {"type": T(t), "value": value}


def P(name, t, nullable=False):
    return {"param_name": name, "type": T(t, nullable)}


def N(t):
    """Typed null literal."""
    return {"type": T(t, True), "value": None}


def col(t, expression, alias="c", nullable=False):
    """A select column; `t` is the type the column would have if the expression were valid."""
    return {"alias": alias, "type": T(t, nullable), "expression": expression}


def op(name, **operands):
    return {"operator": name, **operands}


def agg(name, over="group", **operands):
    return {"operator": name, "over": over, **operands}


# The removed untyped null, kept to check it stays rejected.
UNTYPED_NULL = {"type": {"name": "null"}, "value": None}
UUID = "3f2a6c1e-8b4d-4e2a-9c1f-1a2b3c4d5e6f"
key0 = {"key": 0, "type": T("uuid")}
count = agg("count")
plain = {"from": {"entity": "orders"}, "select": [col("uuid", F("id", "uuid"), "id")]}
grouped = {
    "from": {"entity": "orders"},
    "groupBy": [{"expression": F("user_id", "uuid")}],
    "select": [col("uuid", key0, "user_id"), col("integer", count, "orders")],
}
subquery = {"name": "recent", "query": plain}


def q(base, **changes):
    query = copy.deepcopy(base)
    query.update(changes)
    return query


def without(base, key):
    query = copy.deepcopy(base)
    del query[key]
    return query


def where(condition):
    return q(plain, where=condition)


def select(t, expression, base=plain, nullable=False):
    return q(base, select=[col(t, expression, nullable=nullable)])


def having(condition):
    return q(grouped, having=condition)


eq_status = op("equal", left=F("status", "string"), right=L("string", "paid"))
nullable_flag = F("is_verified", "boolean", nullable=True)

CASES = [
    # --- query structure ----------------------------------------------------
    ("missing_from", "Query without from", without(plain, "from")),
    ("missing_select", "Query without select", without(plain, "select")),
    ("empty_select", "select with no columns", q(plain, select=[])),
    ("unknown_top_level_key", "Unknown top-level key (limit)", q(plain, limit=10)),
    ("pagination_take_zero", "pagination.take is 0", q(plain, pagination={"skip": 0, "take": 0})),
    ("pagination_negative_skip", "pagination.skip is negative", q(plain, pagination={"skip": -1, "take": 10})),
    ("pagination_without_take", "pagination without take", q(plain, pagination={"skip": 0})),
    ("distinct_not_boolean", "distinct given a string", q(plain, distinct="yes")),
    ("invalid_order_direction", "orderBy direction is not asc / desc",
        q(plain, orderBy=[{"expression": F("id", "uuid"), "direction": "up"}])),
    ("order_item_without_expression", "orderBy item without expression",
        q(plain, orderBy=[{"direction": "asc"}])),
    ("invalid_join_type", "join type cross",
        q(plain, joins=[{"type": "cross", "entity": "users", "on": L("boolean", True)}])),
    ("join_without_on", "join without on", q(plain, joins=[{"type": "inner", "entity": "users"}])),
    ("empty_group_by", "groupBy with no keys", q(grouped, groupBy=[])),
    ("typo_alias_key", "Misspelled alias key on a select item",
        q(plain, select=[{"alais": "id", "type": T("uuid"), "expression": F("id", "uuid")}])),

    # --- literals -----------------------------------------------------------
    ("integer_literal_as_string", "integer literal written as a JSON string",
        where(op("greaterThan", left=F("quantity", "integer"), right=L("integer", "5")))),
    ("fraction_in_integer_literal", "integer literal with a fractional value",
        where(op("greaterThan", left=F("quantity", "integer"), right=L("integer", 1.5)))),
    ("boolean_literal_as_string", "boolean literal written as a JSON string",
        where(op("equal", left=F("is_paid", "boolean"), right=L("boolean", "true")))),
    ("invalid_date_literal", "Malformed date literal",
        where(op("greaterThan", left=F("order_date", "date"), right=L("date", "2024-13-45")))),
    ("non_ascii_digits_in_date", "date literal written with Arabic-Indic digits",
        where(op("greaterThan", left=F("order_date", "date"), right=L("date", "٢٠٢٤-01-01")))),
    ("invalid_time_literal", "Malformed time literal",
        where(op("lessThan", left=F("window_start", "time"), right=L("time", "25:00:00")))),
    ("datetime_without_offset", "datetime literal without an offset",
        where(op("greaterThan", left=F("ordered_at", "datetime"), right=L("datetime", "2024-01-01T00:00:00")))),
    ("datetime_unknown_offset", "datetime literal with -00:00 (RFC 3339 'offset unknown')",
        where(op("greaterThan", left=F("ordered_at", "datetime"), right=L("datetime", "2024-01-01T00:00:00-00:00")))),
    ("datetime_lowercase_z", "datetime literal with a lowercase z",
        where(op("greaterThan", left=F("ordered_at", "datetime"), right=L("datetime", "2024-01-01T00:00:00z")))),
    ("datetime_offset_out_of_range", "datetime literal with a +24:00 offset",
        where(op("greaterThan", left=F("ordered_at", "datetime"), right=L("datetime", "2024-01-01T00:00:00+24:00")))),
    ("malformed_uuid_literal", "Malformed uuid literal",
        where(op("equal", left=F("id", "uuid"), right=L("uuid", "not-a-uuid")))),
    ("list_literal_wrong_element", "stringList literal containing a number",
        where(op("in", value=F("status", "string"), list={"type": T("stringList"), "value": ["paid", 5]}))),
    ("nullable_literal_with_value", "Literal typed decimal? with a non-null value",
        select("decimal", {"type": T("decimal", True), "value": 5}, nullable=True)),

    # --- references and type names ------------------------------------------
    ("field_without_type", "Field reference without a type",
        select("uuid", {"source": "orders", "field": "id"})),
    ("field_empty_name", "Field reference with an empty field name", select("uuid", F("", "uuid"))),
    ("field_with_entity_key", "Field reference using the old entity key instead of source",
        select("uuid", {"entity": "orders", "field": "id", "type": T("uuid")})),
    ("param_without_name", "Parameter without param_name", where({"type": T("boolean")})),
    ("unknown_type_name", "Type name number (split into integer / decimal)",
        select("decimal", F("total", "number"))),
    ("null_typed_field", "Field declared with type null", select("string", F("legacy", "null"))),
    ("untyped_null_in_equal", "Untyped null literal (removed type null) as an equal operand",
        where(op("equal", left=F("coupon_id", "uuid", nullable=True), right=UNTYPED_NULL))),
    ("untyped_null_add", "Regression: add over untyped nulls (type would come from nowhere)",
        select("decimal", op("add", values=[UNTYPED_NULL, UNTYPED_NULL]))),
    ("untyped_null_if", "Regression: if with untyped null in both branches",
        select("decimal", op("if", condition=F("is_paid", "boolean"), then=UNTYPED_NULL, **{"else": UNTYPED_NULL}))),

    # --- forms from the previous specification ------------------------------
    ("legacy_each_operator", "eachEqual (each* operators are gone)",
        where(op("eachEqual", left=F("status", "string"), right=L("string", "paid")))),
    ("legacy_aggregate_arg", "Aggregate with arg instead of over / selector",
        select("decimal", op("sum", arg=F("total", "decimal")), grouped)),
    ("legacy_typed_aggregate", "min_number (aggregates are no longer suffixed by type)",
        select("decimal", agg("min_number", selector=F("total", "decimal")), grouped)),
    ("legacy_array_type", "stringArray parameter (lists are stringList)",
        where(op("in", value=F("status", "string"), list=P("statuses", "stringArray")))),

    # --- operator shape -----------------------------------------------------
    ("unknown_operator", "Unknown operator like",
        where(op("like", left=F("name", "string"), right=L("string", "A%")))),
    ("and_without_conditions", "and with an empty conditions array", where(op("and", conditions=[]))),
    ("add_single_value", "add with one operand", select("integer", op("add", values=[F("quantity", "integer")]))),
    ("if_without_else", "if without else",
        select("string", op("if", condition=F("is_paid", "boolean"), then=L("string", "yes")))),
    ("coalesce_single_value", "coalesce with one operand",
        select("string", op("coalesce", values=[F("code", "string", nullable=True)]), nullable=True)),
    ("in_without_list", "in without list", where(op("in", value=F("status", "string")))),
    ("equal_extra_operand", "equal with an unexpected third operand",
        where(op("equal", left=F("status", "string"), right=L("string", "paid"), other=L("string", "x")))),

    # --- operand types ------------------------------------------------------
    ("where_not_boolean", "decimal field as where", where(F("total", "decimal"))),
    ("compare_decimal_with_string", "greaterThan(decimal field, string literal)",
        where(op("greaterThan", left=F("total", "decimal"), right=L("string", "100")))),
    ("equal_uuid_with_string", "equal(uuid field, string literal)",
        where(op("equal", left=F("id", "uuid"), right=L("string", UUID)))),
    ("uuid_greater_than", "Range comparison on uuid",
        where(op("greaterThan", left=F("id", "uuid"), right=L("uuid", UUID)))),
    ("boolean_less_than", "Range comparison on boolean",
        where(op("lessThan", left=F("is_paid", "boolean"), right=L("boolean", True)))),
    ("arithmetic_on_string", "add(string field, integer)",
        select("decimal", op("add", values=[F("name", "string"), L("integer", 1)]))),
    ("concat_with_integer", "concat(string, integer) — no implicit conversion to string",
        select("string", op("concat", values=[F("name", "string"), L("integer", 1)]))),
    ("if_branches_differ", "if with then: decimal and else: string",
        select("decimal", op("if", condition=F("is_paid", "boolean"), then=F("total", "decimal"),
                             **{"else": L("string", "n/a")}))),
    ("if_condition_not_boolean", "if.condition is a string",
        select("string", op("if", condition=F("status", "string"), then=L("string", "a"),
                            **{"else": L("string", "b")}))),
    ("not_on_integer", "not over an integer", where(op("not", condition=F("quantity", "integer")))),
    ("in_list_type_mismatch", "in(uuid field, stringList)",
        where(op("in", value=F("id", "uuid"), list=P("ids", "stringList")))),
    ("list_as_operand", "List parameter used as an equal operand instead of via `in` (old hole A4)",
        where(op("equal", left=F("status", "string"), right=P("statuses", "stringList")))),

    # --- integer / decimal --------------------------------------------------
    ("modulo_on_decimal", "modulo over a decimal operand",
        select("integer", op("modulo", left=F("total", "decimal"), right=L("integer", 2)))),
    ("integer_divide_on_decimal", "integerDivide over a decimal operand",
        select("integer", op("integerDivide", left=F("total", "decimal"), right=L("integer", 2)))),
    ("floor_of_string", "floor over a string", select("integer", op("floor", value=F("name", "string")))),
    ("round_digits_decimal", "round with decimal digits",
        select("decimal", op("round", value=F("total", "decimal"), digits=L("decimal", 2.5)))),
    ("decimal_days", "dateAddDays with decimal days",
        select("date", op("dateAddDays", left=F("order_date", "date"), right=F("total", "decimal")))),
    ("divide_result_as_integer", "divide (always decimal) used where integer days are required",
        select("date", op("dateAddDays", left=F("order_date", "date"),
                          right=op("divide", values=[F("quantity", "integer"), L("integer", 2)])))),
    ("round_digits_as_integer", "round with digits is decimal, so not usable as integer days",
        select("date", op("dateAddDays", left=F("order_date", "date"),
                          right=op("round", value=F("total", "decimal"), digits=L("integer", 0))))),

    # --- date / time / datetime ---------------------------------------------
    ("datetime_vs_date", "datetime compared with a date literal (no implicit conversion)",
        where(op("greaterThan", left=F("ordered_at", "datetime"), right=L("date", "2024-01-01")))),
    ("time_math_on_date", "timeAddSeconds applied to a date",
        select("time", op("timeAddSeconds", left=F("order_date", "date"), right=L("integer", 60)))),
    ("datetime_math_on_date", "datetimeAddSeconds applied to a date",
        select("datetime", op("datetimeAddSeconds", left=F("order_date", "date"), right=L("integer", 60)))),
    ("date_diff_date_and_datetime", "dateDiffDays(date, datetime)",
        select("integer", op("dateDiffDays", left=F("order_date", "date"), right=F("ordered_at", "datetime")))),
    ("time_diff_time_and_datetime", "timeDiffSeconds(time, datetime)",
        select("decimal", op("timeDiffSeconds", left=F("window_start", "time"), right=F("ordered_at", "datetime")))),

    # --- null / nullable ----------------------------------------------------
    ("nullable_boolean_as_where", "Nullable boolean field used directly as where", where(nullable_flag)),
    ("null_boolean_as_where", "Typed null boolean? as where", where(N("boolean"))),
    ("nullable_boolean_in_and", "Nullable boolean inside and.conditions",
        where(op("and", conditions=[eq_status, nullable_flag]))),
    ("nullable_boolean_in_not", "Nullable boolean inside not", where(op("not", condition=nullable_flag))),
    ("nullable_if_condition", "Nullable boolean as if.condition",
        select("string", op("if", condition=nullable_flag, then=L("string", "yes"), **{"else": L("string", "no")}))),
    ("nullable_join_on", "Nullable boolean parameter as join.on",
        q(plain, joins=[{"type": "inner", "entity": "users", "on": P("join_all", "boolean", nullable=True)}])),
    ("coalesce_still_nullable", "coalesce of nullable booleans only is still nullable, so not a condition",
        where(op("coalesce", values=[nullable_flag, P("fallback", "boolean", nullable=True)]))),
    ("lifted_if_in_where", "if with a nullable branch is nullable, so not a condition",
        where(op("if", condition=F("is_paid", "boolean"), then=nullable_flag, **{"else": L("boolean", True)}))),
    ("null_of_wrong_type", "equal(date field, null decimal?)",
        where(op("equal", left=F("order_date", "date"), right=N("decimal")))),
    ("nullable_round_digits", "round.digits must be a non-null integer",
        select("decimal", op("round", value=F("total", "decimal"), digits=N("integer")), nullable=True)),

    # --- contexts and aggregates --------------------------------------------
    ("aggregate_in_where", "Aggregate inside where (old ambiguity B1)",
        where(op("greaterThan", left=agg("sum", "all", selector=F("total", "decimal")), right=L("integer", 5)))),
    ("aggregate_in_join_on", "Aggregate inside join.on (old ambiguity B1)",
        q(plain, joins=[{"type": "inner", "entity": "users",
                         "on": op("greaterThan", left=F("score", "integer", "users"), right=agg("count", "all"))}])),
    ("aggregate_in_group_key", "Aggregate as a groupBy key",
        q(grouped, groupBy=[{"expression": agg("count", "all")}])),
    ("over_group_in_plain_query", "over: group in a query without groupBy", select("integer", agg("count", "group"))),
    ("aggregate_without_over", "Aggregate without over", select("integer", op("count"), grouped)),
    ("unknown_over_value", "over: window", select("integer", agg("count", "window"), grouped)),
    ("count_with_selector", "count does not take a selector",
        select("integer", agg("count", selector=F("id", "uuid")), grouped)),
    ("any_without_predicate", "any without a predicate", select("boolean", agg("any"), grouped)),
    ("predicate_not_boolean", "Aggregate predicate is a decimal",
        select("integer", agg("count", predicate=F("total", "decimal")), grouped)),
    ("nullable_aggregate_predicate", "Nullable boolean as an aggregate predicate",
        select("boolean", agg("any", predicate=nullable_flag), grouped)),
    ("nested_aggregate", "Aggregate inside an aggregate selector (old ambiguity B2)",
        select("decimal", agg("sum", selector=agg("sum", selector=F("total", "decimal"))), grouped)),
    ("sum_of_string", "sum over a string selector", select("decimal", agg("sum", selector=F("status", "string")), grouped)),
    ("sum_of_boolean", "sum over a boolean selector",
        select("decimal", agg("sum", selector=F("is_paid", "boolean")), grouped)),
    ("min_of_uuid", "min over a uuid selector", select("uuid", agg("min", selector=F("id", "uuid")), grouped)),
    ("average_of_string", "average over a string selector",
        select("decimal", agg("average", selector=F("status", "string")), grouped)),
    ("average_as_integer", "average (always decimal) used where integer days are required",
        select("date", op("dateAddDays", left=agg("max", selector=F("order_date", "date")),
                          right=agg("average", selector=F("quantity", "integer"))), grouped)),

    # --- grouping and keys --------------------------------------------------
    ("having_without_group_by", "having without groupBy",
        q(plain, having=op("greaterThan", left=agg("count", "all"), right=L("integer", 1)))),
    ("field_in_having", "Bare field in having (group context has no fields)", having(eq_status)),
    ("column_as_and_conditions", "and.conditions given a row predicate instead of an array (old hole A1)",
        having(op("and", conditions=eq_status))),
    ("column_equality_in_having", "equal(field, field) in having (old hole A2)",
        having(op("equal", left=F("a", "decimal"), right=F("b", "decimal")))),
    ("having_not_boolean", "having is a count", having(count)),
    ("bare_field_in_grouped_select", "Non-key field in grouped select",
        q(grouped, select=[col("uuid", key0, "user_id"), col("string", F("status", "string"), "status")])),
    ("field_in_grouped_order_by", "Field as grouped orderBy key",
        q(grouped, orderBy=[{"expression": F("total", "decimal")}])),
    ("key_in_plain_query", "Group key reference in a query without groupBy", select("uuid", key0)),
    ("key_in_where", "Group key reference in where", q(grouped, where=op("equal", left=key0, right=key0))),
    ("key_in_group_by", "Group key reference inside groupBy itself", q(grouped, groupBy=[{"expression": key0}])),
    ("key_in_aggregate_selector", "Group key inside an aggregate selector (row context)",
        select("integer", agg("sum", selector={"key": 0, "type": T("integer")}), grouped)),
    ("negative_key_index", "Group key with a negative index",
        q(grouped, select=[col("uuid", {"key": -1, "type": T("uuid")}, "user_id")])),
    ("nullable_key_as_having", "Nullable boolean group key as the having condition",
        having({"key": 0, "type": T("boolean", True)})),

    # --- typed select columns -----------------------------------------------
    ("column_without_type", "Select column without a declared type",
        q(plain, select=[{"alias": "id", "expression": F("id", "uuid")}])),
    ("column_without_alias", "Select column without an alias",
        q(plain, select=[{"type": T("uuid"), "expression": F("id", "uuid")}])),
    ("column_empty_alias", "Select column with an empty alias", q(plain, select=[col("uuid", F("id", "uuid"), "")])),
    ("column_type_mismatch", "Column declared string, expression is decimal", select("string", F("total", "decimal"))),
    ("column_type_too_narrow", "Column declared integer, expression is decimal (divide)",
        select("integer", op("divide", values=[F("quantity", "integer"), L("integer", 2)]))),
    ("column_non_null_for_nullable", "Column declared non-null string, expression is a nullable field",
        select("string", F("coupon_code", "string", nullable=True))),
    ("column_non_null_for_nullable_aggregate", "Column declared non-null, but min over all rows is nullable",
        select("decimal", agg("min", "all", selector=F("total", "decimal")))),
    ("column_non_null_for_filtered_aggregate", "Column declared non-null, but a filtered min over a group is nullable",
        select("decimal", agg("min", selector=F("total", "decimal"), predicate=F("is_paid", "boolean")), grouped)),
    ("column_list_type", "Column declared as a list type",
        q(plain, select=[{"alias": "ids", "type": T("uuidList"), "expression": F("id", "uuid")}])),

    # --- subqueries ---------------------------------------------------------
    ("subqueries_not_array", "subqueries given an object", q(plain, subqueries=subquery)),
    ("empty_subqueries", "subqueries with no entries", q(plain, subqueries=[])),
    ("subquery_without_name", "Subquery entry without a name", q(plain, subqueries=[{"query": plain}])),
    ("subquery_without_query", "Subquery entry without a query", q(plain, subqueries=[{"name": "recent"}])),
    ("nested_subqueries", "A subquery declaring its own subqueries (only the main query may)",
        q(plain, subqueries=[{"name": "a", "query": q(plain, subqueries=[{"name": "b", "query": plain}])}])),
    ("subquery_column_without_type", "A subquery's select column without a declared type",
        q(plain, subqueries=[{"name": "recent", "query": q(plain, select=[{"alias": "id", "expression": F("id", "uuid")}])}])),
    ("invalid_grouped_subquery", "A grouped subquery with a field in having",
        q(plain, subqueries=[{"name": "per_user", "query": having(eq_status)}])),
    ("from_entity_and_subquery", "from naming both an entity and a subquery",
        q(plain, **{"from": {"entity": "orders", "subquery": "recent"}})),
    ("from_without_source", "from with only an alias", q(plain, **{"from": {"alias": "o"}})),
    ("join_without_source", "join with neither entity nor subquery",
        q(plain, joins=[{"type": "inner", "alias": "u", "on": L("boolean", True)}])),
    ("in_subquery_column_without_type", "in over a subquery column without a type",
        where(op("in", value=F("user_id", "uuid"), list={"subquery": "vip_users", "field": "id"}))),
    ("in_subquery_column_type", "in(uuid field, string column of a subquery)",
        where(op("in", value=F("user_id", "uuid"), list={"subquery": "vip_users", "field": "id", "type": T("string")}))),
]

out = Path(__file__).parent / "tests" / "invalid"
names = [name for name, _, _ in CASES]
assert len(names) == len(set(names)), "duplicate case names"
for old in out.glob("*.json"):
    old.unlink()
for i, (name, description, query) in enumerate(CASES, 1):
    (out / f"{i:03d}_{name}.json").write_text(dumps({"description": description, "query": query}) + "\n")
print(f"{len(CASES)} invalid cases written")
