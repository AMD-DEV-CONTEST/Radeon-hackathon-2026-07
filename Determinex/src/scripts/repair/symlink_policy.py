"""Workspace symlink policy.

CLAUDE-AUTH-009 remediation: previously the snapshot/restore path
silently dereferenced symlinks (Path.is_file() follows symlinks;
shutil.copy2 / shutil.copytree(symlinks=False) follow symlinks).
A workspace containing a hostile symlink (e.g. pointing at
/etc/passwd) would have TARGET content snapshotted and then
restored as a regular file.

This module enforces a conservative policy: if the workspace contains
any symlink under it, snapshot/apply/rollback refuse to proceed.

Why refuse rather than preserve: preserving symlink semantics across
a snapshot/restore involves recording the link target as metadata
and reconstructing the link at restore time. That introduces
complexity (cross-platform link semantics, symlink-of-symlink chains,
non-existing targets) that the apparatus does not need today. A
clean refusal is auditable; the operator can resolve the workspace
to a symlink-free state before retrying.
"""

from __future__ import annotations

from pathlib import Path


def find_symlinks(root: Path) -> list[Path]:
    """Return every symlink under root (relative paths)."""
    root = Path(root)
    if not root.is_dir():
        return []
    out: list[Path] = []
    # Use lstat to detect symlinks without following them.
    for p in root.rglob("*"):
        try:
            if p.is_symlink():
                out.append(p.relative_to(root))
        except OSError:
            # Race or transient — be conservative and treat as symlink.
            out.append(p.relative_to(root))
    return out


def has_symlinks(root: Path) -> bool:
    return bool(find_symlinks(root))


__all__ = ["find_symlinks", "has_symlinks"]
