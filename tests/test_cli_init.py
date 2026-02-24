from __future__ import annotations

from pathlib import Path

import qpg.cli as cli_mod


def test_init_command_calls_model_init(monkeypatch, capsys, tmp_path: Path) -> None:
    model_path = tmp_path / "cache" / "qpg" / "models" / "microsoft__codebert-base"

    def fake_init_vector_model() -> Path:
        return model_path

    monkeypatch.setattr(cli_mod, "init_vector_model", fake_init_vector_model)

    code = cli_mod.main(["init"])
    assert code == 0
    out = capsys.readouterr().out
    assert str(model_path) in out
