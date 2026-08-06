from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Any

from .pool import DependencyPool
from .versions import DEPENDENCY_POOL_VERSION, ENVIRONMENT_LOCK_VERSION


DEPENDENCY_POOL_ROOT_ENV = "AGENTFACTORY_DEPENDENCY_POOL_ROOT"
ENVIRONMENT_LOCK_PATH_ENV = "AGENTFACTORY_ENVIRONMENT_LOCK_PATH"


class RuntimeDependencyError(RuntimeError):
    pass


def activate_runtime_dependencies() -> dict[str, Any]:
    lock_path = _required_environment_path(ENVIRONMENT_LOCK_PATH_ENV)
    pool_root = _required_environment_path(DEPENDENCY_POOL_ROOT_ENV)
    lock = _read_lock(lock_path)
    pool = _pool_payload(lock)
    if not DependencyPool(pool_root).references_available(pool):
        raise RuntimeDependencyError("environment lock references unavailable dependency-pool entries")
    system_entries = _entries(pool, "system_entries")
    if system_entries:
        raise RuntimeDependencyError(
            "local runtime environment locks cannot contain operating-system package artifacts"
        )
    requirements = lock.get("requirements") if isinstance(lock.get("requirements"), dict) else {}
    timeout_seconds = _timeout_seconds(requirements.get("install_timeout_seconds"))
    binaries = requirements.get("system_binaries") if isinstance(requirements.get("system_binaries"), list) else []
    commands = requirements.get("verification_commands") if isinstance(requirements.get("verification_commands"), list) else []
    _verify_binaries([str(item) for item in binaries])
    _verify_commands(commands, timeout_seconds=timeout_seconds)
    return {
        "source": "dependency_pool",
        "python_entry_count": len(_entries(pool, "python_entries")),
        "system_entry_count": 0,
        "npm_profile": bool(pool.get("npm_profile")),
        "pool_root": str(pool_root),
    }


def _required_environment_path(name: str) -> Path:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeDependencyError(f"local runtime environment variable is missing: {name}")
    return Path(value).expanduser().resolve()


def _verify_binaries(binaries: list[str]) -> None:
    missing = [binary for binary in binaries if binary and shutil.which(binary) is None]
    if missing:
        raise RuntimeDependencyError("declared system binaries are unavailable after dependency activation: " + ", ".join(missing))


def _verify_commands(commands: list[Any], *, timeout_seconds: int | None) -> None:
    for raw in commands:
        if not isinstance(raw, list) or not raw or not all(isinstance(item, str) and item for item in raw):
            raise RuntimeDependencyError("dependency verification commands must be non-empty string argument lists")
        try:
            completed = subprocess.run(raw, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeDependencyError(f"dependency verification timed out: {' '.join(raw)}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "verification failed").strip()
            raise RuntimeDependencyError(f"dependency verification failed: {' '.join(raw)}: {detail[-1000:]}")


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeDependencyError(f"unable to read environment lock: {path}") from exc
    if not isinstance(value, dict) or value.get("version") != ENVIRONMENT_LOCK_VERSION:
        raise RuntimeDependencyError("environment lock is missing or incompatible")
    return value


def _pool_payload(lock: dict[str, Any]) -> dict[str, Any]:
    pool = lock.get("pool")
    if not isinstance(pool, dict) or pool.get("version") != DEPENDENCY_POOL_VERSION:
        raise RuntimeDependencyError("environment lock does not contain a dependency pool reference")
    return pool


def _entries(pool: dict[str, Any], key: str) -> list[dict[str, str]]:
    value = pool.get(key)
    if not isinstance(value, list):
        raise RuntimeDependencyError(f"dependency pool field is invalid: {key}")
    entries: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeDependencyError(f"dependency pool entry is invalid: {key}")
        path = _required_path(item)
        entries.append({"path": path})
    return entries


def _required_path(entry: dict[str, Any]) -> str:
    value = entry.get("path")
    if not isinstance(value, str) or not value:
        raise RuntimeDependencyError("dependency pool entry does not contain a path")
    _pool_relative(value)
    return value


def _pool_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeDependencyError(f"unsafe dependency pool path: {value}")
    return path


def _timeout_seconds(value: object) -> int | None:
    return value if isinstance(value, int) and value > 0 else None
