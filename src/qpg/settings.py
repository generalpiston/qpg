from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


def config_yaml_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser().resolve() / "qpg" / "config.yaml"
    return (Path.home() / ".config" / "qpg" / "config.yaml").expanduser().resolve()


def _looks_like_dotenv(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            return "=" in line and ":" not in line.split("=", 1)[0]
    except OSError:
        return False
    return False


class QPGSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QPG_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("QPG_OPENAI_BASE_URL", "OPENAI_BASE_URL"),
    )
    openai_model: str = Field(
        default="gpt-5-nano",
        validation_alias=AliasChoices("QPG_OPENAI_MODEL", "OPENAI_MODEL"),
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_path = config_yaml_path()
        if _looks_like_dotenv(yaml_path):
            file_config_settings: PydanticBaseSettingsSource = DotEnvSettingsSource(
                settings_cls,
                env_file=yaml_path,
            )
        else:
            file_config_settings = YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path)
        return (
            file_secret_settings,
            file_config_settings,
            dotenv_settings,
            env_settings,
            init_settings,
        )


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str | None
    base_url: str
    model: str


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _env_value(*names: str) -> str | None:
    for name in names:
        value = _clean_optional(os.environ.get(name))
        if value:
            return value
    return None


def resolve_openai_settings(
    *,
    api_key_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
) -> OpenAISettings:
    base = QPGSettings()
    api_key = (
        _clean_optional(api_key_override)
        or _env_value("QPG_OPENAI_API_KEY", "OPENAI_API_KEY")
        or _clean_optional(base.openai_api_key)
    )
    base_url = (
        _clean_optional(base_url_override)
        or _env_value("QPG_OPENAI_BASE_URL", "OPENAI_BASE_URL")
        or base.openai_base_url
    )
    model = (
        _clean_optional(model_override)
        or _env_value("QPG_OPENAI_MODEL", "OPENAI_MODEL")
        or base.openai_model
    )
    return OpenAISettings(api_key=api_key, base_url=base_url, model=model)
