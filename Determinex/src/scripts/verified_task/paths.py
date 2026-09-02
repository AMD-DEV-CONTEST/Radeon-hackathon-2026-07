"""Path policy for verified task runs.

All bulky work defaults to T: through DETERMINEX_VERIFIED_TASK_ROOT, then
DETERMINEX_PB_STAGING_ROOT, then T:/determinex-staging/verified_tasks.
"""

from __future__ import annotations

import os
from pathlib import Path


def default_verified_root() -> Path:
    raw = (
        os.getenv("DETERMINEX_VERIFIED_TASK_ROOT")
        or os.getenv("DETERMINEX_PB_STAGING_ROOT")
        or "T:/determinex-staging/verified_tasks"
    )
    return Path(raw).expanduser()


def ensure_on_staging_root(path: Path) -> Path:
    path = path.resolve()
    root = default_verified_root().resolve()
    allowed = [root]
    pb_root = os.getenv("DETERMINEX_PB_STAGING_ROOT")
    if pb_root:
        allowed.append(Path(pb_root).expanduser().resolve())
    elif root.name == "verified_tasks":
        allowed.append(root.parent)
    for base in allowed:
        try:
            path.relative_to(base)
            return path
        except ValueError:
            pass
    roots = ", ".join(str(p) for p in allowed)
    raise ValueError(f"path is outside verified task staging roots: {path} not under {roots}")
