import sqlite3

from qpg.contexts import (
    ContextRecord,
    ContextSourceNotFoundError,
    ObjectRef,
    add_context,
    list_contexts,
    parse_context_target,
    resolve_effective_context,
)
from qpg.db_sqlite import ensure_schema
from qpg.sources import add_source, delete_source


def test_parse_context_target_levels() -> None:
    source_scope = parse_context_target("qpg://work")
    schema_scope = parse_context_target("qpg://work/public")
    object_scope = parse_context_target("qpg://work/public.orders")

    assert source_scope.source == "work"
    assert source_scope.schema is None

    assert schema_scope.source == "work"
    assert schema_scope.schema == "public"
    assert schema_scope.object_name is None

    assert object_scope.source == "work"
    assert object_scope.schema == "public"
    assert object_scope.object_name == "orders"


def test_context_inheritance_resolution() -> None:
    contexts = [
        ContextRecord(id=1, target_uri="qpg://work", body="global context", created_at=""),
        ContextRecord(id=2, target_uri="qpg://work/public", body="schema context", created_at=""),
        ContextRecord(id=3, target_uri="qpg://work/public.orders", body="object context", created_at=""),
        ContextRecord(id=4, target_uri="qpg://other/public.orders", body="other source", created_at=""),
    ]

    obj = ObjectRef(source="work", schema="public", object_name="orders", object_id="abc")
    effective = resolve_effective_context(contexts, obj)

    assert effective.split("\n") == ["global context", "schema context", "object context"]


def test_object_context_inherits_to_child_object_names() -> None:
    contexts = [
        ContextRecord(id=1, target_uri="qpg://work/public.orders", body="orders context", created_at=""),
    ]

    table_obj = ObjectRef(source="work", schema="public", object_name="orders", object_id="tbl")
    column_obj = ObjectRef(source="work", schema="public", object_name="orders.id", object_id="col")
    other_obj = ObjectRef(source="work", schema="public", object_name="order_items.id", object_id="col2")

    assert resolve_effective_context(contexts, table_obj) == "orders context"
    assert resolve_effective_context(contexts, column_obj) == "orders context"
    assert resolve_effective_context(contexts, other_obj) == ""


def test_add_context_rejects_unknown_source() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    try:
        try:
            add_context(conn, "qpg://missing/public.orders", "desc")
        except ContextSourceNotFoundError as exc:
            assert "source 'missing' not found" in str(exc)
        else:
            raise AssertionError("expected ContextSourceNotFoundError")
    finally:
        conn.close()


def test_delete_source_removes_contexts_for_that_source_only() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    try:
        add_source(conn, "work", "postgresql://u@h/work")
        add_source(conn, "prod", "postgresql://u@h/prod")

        add_context(conn, "qpg://work", "work source context")
        add_context(conn, "qpg://work/public.orders", "work object context")
        add_context(conn, "qpg://prod", "prod source context")

        delete_source(conn, "work")

        remaining = list_contexts(conn)
        assert len(remaining) == 1
        assert remaining[0].target_uri == "qpg://prod"
    finally:
        conn.close()
