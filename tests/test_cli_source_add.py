from io import StringIO

from qpg.cli import _resolve_source_add_dsn


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
