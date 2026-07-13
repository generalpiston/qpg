from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qpg.row_query import (
    MAX_RESPONSE_BYTES,
    RowQueryError,
    TableAccess,
    _build_sql,
    _normalize_rows,
    _plan_details,
    parse_request,
)
from qpg.sources import SourceRecord


def _access() -> TableAccess:
    return TableAccess(
        SourceRecord(1, "work", "postgresql://u@h/db", [], [], "", "", None, None),
        "id",
        "orders_pkey",
        {"id": "bigint", "status": "character varying(32)", "created_at": "timestamp with time zone"},
    )


def test_lookup_requires_key_and_explicit_columns() -> None:
    with pytest.raises(RowQueryError, match="requires key"):
        parse_request({"source": "work", "table": "public.orders", "columns": ["id"], "mode": "lookup"})
    with pytest.raises(RowQueryError, match="explicit"):
        parse_request({"source": "work", "table": "public.orders", "columns": ["*"], "mode": "page", "limit": 1})


def test_page_requires_a_bounded_limit() -> None:
    with pytest.raises(RowQueryError, match="page mode requires"):
        parse_request({"source": "work", "table": "public.orders", "columns": ["id"], "mode": "page"})
    with pytest.raises(RowQueryError, match="between 1 and 100"):
        parse_request({"source": "work", "table": "public.orders", "columns": ["id"], "mode": "page", "limit": 101})


def test_request_rejects_unknown_fields_and_lookup_limit() -> None:
    with pytest.raises(RowQueryError, match="unsupported"):
        parse_request({"source": "work", "table": "public.orders", "columns": ["id"], "mode": "page", "limit": 1, "filter": "no"})
    with pytest.raises(RowQueryError, match="does not accept"):
        parse_request({"source": "work", "table": "public.orders", "columns": ["id"], "mode": "lookup", "key": 1, "limit": 1})


def test_lookup_sql_is_primary_key_bound_and_ordered() -> None:
    request = parse_request({"source": "work", "table": "public.orders", "columns": ["id", "status"], "mode": "lookup", "key": 4})
    sql, params = _build_sql(request, _access())
    assert 'FROM "public"."orders" WHERE "id" = %s ORDER BY "id" ASC LIMIT %s' in sql
    assert params == [4, 1]


def test_page_sql_uses_exclusive_keyset_cursor() -> None:
    request = parse_request({"source": "work", "table": "public.orders", "columns": ["id"], "mode": "page", "key": 4, "limit": 10})
    sql, params = _build_sql(request, _access())
    assert 'WHERE "id" > %s ORDER BY "id" ASC LIMIT %s' in sql
    assert params == [4, 10]


def test_plan_details_accepts_postgres_json_plan_shape() -> None:
    _, plan = _plan_details([{"Plan": {"Node Type": "Limit", "Total Cost": 3.5, "Plans": [{"Node Type": "Index Scan"}]}}])
    assert plan.total_cost == 3.5
    assert plan.node_types == ("Limit", "Index Scan")


def test_normalize_rows_preserves_dict_values_and_datetime() -> None:
    request = parse_request({"source": "work", "table": "public.orders", "columns": ["id", "created_at"], "mode": "page", "limit": 1})
    rows, cursor = _normalize_rows(
        [{"id": 1, "created_at": datetime(2026, 1, 2, tzinfo=UTC), "__qpg_cursor": 1}], request
    )
    assert rows == [{"id": 1, "created_at": "2026-01-02T00:00:00+00:00"}]
    assert cursor == 1


def test_normalize_rows_rejects_oversized_result() -> None:
    request = parse_request({"source": "work", "table": "public.orders", "columns": ["status"], "mode": "page", "limit": 1})
    with pytest.raises(RowQueryError, match="response limit"):
        _normalize_rows([{"status": "x" * MAX_RESPONSE_BYTES, "__qpg_cursor": 1}], request)
