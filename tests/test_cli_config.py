from __future__ import annotations

import json
from pathlib import Path

import qpg.cli as cli_mod


def test_config_json_redacts_api_key_and_uses_env(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("QPG_OPENAI_API_KEY", "sk-example-secret-1234")
    monkeypatch.setenv("QPG_OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("QPG_OPENAI_BASE_URL", "https://example.test/v1")

    code = cli_mod.main(["config", "--json"])
    assert code == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["config_yaml_path"] == str((tmp_path / "config" / "qpg" / "config.yaml").resolve())
    assert payload["config_yaml_exists"] is False
    assert payload["openai"]["api_key_configured"] is True
    assert payload["openai"]["api_key_redacted"] == "sk-...34"
    assert payload["openai"]["model"] == "gpt-4.1-mini"
    assert payload["openai"]["base_url"] == "https://example.test/v1"
    assert "sk-example-secret-1234" not in out


def test_config_plain_unset_key(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("QPG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    code = cli_mod.main(["config"])
    assert code == 0

    out = capsys.readouterr().out
    assert f"config_yaml: {(tmp_path / 'config' / 'qpg' / 'config.yaml').resolve()}" in out
    assert "config_yaml_exists: False" in out
    assert "openai_api_key: unset" in out
    assert "openai_model: gpt-5-nano" in out
    assert "openai_base_url: https://api.openai.com/v1" in out


def test_config_json_reads_plain_openai_env_vars(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("QPG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("QPG_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("QPG_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-only")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example-openai.test/v1")

    code = cli_mod.main(["config", "--json"])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_yaml_exists"] is False
    assert payload["openai"]["api_key_configured"] is True
    assert payload["openai"]["api_key_redacted"] == "sk-...ly"
    assert payload["openai"]["model"] == "gpt-4.1-mini"
    assert payload["openai"]["base_url"] == "https://example-openai.test/v1"


def test_config_json_reads_yaml_config_file(monkeypatch, tmp_path: Path, capsys) -> None:
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
            "openai_api_key: sk-from-yaml\n"
            "openai_model: gpt-4.1-nano\n"
            "openai_base_url: https://yaml.example.test/v1\n"
        ),
    )

    code = cli_mod.main(["config", "--json"])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_yaml_exists"] is True
    assert payload["openai"]["api_key_configured"] is True
    assert payload["openai"]["api_key_redacted"] == "sk-...ml"
    assert payload["openai"]["model"] == "gpt-4.1-nano"
    assert payload["openai"]["base_url"] == "https://yaml.example.test/v1"


def test_config_env_overrides_yaml(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    cfg = tmp_path / "config" / "qpg" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        (
            "openai_api_key: sk-from-yaml\n"
            "openai_model: gpt-4.1-nano\n"
            "openai_base_url: https://yaml.example.test/v1\n"
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example.test/v1")

    code = cli_mod.main(["config", "--json"])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_yaml_exists"] is True
    assert payload["openai"]["api_key_redacted"] == "sk-...nv"
    assert payload["openai"]["model"] == "gpt-4.1-mini"
    assert payload["openai"]["base_url"] == "https://env.example.test/v1"


def test_config_json_reads_dotenv_style_config_file(monkeypatch, tmp_path: Path, capsys) -> None:
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
            "OPENAI_API_KEY=sk-from-dotenv\n"
            "OPENAI_MODEL=gpt-4.1-mini\n"
            "OPENAI_BASE_URL=https://dotenv.example.test/v1\n"
        ),
    )

    code = cli_mod.main(["config", "--json"])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["config_yaml_exists"] is True
    assert payload["openai"]["api_key_configured"] is True
    assert payload["openai"]["api_key_redacted"] == "sk-...nv"
    assert payload["openai"]["model"] == "gpt-4.1-mini"
    assert payload["openai"]["base_url"] == "https://dotenv.example.test/v1"
