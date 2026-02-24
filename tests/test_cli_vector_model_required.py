from __future__ import annotations

from pathlib import Path

import pytest

import qpg.cli as cli_mod
from qpg.index.vec import VectorModelNotInitializedError


@pytest.mark.parametrize(
    "argv",
    [
        ["update"],
        ["vsearch", "orders"],
        ["query", "refund model"],
    ],
)
def test_vector_commands_require_initialized_model(
    argv: list[str],
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    if argv == ["update"]:
        assert (
            cli_mod.main(
                ["source", "add", "postgresql://user@host:5432/db", "--name", "work"]
            )
            == 0
        )
        argv = ["update", "--source", "work"]

    def fail_require_model() -> Path:
        raise VectorModelNotInitializedError("vector model is not initialized. Run `qpg init`.")

    monkeypatch.setattr(cli_mod, "require_vector_model", fail_require_model)

    code = cli_mod.main(argv)
    assert code == 2

    captured = capsys.readouterr()
    assert "qpg init" in captured.err


def test_mcp_starts_without_initialized_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    def fail_require_model() -> Path:
        raise VectorModelNotInitializedError("vector model is not initialized. Run `qpg init`.")

    monkeypatch.setattr(cli_mod, "require_vector_model", fail_require_model)
    monkeypatch.setattr(cli_mod, "serve_stdio", lambda _conn: 0)

    code = cli_mod.main(["mcp"])
    assert code == 0
