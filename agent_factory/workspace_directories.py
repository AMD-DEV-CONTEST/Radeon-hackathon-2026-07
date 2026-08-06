from __future__ import annotations

import os
from pathlib import Path


WORKSPACE_DIRECTORY_ROOTS_ENV = "AGENTFACTORY_WORKSPACE_DIRECTORY_ROOTS"


class WorkspaceDirectoryBrowser:
    def __init__(self, roots: tuple[Path, ...] | None = None) -> None:
        self.roots = roots or _configured_roots()

    def root_views(self) -> list[dict[str, str]]:
        return [
            {
                "name": root.name or str(root),
                "path": str(root),
            }
            for root in self.roots
        ]

    def list_directories(self, path: str) -> dict[str, object]:
        current = self.resolve(path)
        directories: list[dict[str, str]] = []
        for child in sorted(current.iterdir(), key=lambda item: item.name.casefold()):
            try:
                if not child.is_dir():
                    continue
            except OSError:
                continue
            directories.append({"name": child.name, "path": str(child.resolve())})
        parent = current.parent
        return {
            "path": str(current),
            "parent": str(parent) if self._is_allowed(parent) else None,
            "directories": directories,
        }

    def resolve(self, value: str) -> Path:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("directory path must not be empty")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise ValueError("directory path must be absolute")
        resolved = candidate.resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"workspace directory not found: {resolved}")
        if not self._is_allowed(resolved):
            raise PermissionError(f"workspace directory is outside configured roots: {resolved}")
        return resolved

    def _is_allowed(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        return any(_is_relative_to(resolved, root) for root in self.roots)


def _configured_roots() -> tuple[Path, ...]:
    configured = str(os.getenv(WORKSPACE_DIRECTORY_ROOTS_ENV) or "").strip()
    candidates = (
        [Path(item) for item in configured.split(os.pathsep) if item.strip()]
        if configured
        else [Path.home()]
    )
    roots: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    if not roots:
        raise RuntimeError("no workspace directory roots are available")
    return tuple(roots)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
