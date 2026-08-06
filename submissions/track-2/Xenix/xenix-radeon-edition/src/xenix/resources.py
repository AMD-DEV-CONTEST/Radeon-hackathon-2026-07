from __future__ import annotations

from pathlib import Path

from .config import get_app_paths


def package_resource_path(*relative_path: str) -> Path:
    candidate = get_app_paths().resources.joinpath(*relative_path)
    if not candidate.exists():
        joined_path = "/".join(relative_path)
        raise FileNotFoundError(f"Resource not found: {joined_path}")

    return candidate
