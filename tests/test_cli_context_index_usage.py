from __future__ import annotations

import io
from pathlib import Path

import qpg.cli as cli_mod
from qpg.context_usage import INDEX_USAGE_MANAGED_PREFIX
from qpg.db_sqlite import connect_sqlite, ensure_schema


def _prepare_index_with_indexes(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    db_path = cache / "qpg" / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = connect_sqlite(db_path)
    ensure_schema(conn)
    try:
        conn.execute("INSERT INTO sources(name, dsn) VALUES(?, ?)", ("work", "postgresql://u@h/work"))
        source_id = conn.execute("SELECT id FROM sources WHERE name = 'work'").fetchone()["id"]
        conn.executemany(
            """
            INSERT INTO db_objects(
                id, source_id, schema_name, object_name, object_type, fqname, definition, comment, signature, owner, is_system
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "idx_orders_created_at_id",
                    source_id,
                    "public",
                    "orders.idx_orders_created_at",
                    "index",
                    "public.orders.idx_orders_created_at",
                    "CREATE INDEX idx_orders_created_at ON public.orders(created_at)",
                    None,
                    "in public.orders",
                    None,
                    0,
                ),
                (
                    "idx_orders_status_id",
                    source_id,
                    "public",
                    "orders.idx_orders_status",
                    "index",
                    "public.orders.idx_orders_status",
                    "CREATE INDEX idx_orders_status ON public.orders(status)",
                    None,
                    "in public.orders",
                    None,
                    0,
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_context_generate_index_usage_from_stdin(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = _prepare_index_with_indexes(tmp_path)

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"schema":"public","table":"orders","index":"idx_orders_created_at",'
            '"unused_days":17,"as_of":"2026-02-27T00:00:00Z"}\n'
        ),
    )

    code = cli_mod.main(
        [
            "context",
            "generate",
            "--from",
            "index-usage",
            "--source",
            "work",
            "--unused-days",
            "14",
            "--input",
            "-",
        ]
    )
    assert code == 0

    conn = connect_sqlite(db_path)
    try:
        row = conn.execute("SELECT target_uri, body FROM contexts").fetchone()
        assert row is not None
        assert row["target_uri"] == "qpg://work#idx_orders_created_at_id"
        assert INDEX_USAGE_MANAGED_PREFIX in row["body"]
        assert "unused for 17 days as of 2026-02-27T00:00:00Z" in row["body"]
    finally:
        conn.close()


def test_context_generate_index_usage_skips_below_threshold(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = _prepare_index_with_indexes(tmp_path)

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"schema":"public","table":"orders","index":"idx_orders_created_at","unused_days":3}\n'),
    )

    code = cli_mod.main(
        [
            "context",
            "generate",
            "--from",
            "index-usage",
            "--source",
            "work",
            "--unused-days",
            "14",
            "--input",
            "-",
        ]
    )
    assert code == 0

    conn = connect_sqlite(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM contexts").fetchone()["c"]
        assert count == 0
    finally:
        conn.close()


def test_context_generate_index_usage_replace_managed_preserves_manual(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = _prepare_index_with_indexes(tmp_path)

    conn = connect_sqlite(db_path)
    ensure_schema(conn)
    try:
        conn.execute(
            "INSERT INTO contexts(target_uri, body) VALUES(?, ?)",
            ("qpg://work#idx_orders_created_at_id", f"{INDEX_USAGE_MANAGED_PREFIX}\nstale"),
        )
        conn.execute(
            "INSERT INTO contexts(target_uri, body) VALUES(?, ?)",
            ("qpg://work#idx_orders_created_at_id", "manual note about this index"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code = cli_mod.main(
        [
            "context",
            "generate",
            "--from",
            "index-usage",
            "--source",
            "work",
            "--replace-managed",
            "--input",
            "-",
        ]
    )
    assert code == 0

    conn = connect_sqlite(db_path)
    try:
        rows = conn.execute("SELECT target_uri, body FROM contexts ORDER BY id").fetchall()
        assert len(rows) == 1
        assert rows[0]["target_uri"] == "qpg://work#idx_orders_created_at_id"
        assert rows[0]["body"] == "manual note about this index"
    finally:
        conn.close()


def test_context_generate_index_usage_rejects_invalid_input(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _prepare_index_with_indexes(tmp_path)

    monkeypatch.setattr("sys.stdin", io.StringIO("{not-json}\n"))
    code = cli_mod.main(["context", "generate", "--from", "index-usage", "--source", "work", "--input", "-"])

    assert code == 2
    err = capsys.readouterr().err
    assert "invalid JSON on line 1" in err
