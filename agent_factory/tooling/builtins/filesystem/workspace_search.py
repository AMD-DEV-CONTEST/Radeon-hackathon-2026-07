from __future__ import annotations

from datetime import UTC, datetime
import fnmatch
import os
from pathlib import Path
from typing import Iterator

from agent_factory.tooling.builtins.filesystem.common import path_type


DEFAULT_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
    }
)


def iter_workspace_entries(root: Path, *, recursive: bool) -> Iterator[Path]:
    if not recursive:
        yield from sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower(), item.name))
        return
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = sorted(
            name
            for name in directory_names
            if name not in DEFAULT_IGNORED_DIRECTORY_NAMES
        )
        current = Path(current_root)
        for directory_name in directory_names:
            yield current / directory_name
        for file_name in sorted(file_names):
            yield current / file_name


def iter_workspace_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    for item in iter_workspace_entries(root, recursive=True):
        if item.is_file():
            yield item


def workspace_path_record(
    path: Path,
    *,
    workspace_root: Path,
    mounts: dict[str, Path] | None = None,
) -> dict[str, object]:
    virtual_path = workspace_relative_path(path, workspace_root=workspace_root, mounts=mounts)
    mount_name = virtual_path.split("/", 1)[0]
    mounted = mount_name in (mounts or {})
    try:
        file_stat = path.stat()
        entry_type = path_type(path)
        size_bytes = file_stat.st_size if path.is_file() else None
        modified_at = datetime.fromtimestamp(file_stat.st_mtime, tz=UTC).isoformat()
        connected = True
    except OSError:
        entry_type = "directory" if mounted else "other"
        size_bytes = None
        modified_at = None
        connected = False
    return {
        "path": virtual_path,
        "name": path.name,
        "type": entry_type,
        "size_bytes": size_bytes,
        "modified_at": modified_at,
        **({"mounted": True, "connected": connected} if mounted else {}),
    }


def workspace_relative_path(
    path: Path,
    *,
    workspace_root: Path,
    mounts: dict[str, Path] | None = None,
) -> str:
    resolved_path = path.resolve(strict=False)
    try:
        relative = resolved_path.relative_to(workspace_root.resolve(strict=False))
    except ValueError:
        for name, mount_root in (mounts or {}).items():
            try:
                mount_relative = resolved_path.relative_to(mount_root.resolve(strict=False))
            except ValueError:
                continue
            suffix = mount_relative.as_posix()
            return f"{name}/{suffix}" if suffix not in {"", "."} else name
        return str(path)
    value = relative.as_posix()
    return value or "."


def matches_path_pattern(path: Path, *, search_root: Path, pattern: str) -> bool:
    relative = path.relative_to(search_root).as_posix()
    return fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern)


def matches_any_pattern(path: Path, *, search_root: Path, patterns: list[str]) -> bool:
    return any(matches_path_pattern(path, search_root=search_root, pattern=pattern) for pattern in patterns)


def string_list(value: object, *, key: str) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError(f"{key} must be a string or an array of strings")
    return [item.strip() for item in values if item.strip()]


def is_probably_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]
