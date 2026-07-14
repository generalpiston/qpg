from __future__ import annotations

import json
import sqlite3

import pytest

from qpg.db_pg import PostgresDependencyError, connect_pg
from qpg.db_sqlite import ensure_schema
from qpg.row_query import execute_row_query
from qpg.schema.privilege_check import check_privileges
from qpg.sources import add_source


def _row_query_db(dsn: str) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    source = add_source(conn, "work", dsn)
    conn.execute(
        "INSERT INTO db_objects(id, source_id, schema_name, object_name, object_type, fqname) "
        "VALUES (?, ?, 'public', 'qpg_harness_keys', 'table', 'public.qpg_harness_keys')",
        ("keys-table", source.id),
    )
    conn.executemany(
        "INSERT INTO columns(object_id, column_name, data_type, is_nullable, ordinal_position) VALUES (?, ?, ?, ?, ?)",
        [
            ("keys-table", "id", "bigint", 0, 1),
            ("keys-table", "created_at", "timestamp with time zone", 0, 2),
        ],
    )
    conn.execute(
        "INSERT INTO indexes(object_id, index_name, is_primary, columns_json) VALUES (?, ?, 1, ?)",
        ("keys-table", "qpg_harness_keys_pkey", json.dumps(["id"])),
    )
    conn.execute(
        "INSERT INTO db_objects(id, source_id, schema_name, object_name, object_type, fqname) "
        "VALUES (?, ?, 'public', 'qpg_harness_orders', 'table', 'public.qpg_harness_orders')",
        ("orders-table", source.id),
    )
    conn.executemany(
        "INSERT INTO columns(object_id, column_name, data_type, is_nullable, ordinal_position) VALUES (?, ?, ?, ?, ?)",
        [
            ("orders-table", "id", "bigint", 0, 1),
            ("orders-table", "status", "text", 1, 2),
        ],
    )
    conn.execute(
        "INSERT INTO indexes(object_id, index_name, is_primary, columns_json) VALUES (?, ?, 1, ?)",
        ("orders-table", "qpg_harness_orders_pkey", json.dumps(["id"])),
    )
    conn.commit()
    return conn


@pytest.mark.integration
def test_select_only_role_passes(integration_dsns: dict[str, str]) -> None:
    try:
        with connect_pg(integration_dsns["readonly"]) as conn:
            report = check_privileges(conn)
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))

    assert report.passed is True


@pytest.mark.integration
def test_role_with_insert_privilege_fails(integration_dsns: dict[str, str]) -> None:
    try:
        with connect_pg(integration_dsns["writer"]) as conn:
            report = check_privileges(conn)
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))

    assert report.passed is False
    assert any(v.privilege in {"INSERT", "UPDATE", "DELETE", "TRUNCATE"} for v in report.violations)


@pytest.mark.integration
def test_writer_role_cannot_write_when_qpg_enforces_readonly(
    integration_dsns: dict[str, str],
) -> None:
    try:
        with connect_pg(integration_dsns["writer"]) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT has_table_privilege(
                    current_user,
                    'public.qpg_harness_orders',
                    'INSERT'
                ) AS can_insert
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert bool(row["can_insert"]) is True

            with pytest.raises(Exception, match=r"read-only|ReadOnly|25006"):
                cur.execute(
                    "INSERT INTO public.qpg_harness_orders(status) VALUES ('should_fail')",
                )
    except PostgresDependencyError as exc:
        pytest.skip(str(exc))


@pytest.mark.integration
def test_bounded_row_lookup_and_keyset_page(integration_dsns: dict[str, str]) -> None:
    sqlite_conn = _row_query_db(integration_dsns["readonly"])
    try:
        with connect_pg(integration_dsns["readonly"]) as pg_conn:
            lookup = execute_row_query(
                sqlite_conn,
                pg_conn,
                {
                    "source": "work",
                    "table": "public.qpg_harness_keys",
                    "projections": [{"column": "id"}, {"column": "created_at"}],
                    "mode": "lookup",
                    "key": 2,
                },
            )
            page = execute_row_query(
                sqlite_conn,
                pg_conn,
                {
                    "source": "work",
                    "table": "public.qpg_harness_keys",
                    "projections": [{"column": "id"}],
                    "mode": "page",
                    "key": 1,
                    "limit": 2,
                },
            )
            expression = execute_row_query(
                sqlite_conn,
                pg_conn,
                {
                    "source": "work",
                    "table": "public.qpg_harness_orders",
                    "projections": [
                        {"column": "id"},
                        {"function": "left", "column": "status", "length": 8, "alias": "status_prefix"},
                    ],
                    "mode": "lookup",
                    "key": 1,
                },
            )
    finally:
        sqlite_conn.close()

    assert lookup["rows"][0]["id"] == 2
    assert lookup["preflight"]["node_types"] == ["Limit", "Index Scan"]
    assert [row["id"] for row in page["rows"]] == [2, 3]
    assert page["next_cursor"] == 3
    assert expression["rows"] == [{"id": 1, "status_prefix": "database"}]
