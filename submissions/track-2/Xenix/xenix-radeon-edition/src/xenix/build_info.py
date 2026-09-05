from __future__ import annotations

from pathlib import Path
import tomllib

from .release_config import load_release_config

DEVELOPMENT_BUILD_COMMIT = "development"


def _development_version() -> str:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
        return str(project["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return "0.0.0"

try:
    from ._generated_build_info import APP_VERSION, BUILD_COMMIT as _RAW_BUILD_COMMIT
except ModuleNotFoundError as exc:
    if exc.name != "xenix._generated_build_info":
        raise
    _RAW_BUILD_COMMIT = DEVELOPMENT_BUILD_COMMIT
    APP_VERSION = _development_version()

APP_UPDATE_FEED_URL = load_release_config().update_feed_url


def _normalize_build_commit(value: object) -> str:
    if not isinstance(value, str):
        return DEVELOPMENT_BUILD_COMMIT
    cleaned = value.strip()
    return cleaned or DEVELOPMENT_BUILD_COMMIT


def _display_build_commit(value: str) -> str:
    if value == DEVELOPMENT_BUILD_COMMIT:
        return value
    return value[:12]


BUILD_COMMIT = _normalize_build_commit(_RAW_BUILD_COMMIT)
BUILD_COMMIT_DISPLAY = _display_build_commit(BUILD_COMMIT)
