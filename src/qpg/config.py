from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "qpg"
INDEX_FILENAME = "index.sqlite"
MCP_PID_FILENAME = "mcp-http.pid"


@dataclass(frozen=True)
class Paths:
    cache_dir: Path
    state_dir: Path
    index_db: Path
    models_dir: Path
    mcp_pid_file: Path


def _xdg_or_default(env_name: str, default: Path) -> Path:
    value = os.environ.get(env_name)
    if value:
        return Path(value).expanduser().resolve()
    return default.expanduser().resolve()


def get_paths() -> Paths:
    home = Path.home()
    cache_home = _xdg_or_default("XDG_CACHE_HOME", home / ".cache")
    state_home = _xdg_or_default("XDG_STATE_HOME", home / ".local" / "state")
    cache_dir = cache_home / APP_NAME
    state_dir = state_home / APP_NAME
    return Paths(
        cache_dir=cache_dir,
        state_dir=state_dir,
        index_db=cache_dir / INDEX_FILENAME,
        models_dir=cache_dir / "models",
        mcp_pid_file=state_dir / MCP_PID_FILENAME,
    )


def ensure_dirs(paths: Paths | None = None) -> Paths:
    resolved = paths or get_paths()
    resolved.cache_dir.mkdir(parents=True, exist_ok=True)
    resolved.state_dir.mkdir(parents=True, exist_ok=True)
    resolved.models_dir.mkdir(parents=True, exist_ok=True)
    return resolved
