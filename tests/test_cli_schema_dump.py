from __future__ import annotations

from pathlib import Path

from qpg.cli import main
from qpg.db_sqlite import connect_sqlite, ensure_schema


def test_schema_command_prints_entire_table_definition(
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
                "Stores incoming events",
                None,
                None,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO columns(object_id, column_name, data_type, is_nullable, ordinal_position)
            VALUES
                (?, 'id', 'bigint', 0, 1),
                (?, 'payload', 'jsonb', 1, 2)
            """,
            ("obj_event_data", "obj_event_data"),
        )
        conn.commit()
    finally:
        conn.close()

    code = main(["schema", "--source", "datadb"])
    assert code == 0

    out = capsys.readouterr().out
    assert "== source: datadb ==" in out
    assert "-- public.event_data (table)" in out
    assert "-- Stores incoming events" in out
    assert "CREATE TABLE public.event_data" in out
    assert "id bigint NOT NULL" in out
    assert "payload jsonb" in out
