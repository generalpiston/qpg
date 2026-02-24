from __future__ import annotations

import json
from pathlib import Path

import qpg.cli as cli_mod
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


def test_usage_refresh_writes_snapshot(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _prepare_sources(tmp_path)

    class _FakePgContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def fake_connect_pg(dsn: str):
        assert dsn == "postgresql://u@h/work"
        return _FakePgContext()

    def fake_collect_index_usage_records(pg_conn, *, source_name: str):
        assert source_name == "work"
        return [
            IndexUsageRecord(
                schema="public",
                table="orders",
                index="idx_orders_created_at",
                unused_days=21.0,
                as_of="2026-02-27T00:00:00Z",
                source="work",
                idx_scan=0.0,
            )
        ]

    monkeypatch.setattr(cli_mod, "connect_pg", fake_connect_pg)
    monkeypatch.setattr(cli_mod, "collect_index_usage_records", fake_collect_index_usage_records)

    code = cli_mod.main(["usage", "refresh", "--source", "work", "--json"])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "work"
    assert payload["records"] == 1

    snapshot = usage_snapshot_path(ensure_dirs(get_paths()), "work")
    assert payload["path"] == str(snapshot)
    assert snapshot.exists()

    rows = [json.loads(line) for line in snapshot.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows == [
        {
            "as_of": "2026-02-27T00:00:00Z",
            "idx_scan": 0.0,
            "index": "idx_orders_created_at",
            "schema": "public",
            "source": "work",
            "table": "orders",
            "unused_days": 21.0,
        }
    ]


def test_update_also_refreshes_usage_snapshot(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _prepare_sources(tmp_path)

    class _FakePgContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(update_mod, "require_vector_model", lambda: tmp_path / "cache" / "qpg" / "models" / "m")
    monkeypatch.setattr(update_mod, "connect_pg", lambda _dsn, **_kwargs: _FakePgContext())
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

    code = cli_mod.main(["update", "--source", "work"])
    assert code == 0

    out = capsys.readouterr().out
    assert "usage snapshot refreshed: work records=1" in out

    snapshot = usage_snapshot_path(ensure_dirs(get_paths()), "work")
    assert snapshot.exists()
