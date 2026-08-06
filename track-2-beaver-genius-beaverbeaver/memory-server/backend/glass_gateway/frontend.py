from __future__ import annotations

import os
from pathlib import Path


def frontend_root() -> Path:
    configured = os.getenv("FRONTEND_ROOT") or os.getenv("GLASS_FRONTEND_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "frontend"


def frontend_page(name: str) -> Path:
    if Path(name).name != name:
        raise ValueError("frontend page name must not contain a path")
    return frontend_root() / "pages" / name
