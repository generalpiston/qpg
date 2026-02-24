from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import qpg.cli as cli_mod


def test_mcp_startup_refresh_logs_source_errors_and_continues(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def fake_connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=check_same_thread)
        conn.row_factory = sqlite3.Row
        return conn

    def fake_ensure_schema(conn: sqlite3.Connection) -> bool:
        conn.execute("CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS db_objects (id TEXT PRIMARY KEY, object_type TEXT)")
        conn.commit()
        return True

    monkeypatch.setattr(cli_mod, "connect_sqlite", fake_connect)
    monkeypatch.setattr(cli_mod, "ensure_schema", fake_ensure_schema)
    monkeypatch.setattr(
        cli_mod,
        "update_sources",
        lambda _conn, **_kwargs: {
            "source_count": 1,
            "results": [
                {
                    "source": "work",
                    "ok": False,
                    "warnings": ["skipped one function"],
                    "indexed": None,
                    "usage_snapshot": None,
                    "error": "failed introspection: connection refused",
                }
            ],
            "exit_code": 4,
        },
    )
    monkeypatch.setattr(cli_mod, "serve_stdio", lambda _conn, enable_update_tool=False: 0)

    def run_refresh_inline() -> None:
        conn = cli_mod._with_db(check_same_thread=False)
        try:
            cli_mod._run_mcp_startup_refresh(conn)
        finally:
            conn.close()

    monkeypatch.setattr(cli_mod, "_start_mcp_startup_refresh", run_refresh_inline)

    code = cli_mod.cmd_mcp(
        argparse.Namespace(
            http=False,
            daemon=False,
            enable_update_tool=False,
            host="127.0.0.1",
            port=8765,
            mcp_cmd=None,
        )
    )

    assert code == 0
    err = capsys.readouterr().err
    assert "source 'work' refresh warning: skipped one function" in err
    assert "source 'work' refresh failed: failed introspection: connection refused" in err


def test_mcp_startup_refresh_ignores_missing_sources(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    monkeypatch.setattr(
        cli_mod,
        "update_sources",
        lambda _conn, **_kwargs: (_ for _ in ()).throw(cli_mod.NoSourcesConfiguredError()),
    )
    monkeypatch.setattr(cli_mod, "serve_stdio", lambda _conn, enable_update_tool=False: 0)

    def run_refresh_inline() -> None:
        cli_mod._best_effort_mcp_startup_refresh()

    monkeypatch.setattr(cli_mod, "_start_mcp_startup_refresh", run_refresh_inline)

    code = cli_mod.main(["mcp"])
    assert code == 0


def test_mcp_startup_refresh_logs_exceptions_and_continues(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    monkeypatch.setattr(
        cli_mod,
        "update_sources",
        lambda _conn, **_kwargs: (_ for _ in ()).throw(RuntimeError("db offline")),
    )
    monkeypatch.setattr(cli_mod, "serve_stdio", lambda _conn, enable_update_tool=False: 0)

    def run_refresh_inline() -> None:
        cli_mod._best_effort_mcp_startup_refresh()

    monkeypatch.setattr(cli_mod, "_start_mcp_startup_refresh", run_refresh_inline)

    code = cli_mod.main(["mcp"])

    assert code == 0
    assert "warning: MCP startup source refresh failed: db offline" in capsys.readouterr().err


def test_mcp_startup_refresh_uses_same_update_defaults(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    captured: dict[str, object] = {}

    def fake_update_sources(_conn, **kwargs):
        captured.update(kwargs)
        return {"source_count": 0, "results": [], "exit_code": 0}

    monkeypatch.setattr(cli_mod, "update_sources", fake_update_sources)
    monkeypatch.setattr(cli_mod, "serve_stdio", lambda _conn, enable_update_tool=False: 0)

    def run_refresh_inline() -> None:
        cli_mod._best_effort_mcp_startup_refresh()

    monkeypatch.setattr(cli_mod, "_start_mcp_startup_refresh", run_refresh_inline)

    code = cli_mod.main(["mcp"])

    assert code == 0
    assert captured == {}


def test_mcp_starts_serving_without_waiting_for_startup_refresh(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    entered: dict[str, bool] = {"serve_stdio": False, "refresh_started": False}

    def fake_start_refresh():
        entered["refresh_started"] = True

    def fake_serve_stdio(_conn, enable_update_tool=False):
        assert entered["refresh_started"] is True
        entered["serve_stdio"] = True
        return 0

    monkeypatch.setattr(cli_mod, "_start_mcp_startup_refresh", fake_start_refresh)
    monkeypatch.setattr(cli_mod, "serve_stdio", fake_serve_stdio)

    code = cli_mod.main(["mcp"])

    assert code == 0
    assert entered["serve_stdio"] is True
