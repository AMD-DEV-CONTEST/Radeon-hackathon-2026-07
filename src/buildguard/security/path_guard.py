"""Filesystem allowlist and sensitive-file protection."""

from __future__ import annotations

import fnmatch
from pathlib import Path

SENSITIVE_PATTERNS = (".env", "id_rsa", "id_ed25519", "*.pem", "*.key", "credentials*")


class PathGuard:
    def __init__(self, read_roots: list[Path], write_roots: list[Path] | None = None) -> None:
        self.read_roots = [root.resolve() for root in read_roots]
        self.write_roots = [root.resolve() for root in (write_roots or [])]
        if not self.read_roots:
            raise ValueError("At least one read root is required")

    @staticmethod
    def _sensitive(path: Path) -> bool:
        name = path.name.lower()
        return any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_PATTERNS)

    @staticmethod
    def _within(path: Path, roots: list[Path]) -> bool:
        return any(path == root or path.is_relative_to(root) for root in roots)

    def resolve_read(self, path: Path, *, root: Path | None = None) -> Path:
        base = root.resolve() if root else self.read_roots[0]
        if base not in self.read_roots:
            raise PermissionError("Requested read root is not allowlisted")
        candidate = path.resolve() if path.is_absolute() else (base / path).resolve()
        if not self._within(candidate, self.read_roots):
            raise PermissionError(f"Read path escapes allowed roots: {path}")
        if self._sensitive(candidate):
            raise PermissionError(f"Sensitive file is blocked: {candidate.name}")
        return candidate

    def resolve_write(
        self,
        path: Path,
        *,
        root: Path | None = None,
        overwrite_confirmed: bool = False,
    ) -> Path:
        if not self.write_roots:
            raise PermissionError("No write roots are configured")
        base = root.resolve() if root else self.write_roots[0]
        if base not in self.write_roots:
            raise PermissionError("Requested write root is not allowlisted")
        candidate = path.resolve() if path.is_absolute() else (base / path).resolve()
        if not self._within(candidate, self.write_roots):
            raise PermissionError(f"Write path escapes allowed roots: {path}")
        if self._sensitive(candidate):
            raise PermissionError(f"Sensitive file is blocked: {candidate.name}")
        if candidate.exists() and not overwrite_confirmed:
            raise PermissionError("Overwriting an existing file requires confirmation")
        return candidate

