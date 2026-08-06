from __future__ import annotations

from pathlib import Path


TRANSIENT_PACKAGE_ROOTS = {".agent_runtime", ".factory"}
TRANSIENT_PACKAGE_NAMES = {
    ".DS_Store",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
TRANSIENT_PACKAGE_SUFFIXES = {".pyc", ".pyo"}


def normalize_package_relative(path: str | Path) -> str:
    relative = Path(str(path)).as_posix()
    while relative.startswith("./"):
        relative = relative[2:]
    return relative


def is_transient_package_path(path: str | Path) -> bool:
    relative = normalize_package_relative(path)
    if not relative:
        return True
    parts = relative.split("/")
    if parts[0] in TRANSIENT_PACKAGE_ROOTS:
        return True
    if any(part in TRANSIENT_PACKAGE_NAMES for part in parts):
        return True
    return any(relative.endswith(suffix) for suffix in TRANSIENT_PACKAGE_SUFFIXES)
