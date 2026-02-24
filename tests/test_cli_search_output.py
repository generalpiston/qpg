from __future__ import annotations

from pathlib import Path

from qpg.cli import main
from qpg.db_sqlite import connect_sqlite, ensure_schema
from qpg.index.fts import rebuild_fts


def test_search_prints_definition_and_description(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    cache = tmp_path / "cache"
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))

    db_path = cache / "qpg" / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect_sqlite(db_path)
    ensure_schema(conn)
    try:
        conn.execute("INSERT INTO sources(name, dsn) VALUES(?, ?)", ("datadb", "postgresql://u@h/db"))
        source_id = conn.execute("SELECT id FROM sources WHERE name = ?", ("datadb",)).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO db_objects(
                id, source_id, schema_name, object_name, object_type, fqname, definition, comment, signature, owner, is_system
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "obj_event_data",
                source_id,
                "public",
                "event_data",
                "table",
                "public.event_data",
                "",
                "Stores normalized incoming event records",
                None,
                None,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO columns(object_id, column_name, data_type, is_nullable, ordinal_position, default_expr, comment)
            VALUES
                (?, 'id', 'bigint', 0, 1, NULL, NULL),
                (?, 'event_name', 'text', 0, 2, NULL, NULL)
            """,
            ("obj_event_data", "obj_event_data"),
        )
        conn.execute(
            """
            INSERT INTO lexical_docs(object_id, source_id, name_col, comment_col, defs_col, context_col)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (
                "obj_event_data",
                source_id,
                "public.event_data",
                "Stores normalized incoming event records",
                "table event_data",
                "",
            ),
        )
        rebuild_fts(conn)
        conn.commit()
    finally:
        conn.close()

    code = main(["search", "event_data", "--source", "datadb"])
    assert code == 0

    out = capsys.readouterr().out
    assert "public.event_data (table)" in out
    assert "description: Stores normalized incoming event records" in out
    assert "CREATE TABLE public.event_data" in out
    assert "event_name text NOT NULL" in out
