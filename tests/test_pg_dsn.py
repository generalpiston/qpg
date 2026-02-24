import sqlite3
from urllib.parse import parse_qsl, urlsplit

from qpg.db_sqlite import ensure_schema
from qpg.sources import add_source, get_source
from qpg.util.pg_dsn import dsn_has_password, dsn_with_password, enforce_readonly_dsn


def _query_pairs(dsn: str) -> dict[str, str]:
    return dict(parse_qsl(urlsplit(dsn).query, keep_blank_values=True))


def test_enforce_readonly_dsn_adds_options_param() -> None:
    dsn = "postgres://user:pass@host:5432/dbname"
    normalized = enforce_readonly_dsn(dsn)

    pairs = _query_pairs(normalized)
    assert "options" in pairs
    assert "default_transaction_read_only=on" in pairs["options"]


def test_enforce_readonly_dsn_preserves_existing_query_params() -> None:
    dsn = "postgres://user:pass@host:5432/dbname?sslmode=require"
    normalized = enforce_readonly_dsn(dsn)

    pairs = _query_pairs(normalized)
    assert pairs["sslmode"] == "require"
    assert "default_transaction_read_only=on" in pairs["options"]


def test_enforce_readonly_dsn_does_not_duplicate_when_already_on() -> None:
    dsn = (
        "postgres://user:pass@host:5432/dbname"
        "?options=-c%20default_transaction_read_only%3Don"
    )
    normalized = enforce_readonly_dsn(dsn)

    pairs = _query_pairs(normalized)
    assert pairs["options"].count("default_transaction_read_only=on") == 1


def test_add_source_stores_normalized_dsn() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    try:
        add_source(conn, "work", "postgres://user:pass@host:5432/dbname")
        source = get_source(conn, "work")
        pairs = _query_pairs(source.dsn)
        assert "default_transaction_read_only=on" in pairs["options"]
    finally:
        conn.close()


def test_add_source_accepts_passwordless_dsn() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    try:
        add_source(conn, "work", "postgres://user@host:5432/dbname")
        source = get_source(conn, "work")
        assert source.dsn.startswith("postgres://user@host:5432/dbname")
        pairs = _query_pairs(source.dsn)
        assert "default_transaction_read_only=on" in pairs["options"]
    finally:
        conn.close()


def test_dsn_has_password_detection() -> None:
    assert dsn_has_password("postgres://user:pass@host:5432/dbname") is True
    assert dsn_has_password("postgres://user@host:5432/dbname") is False


def test_dsn_with_password_sets_encoded_password() -> None:
    dsn = "postgresql://user@host:5432/dbname?sslmode=require"
    updated = dsn_with_password(dsn, "p@ss:word")
    assert updated.startswith("postgresql://user:p%40ss%3Aword@host:5432/dbname")
    assert "sslmode=require" in updated
