from __future__ import annotations

from pathlib import Path

from qpg.cli import main


def test_update_unknown_source_returns_clean_error(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    code = main(["update", "--source", "data_db"])
    assert code == 2

    captured = capsys.readouterr()
    assert "source 'data_db' not found" in captured.err
    assert "Traceback" not in captured.err
