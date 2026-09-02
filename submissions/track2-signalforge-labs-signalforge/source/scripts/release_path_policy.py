"""Candidate-root containment for SignalForge release tooling."""

from __future__ import annotations

from pathlib import Path


def resolve_candidate_file(root: Path, relative: Path) -> tuple[Path | None, str | None]:
    """Return a contained non-symlink candidate path before any content access."""
    if relative.is_absolute() or ".." in relative.parts:
        return None, "path escapes repository candidate"

    root_resolved = root.resolve()
    current = root_resolved
    for part in relative.parts:
        if part in {"", "."}:
            continue
        current = current / part
        if current.is_symlink():
            return None, "path uses a symlink"

    candidate = root_resolved / relative
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None, "path cannot be resolved safely"
    if not resolved.is_relative_to(root_resolved):
        return None, "path escapes repository candidate"
    return candidate, None
