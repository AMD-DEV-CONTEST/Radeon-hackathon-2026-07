"""Path / ID hardening helpers for private agent tools."""

from __future__ import annotations

import re
from pathlib import Path

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def is_under(child: Path, parent: Path) -> bool:
    """True iff child resolves strictly inside parent (symlink-aware)."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def safe_join(base: Path, name: str) -> Path | None:
    """Join basename-only under base; reject abs / .. / traversal."""
    raw = (name or "").strip().replace("\\", "/")
    if not raw:
        return None
    p = Path(raw)
    if p.is_absolute():
        return None
    base_name = p.name
    if not base_name or base_name in {".", ".."}:
        return None
    candidate = (base / base_name).resolve()
    if not is_under(candidate, base):
        return None
    return candidate


def sanitize_id(value: str, fallback: str = "custom") -> str:
    """Restrict workflow/app/skill project IDs to a safe charset."""
    raw = (value or "").strip().replace("\\", "/").split("/")[-1]
    raw = raw.replace("..", "")
    if _SAFE_ID_RE.match(raw):
        return raw
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    if cleaned and _SAFE_ID_RE.match(cleaned[:64]):
        return cleaned[:64]
    digest = abs(hash(value)) % 10_000_000
    fb = fallback if _SAFE_ID_RE.match(fallback) else "custom"
    return f"{fb}_{digest}"
