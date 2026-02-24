import sqlite3

from qpg.db_sqlite import ensure_schema
from qpg.get import get_object_payload


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_get_payload_schema_stability() -> None:
    conn = _db()
    try:
        conn.execute("INSERT INTO sources(name, dsn) VALUES(?, ?)", ("work", "postgresql://user@localhost/db"))
        source_id = conn.execute("SELECT id FROM sources WHERE name = 'work'").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO db_objects(
                id, source_id, schema_name, object_name, object_type, fqname, definition, comment, signature, owner, is_system
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "abc123def456",
                source_id,
                "public",
                "orders",
                "table",
                "public.orders",
                "",
                "orders table",
                None,
                "owner",
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO columns(object_id, column_name, data_type, is_nullable, ordinal_position)
            VALUES(?, ?, ?, ?, ?)
            """,
            ("abc123def456", "id", "bigint", 0, 1),
        )
        conn.commit()

        payload = get_object_payload(conn, "public.orders")
        assert set(payload.keys()) == {
            "object_id",
            "source",
            "fqname",
            "schema",
            "name",
            "kind",
            "definition",
            "comment",
            "signature",
            "owner",
            "columns",
            "constraints",
            "indexes",
            "dependencies",
            "context",
        }

        assert payload["object_id"] == "abc123def456"
        assert payload["kind"] == "table"
        assert isinstance(payload["columns"], list)
        assert set(payload["columns"][0].keys()) == {
            "name",
            "type",
            "nullable",
            "ordinal",
            "default",
            "comment",
        }
    finally:
        conn.close()
