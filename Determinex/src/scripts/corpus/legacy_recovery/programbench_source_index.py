from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from corpus.legacy_recovery.programbench_tool_alias_index import (
    normalized_repo_name,
    normalized_slug,
    normalized_tool_name,
)


@dataclass(slots=True)
class ProgramBenchSourceEntry:
    slug: str
    root: str
    source_root: str
    binary_names: list[str]
    metadata: dict[str, Any]
    index_keys: list[str]
    exact_keys: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProgramBenchSourceIndex:
    """Index local ProgramBench task/source roots without following symlink escapes."""

    def __init__(self, roots: list[Path], *, max_depth: int = 3) -> None:
        self.roots = [Path(root) for root in roots]
        self.max_depth = max_depth
        self.entries = self._build_entries()

    def find_by_key(self, key: str) -> list[ProgramBenchSourceEntry]:
        normalized = normalized_slug(key)
        return [entry for entry in self.entries if normalized in entry.index_keys]

    def find_exact(self, key: str) -> list[ProgramBenchSourceEntry]:
        normalized = normalized_slug(key)
        return [entry for entry in self.entries if normalized in entry.exact_keys]

    def find_by_binary(self, binary_name: str) -> list[ProgramBenchSourceEntry]:
        normalized = normalized_slug(binary_name)
        return [
            entry
            for entry in self.entries
            if normalized in {normalized_slug(name) for name in entry.binary_names}
        ]

    def _build_entries(self) -> list[ProgramBenchSourceEntry]:
        entries: list[ProgramBenchSourceEntry] = []
        seen: set[str] = set()
        for root in self.roots:
            if not root.exists() or not root.is_dir():
                continue
            for path in _walk_dirs(root, self.max_depth):
                if not _inside(path, root) or _is_symlink_escape(path, root):
                    continue
                if not _looks_like_programbench_dir(path):
                    continue
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                entries.append(_entry_for(path))
        return entries


def _walk_dirs(root: Path, max_depth: int) -> list[Path]:
    out: list[Path] = []
    root_depth = len(root.parts)
    stack = [root]
    while stack:
        current = stack.pop()
        depth = len(current.parts) - root_depth
        if depth > max_depth:
            continue
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            out.append(child)
            if depth < max_depth:
                stack.append(child)
    return out


def _looks_like_programbench_dir(path: Path) -> bool:
    if "__" in path.name and "." in path.name:
        return True
    if (path / "source").is_dir() or (path / "eval").is_dir():
        return True
    if any(
        (path / name).is_file()
        for name in ("Cargo.toml", "go.mod", "package.json", "Makefile", "CMakeLists.txt")
    ):
        return True
    if any(
        (path / name).is_file()
        for name in ("executable", "build.sh", "manifest.json", "gate_result.json")
    ):
        return True
    return False


def _entry_for(path: Path) -> ProgramBenchSourceEntry:
    metadata = _read_metadata(path)
    slug = str(metadata.get("slug") or path.name)
    source_root = _source_root(path)
    binary_names = _binary_names(path, metadata)
    keys = {
        normalized_slug(slug),
        normalized_tool_name(slug),
        normalized_repo_name(slug),
        normalized_slug(path.name),
        normalized_slug(_without_revision(slug)),
        normalized_slug(_without_revision(path.name)),
    }
    for name in binary_names:
        keys.add(normalized_slug(name))
    return ProgramBenchSourceEntry(
        slug=slug,
        root=str(path),
        source_root=str(source_root),
        binary_names=sorted(set(binary_names)),
        metadata=metadata,
        index_keys=sorted(key for key in keys if key),
        exact_keys=sorted(
            {
                normalized_slug(slug),
                normalized_slug(path.name),
            }
        ),
    )


def _read_metadata(path: Path) -> dict[str, Any]:
    for name in ("manifest.json", "metadata.json", "task.json", "gate_result.json"):
        candidate = path / name
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _without_revision(value: str) -> str:
    parts = value.rsplit(".", 1)
    if len(parts) == 2 and 6 <= len(parts[1]) <= 12:
        return parts[0]
    return value


def _source_root(path: Path) -> Path:
    for name in ("source", "src"):
        candidate = path / name
        if candidate.is_dir():
            return candidate
    return path


def _binary_names(path: Path, metadata: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("binary", "binary_name", "executable", "tool", "name"):
        value = metadata.get(key)
        if isinstance(value, str):
            names.append(Path(value).name)
    for name in ("executable", "build.sh"):
        if (path / name).is_file():
            names.append(name)
    try:
        for child in path.iterdir():
            if child.is_file() and child.suffix == "" and child.name not in {"LICENSE", "README"}:
                names.append(child.name)
    except OSError:
        pass
    if "__" in path.name:
        names.append(path.name.split("__", 1)[1].split(".", 1)[0])
    names.append(path.name)
    return [name for name in names if name]


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_symlink_escape(path: Path, root: Path) -> bool:
    try:
        if path.is_symlink():
            path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return False
