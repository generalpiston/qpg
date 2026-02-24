from __future__ import annotations

from pathlib import Path

import qpg.cli as cli_mod
from qpg.db_sqlite import connect_sqlite, ensure_schema


def _prepare_index(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    db_path = cache / "qpg" / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(db_path)
    ensure_schema(conn)
    try:
        conn.execute("INSERT INTO sources(name, dsn) VALUES(?, ?)", ("work", "postgresql://u@h/work"))
        source_id = conn.execute("SELECT id FROM sources WHERE name = 'work'").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO db_objects(
                id, source_id, schema_name, object_name, object_type, fqname, definition, comment, signature, owner, is_system
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "obj_orders",
                source_id,
                "public",
                "orders",
                "table",
                "public.orders",
                "CREATE TABLE public.orders (...)",
                "Stores customer orders",
                None,
                None,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO columns(object_id, column_name, data_type, is_nullable, ordinal_position, default_expr, comment)
            VALUES
                (?, 'id', 'bigint', 0, 1, NULL, 'primary key'),
                (?, 'status', 'text', 0, 2, NULL, 'order state')
            """,
            ("obj_orders", "obj_orders"),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_context_generate_creates_table_target_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = _prepare_index(tmp_path)

    calls: list[str] = []

    def fake_generate(conn, candidate, *, api_key: str, model: str, base_url: str) -> str:
        assert api_key == "test-key"
        assert model == "fake-model"
        assert candidate.fqname == "public.orders"
        assert len(candidate.columns) == 2
        calls.append(candidate.target_uri)
        return "Tracks customer order lifecycle and status transitions."

    monkeypatch.setattr(cli_mod, "generate_table_context_text", fake_generate)

    code = cli_mod.main(
        [
            "context",
            "generate",
            "--source",
            "work",
            "--api-key",
            "test-key",
            "--model",
            "fake-model",
        ]
    )
    assert code == 0
    assert calls == ["qpg://work/public.orders"]

    conn = connect_sqlite(db_path)
    try:
        row = conn.execute("SELECT target_uri, body FROM contexts").fetchone()
        assert row is not None
        assert row["target_uri"] == "qpg://work/public.orders"
        assert row["body"] == "Tracks customer order lifecycle and status transitions."
    finally:
        conn.close()


def test_context_generate_reads_api_key_and_model_from_settings_env(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("QPG_OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("QPG_OPENAI_MODEL", "env-model")
    monkeypatch.setenv("QPG_OPENAI_BASE_URL", "https://example.test/v1")
    _prepare_index(tmp_path)

    calls: list[tuple[str, str, str]] = []

    def fake_generate(conn, candidate, *, api_key: str, model: str, base_url: str) -> str:
        calls.append((api_key, model, base_url))
        return "generated from env settings"

    monkeypatch.setattr(cli_mod, "generate_table_context_text", fake_generate)

    code = cli_mod.main(["context", "generate", "--source", "work"])
    assert code == 0
    assert calls == [("env-key", "env-model", "https://example.test/v1")]


def test_context_generate_reads_settings_from_yaml_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("QPG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("QPG_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("QPG_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    cfg = tmp_path / "config" / "qpg" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        (
            "openai_api_key: yaml-key\n"
            "openai_model: yaml-model\n"
            "openai_base_url: https://yaml.example.test/v1\n"
        ),
    )
    _prepare_index(tmp_path)

    calls: list[tuple[str, str, str]] = []

    def fake_generate(conn, candidate, *, api_key: str, model: str, base_url: str) -> str:
        calls.append((api_key, model, base_url))
        return "generated from yaml settings"

    monkeypatch.setattr(cli_mod, "generate_table_context_text", fake_generate)

    code = cli_mod.main(["context", "generate", "--source", "work"])
    assert code == 0
    assert calls == [("yaml-key", "yaml-model", "https://yaml.example.test/v1")]


def test_context_generate_skips_existing_unless_overwrite(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = _prepare_index(tmp_path)

    conn = connect_sqlite(db_path)
    ensure_schema(conn)
    try:
        conn.execute(
            "INSERT INTO contexts(target_uri, body) VALUES(?, ?)",
            ("qpg://work/public.orders", "existing context"),
        )
        conn.commit()
    finally:
        conn.close()

    calls = 0

    def fake_generate(conn, candidate, *, api_key: str, model: str, base_url: str) -> str:
        nonlocal calls
        calls += 1
        return "new context"

    monkeypatch.setattr(cli_mod, "generate_table_context_text", fake_generate)

    code = cli_mod.main(
        ["context", "generate", "--source", "work", "--api-key", "test-key", "--model", "fake-model"]
    )
    assert code == 0
    assert calls == 0

    conn = connect_sqlite(db_path)
    try:
        body = conn.execute("SELECT body FROM contexts WHERE target_uri = ?", ("qpg://work/public.orders",)).fetchone()[
            "body"
        ]
        assert body == "existing context"
    finally:
        conn.close()

    code = cli_mod.main(
        [
            "context",
            "generate",
            "--source",
            "work",
            "--api-key",
            "test-key",
            "--model",
            "fake-model",
            "--overwrite",
        ]
    )
    assert code == 0
    assert calls == 1

    conn = connect_sqlite(db_path)
    try:
        row = conn.execute(
            "SELECT body FROM contexts WHERE target_uri = ?",
            ("qpg://work/public.orders",),
        ).fetchone()
        assert row is not None
        assert row["body"] == "new context"
    finally:
        conn.close()


def test_context_generate_skips_when_no_reasonable_inference(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    db_path = _prepare_index(tmp_path)

    def fake_generate(conn, candidate, *, api_key: str, model: str, base_url: str):
        return None

    monkeypatch.setattr(cli_mod, "generate_table_context_text", fake_generate)

    code = cli_mod.main(
        [
            "context",
            "generate",
            "--source",
            "work",
            "--api-key",
            "test-key",
            "--model",
            "fake-model",
        ]
    )
    assert code == 0

    out = capsys.readouterr().out
    assert "skipped inference: qpg://work/public.orders" in out
    assert "skipped_inference=1" in out

    conn = connect_sqlite(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM contexts").fetchone()["c"]
        assert count == 0
    finally:
        conn.close()


def test_context_list_does_not_require_http_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    code = cli_mod.main(["context", "list"])
    assert code == 0
