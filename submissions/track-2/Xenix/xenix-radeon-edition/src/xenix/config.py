from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Xenix"
APP_ORGANIZATION = "xiaoland"


@dataclass(frozen=True)
class AppPaths:
    home: Path
    config: Path
    logs: Path
    cache: Path
    state: Path
    temp: Path
    artifacts: Path
    resources: Path


def package_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "xenix"
    return Path(__file__).resolve().parent


def _default_app_home() -> Path:
    override = os.getenv("XENIX_APP_HOME")
    if override:
        return Path(override).expanduser()

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


def get_app_paths() -> AppPaths:
    home = _default_app_home()
    resolved_package_root = package_root()

    return AppPaths(
        home=home,
        config=home / "config",
        logs=home / "logs",
        cache=home / "cache",
        state=home / "state",
        temp=home / "temp",
        artifacts=home / "artifacts",
        resources=resolved_package_root / "resources",
    )


def ensure_app_dirs(paths: AppPaths | None = None) -> AppPaths:
    resolved_paths = paths or get_app_paths()
    for directory in (
        resolved_paths.home,
        resolved_paths.config,
        resolved_paths.logs,
        resolved_paths.cache,
        resolved_paths.state,
        resolved_paths.temp,
        resolved_paths.artifacts,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    return resolved_paths
