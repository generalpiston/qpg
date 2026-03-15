from __future__ import annotations

from typing import Any

import qpg.db_pg as db_pg


class _FakeCursor:
    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, _sql: str, _params: tuple[Any, ...] | None = None) -> None:
        return None


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor()

    def close(self) -> None:
        self.closed = True


def test_connect_pg_uses_short_default_connect_timeout(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    fake_conn = _FakeConn()

    def fake_connect(dsn: str, **kwargs: Any) -> _FakeConn:
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return fake_conn

    monkeypatch.setattr(db_pg.psycopg, "connect", fake_connect)
    monkeypatch.delenv("QPG_PG_CONNECT_TIMEOUT_SEC", raising=False)

    with db_pg.connect_pg("postgresql://user@host:5432/app") as conn:
        assert conn is fake_conn

    assert captured["kwargs"]["connect_timeout"] == db_pg.DEFAULT_CONNECT_TIMEOUT_SEC
    assert captured["kwargs"]["autocommit"] is True
    assert fake_conn.closed is True


def test_connect_pg_reads_configured_connect_timeout(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(_dsn: str, **kwargs: Any) -> _FakeConn:
        captured["kwargs"] = kwargs
        return _FakeConn()

    monkeypatch.setattr(db_pg.psycopg, "connect", fake_connect)
    monkeypatch.setenv("QPG_PG_CONNECT_TIMEOUT_SEC", "2")

    with db_pg.connect_pg("postgresql://user@host:5432/app"):
        pass

    assert captured["kwargs"]["connect_timeout"] == 2
