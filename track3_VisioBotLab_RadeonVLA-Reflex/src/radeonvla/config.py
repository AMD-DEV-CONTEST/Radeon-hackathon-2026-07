"""YAML configuration loading with base-config inheritance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from radeonvla.paths import PROJECT_ROOT


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a YAML config, recursively merging any ``base_config`` parent."""
    cfg_path = _resolve(path)
    with cfg_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Config root must be a mapping: {cfg_path}")

    base_name = data.pop("base_config", None)
    if base_name:
        base_path = Path(base_name)
        if base_path.is_absolute():
            parent_path = base_path
        else:
            # Prefer project-root-relative paths (e.g. configs/base.yaml), then
            # fall back to paths relative to the child config file.
            root_candidate = PROJECT_ROOT / base_path
            sibling_candidate = cfg_path.parent / base_path
            parent_path = root_candidate if root_candidate.is_file() else sibling_candidate
        parent = load_config(parent_path)
        data = _deep_merge(parent, data)
    data["_config_path"] = str(cfg_path)
    return data
