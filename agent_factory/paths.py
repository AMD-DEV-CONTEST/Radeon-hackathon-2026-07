from __future__ import annotations

import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath


PROJECT_ROOT_ENV = "AGENTFACTORY_PROJECT_ROOT"
SYSTEM_PACKAGE_ROOT_ENV = "AGENTFACTORY_SYSTEM_PACKAGE_ROOT"


def cross_platform_absolute_path(value: str) -> PurePath | None:
    for path_type in (PurePosixPath, PureWindowsPath):
        path = path_type(value)
        if path.is_absolute():
            return path
    return None


def project_root() -> Path:
    configured = os.getenv(PROJECT_ROOT_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "agent_factory").is_dir():
            return candidate
    return current


def resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return project_root() / path


def factory_artifact_root() -> Path:
    return project_root() / ".agentfactory"


def factory_artifact_path(*parts: str) -> Path:
    return factory_artifact_root().joinpath(*parts)


def system_package_root() -> Path:
    configured = os.getenv(SYSTEM_PACKAGE_ROOT_ENV)
    if configured:
        return resolve_project_path(configured).resolve()
    return project_root() / "SystemPackage"
