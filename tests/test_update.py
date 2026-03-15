from __future__ import annotations

from pathlib import Path

import qpg.update as update_mod
from qpg.config import ensure_dirs, get_paths
from qpg.context_usage import IndexUsageRecord
from qpg.db_sqlite import connect_sqlite, ensure_schema
from qpg.index.build import UpdateStats
from qpg.schema.introspect import IntrospectionBundle
from qpg.usage import usage_snapshot_path


def _prepare_sources(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    db_path = cache / "qpg" / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(db_path)
    ensure_schema(conn)
    try:
        conn.execute("INSERT INTO sources(name, dsn) VALUES(?, ?)", ("work", "postgresql://u@h/work"))
        conn.commit()
    finally:
        conn.close()


def test_update_sources_propagates_fast_fail_settings_to_usage_refresh(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _prepare_sources(tmp_path)

    conn = connect_sqlite(ensure_dirs(get_paths()).index_db)
    ensure_schema(conn)

    connect_calls: list[dict[str, object]] = []

    class _FakePgContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_connect_pg(dsn: str, **kwargs):
        connect_calls.append({"dsn": dsn, **kwargs})
        return _FakePgContext()

    monkeypatch.setattr(update_mod, "require_vector_model", lambda: tmp_path / "cache" / "qpg" / "models" / "m")
    monkeypatch.setattr(update_mod, "connect_pg", fake_connect_pg)
    monkeypatch.setattr(update_mod, "list_contexts", lambda _conn: [])
    monkeypatch.setattr(update_mod, "introspect_schema", lambda _conn, include_functions: IntrospectionBundle())
    monkeypatch.setattr(update_mod, "apply_filters", lambda bundle, **_kwargs: bundle)
    monkeypatch.setattr(
        update_mod,
        "update_source_index",
        lambda _conn, **_kwargs: UpdateStats(objects=0, columns=0, constraints=0, indexes=0, dependencies=0, vectors=0),
    )
    monkeypatch.setattr(
        update_mod,
        "collect_index_usage_records",
        lambda _conn, *, source_name: [
            IndexUsageRecord(
                schema="public",
                table="orders",
                index="idx_orders_created_at",
                unused_days=30.0,
                as_of="2026-02-27T00:00:00Z",
                source=source_name,
                idx_scan=0.0,
            )
        ],
    )

    payload = update_mod.update_sources(
        conn,
        source_name="work",
        connect_timeout_sec=1,
        statement_timeout="1s",
        idle_in_transaction_timeout="1s",
    )

    assert payload["exit_code"] == 0
    assert len(connect_calls) == 2
    assert connect_calls == [
        {
            "dsn": "postgresql://u@h/work",
            "connect_timeout_sec": 1,
            "statement_timeout": "1s",
            "idle_in_transaction_timeout": "1s",
        },
        {
            "dsn": "postgresql://u@h/work",
            "connect_timeout_sec": 1,
            "statement_timeout": "1s",
            "idle_in_transaction_timeout": "1s",
        },
    ]
    assert usage_snapshot_path(ensure_dirs(get_paths()), "work").exists()
