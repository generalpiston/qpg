import json
from io import StringIO
from pathlib import Path

import qpg.cli as cli_mod
from qpg.cli import _resolve_source_add_dsn
from qpg.context_usage import IndexUsageRecord
from qpg.index.build import UpdateStats
from qpg.index.vec import VectorModelNotInitializedError
from qpg.schema.introspect import IntrospectionBundle
from qpg.usage import usage_snapshot_path


def test_resolve_source_add_dsn_without_password_flag_returns_original() -> None:
    dsn = "postgresql://user@host:5432/db"
    assert _resolve_source_add_dsn(dsn, use_stdin_password=False, stdin=StringIO("ignored\n")) == dsn


def test_resolve_source_add_dsn_with_password_reads_from_stdin() -> None:
    dsn = "postgresql://user@host:5432/db"
    resolved = _resolve_source_add_dsn(dsn, use_stdin_password=True, stdin=StringIO("secret\n"))
    assert resolved.startswith("postgresql://user:secret@host:5432/db")


def test_resolve_source_add_dsn_with_password_rejects_existing_password() -> None:
    dsn = "postgresql://user:already@host:5432/db"
    try:
        _resolve_source_add_dsn(dsn, use_stdin_password=True, stdin=StringIO("secret\n"))
    except ValueError as exc:
        assert "already contains a password" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_resolve_source_add_dsn_with_password_requires_stdin_value() -> None:
    dsn = "postgresql://user@host:5432/db"
    try:
        _resolve_source_add_dsn(dsn, use_stdin_password=True, stdin=StringIO("\n"))
    except ValueError as exc:
        assert "missing password" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_source_add_auto_refreshes_index_and_usage(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    class _FakePgContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(cli_mod, "require_vector_model", lambda: tmp_path / "cache" / "qpg" / "models" / "m")
    monkeypatch.setattr(cli_mod, "connect_pg", lambda _dsn: _FakePgContext())
    monkeypatch.setattr(cli_mod, "introspect_schema", lambda _conn, include_functions: IntrospectionBundle())
    monkeypatch.setattr(cli_mod, "apply_filters", lambda bundle, **_kwargs: bundle)
    monkeypatch.setattr(
        cli_mod,
        "update_source_index",
        lambda _conn, **_kwargs: UpdateStats(objects=1, columns=0, constraints=0, indexes=0, dependencies=0, vectors=1),
    )
    monkeypatch.setattr(
        cli_mod,
        "collect_index_usage_records",
        lambda _conn, *, source_name: [
            IndexUsageRecord(
                schema="public",
                table="orders",
                index="idx_orders_created_at",
                unused_days=14.0,
                as_of="2026-02-27T00:00:00Z",
                source=source_name,
                idx_scan=0.0,
            )
        ],
    )

    code = cli_mod.main(
        [
            "source",
            "add",
            "postgresql://user@host:5432/db",
            "--name",
            "work",
            "--json",
        ]
    )
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "work"
    assert payload["auto_refreshed"] is True
    assert payload["indexed"]["objects"] == 1
    assert payload["usage_snapshot"]["records"] == 1

    snapshot = usage_snapshot_path(cli_mod.ensure_dirs(cli_mod.get_paths()), "work")
    assert payload["usage_snapshot"]["path"] == str(snapshot)
    assert snapshot.exists()


def test_source_add_is_best_effort_when_auto_refresh_fails(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def fail_require_model() -> Path:
        raise VectorModelNotInitializedError("vector model is not initialized. Run `qpg init`.")

    monkeypatch.setattr(cli_mod, "require_vector_model", fail_require_model)

    code = cli_mod.main(
        [
            "source",
            "add",
            "postgresql://user@host:5432/db",
            "--name",
            "work",
            "--json",
        ]
    )
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["name"] == "work"
    assert payload["auto_refreshed"] is False
    assert "auto_refresh_error" in payload
    assert "qpg init" in payload["auto_refresh_error"]
