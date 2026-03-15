from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from qpg.settings import resolve_pg_connect_timeout_sec
from qpg.util.pg_dsn import enforce_readonly_dsn


class PostgresDependencyError(RuntimeError):
    pass


DEFAULT_CONNECT_TIMEOUT_SEC = 1


@contextmanager
def connect_pg(
    dsn: str,
    *,
    connect_timeout_sec: int | None = None,
    statement_timeout: str = "5s",
    idle_in_transaction_timeout: str = "10s",
) -> Iterator[Any]:
    conn = psycopg.connect(
        enforce_readonly_dsn(dsn),
        autocommit=True,
        connect_timeout=resolve_pg_connect_timeout_sec(
            override=connect_timeout_sec if connect_timeout_sec is not None else None
        ),
        row_factory=dict_row,
    )
    try:
        apply_session_guards(
            conn,
            statement_timeout=statement_timeout,
            idle_in_transaction_timeout=idle_in_transaction_timeout,
        )
        yield conn
    finally:
        conn.close()


def apply_session_guards(
    conn: Any,
    *,
    statement_timeout: str = "5s",
    idle_in_transaction_timeout: str = "10s",
) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('default_transaction_read_only', 'on', false)")
        cur.execute("SELECT set_config('statement_timeout', %s, false)", (statement_timeout,))
        cur.execute(
            "SELECT set_config('idle_in_transaction_session_timeout', %s, false)",
            (idle_in_transaction_timeout,),
        )


def fetch_all(conn: Any, sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetch_one(conn: Any, sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
    return dict(row) if row is not None else None
