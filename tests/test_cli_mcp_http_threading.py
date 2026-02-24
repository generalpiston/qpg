from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import qpg.cli as cli_mod


def test_mcp_http_uses_thread_safe_sqlite_connection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    check_same_thread_calls: list[bool] = []

    def fake_connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
        check_same_thread_calls.append(check_same_thread)
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn

    def fake_ensure_schema(conn: sqlite3.Connection) -> bool:
        conn.execute("CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE IF NOT EXISTS db_objects (id TEXT PRIMARY KEY, object_type TEXT)")
        conn.commit()
        return True

    def fake_serve_http(conn: sqlite3.Connection, *, host: str = "127.0.0.1", port: int = 8765) -> int:
        return 0

    monkeypatch.setattr(cli_mod, "connect_sqlite", fake_connect)
    monkeypatch.setattr(cli_mod, "ensure_schema", fake_ensure_schema)
    monkeypatch.setattr(cli_mod, "require_vector_model", lambda: Path("/tmp/model"))
    monkeypatch.setattr(cli_mod, "serve_http", fake_serve_http)

    args = argparse.Namespace(http=True, daemon=False, host="127.0.0.1", port=8765, mcp_cmd=None)
    code = cli_mod.cmd_mcp(args)

    assert code == 0
    assert False in check_same_thread_calls
