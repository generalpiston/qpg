from __future__ import annotations

import sqlite3

from qpg.db_sqlite import ensure_schema
from qpg.schema.introspect import IntrospectedObject, IntrospectionBundle, apply_filters
from qpg.sources import add_source, get_source


def test_add_source_persists_schema_and_skip_filters() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    try:
        add_source(
            conn,
            "work",
            "postgresql://user@host:5432/db",
            include_schemas=["public", "analytics"],
            skip_patterns=["*.tmp_*", "analytics.old_*"],
        )
        source = get_source(conn, "work")
        assert source.include_schemas == ["analytics", "public"]
        assert source.skip_patterns == ["*.tmp_*", "analytics.old_*"]
    finally:
        conn.close()


def test_apply_filters_limits_schema_and_skip_patterns() -> None:
    bundle = IntrospectionBundle(
        objects=[
            IntrospectedObject("public", "orders", "table", None, None),
            IntrospectedObject("public", "tmp_orders", "table", None, None),
            IntrospectedObject("analytics", "events", "table", None, None),
        ]
    )

    filtered = apply_filters(
        bundle,
        include_schemas=["public"],
        skip_patterns=["public.tmp_*"],
    )

    names = [obj.fqname for obj in filtered.objects]
    assert names == ["public.orders"]
