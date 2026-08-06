"""File-backed Skill registry (M7 Skills basic line, Phase 1).

The registry is a simple JSON file shipped under `app/data/skills_seed.json`.
We keep it read-only at this stage — upgrade path is a DB-backed registry
(already sketched in plan), but for the basic functionality line a file is
easier to evolve and review.

Public API:
    - list_skills() -> list[dict]
    - get_skill(skill_id) -> dict | None
    - get_compatible_skills(runtime_robot_type) -> list[dict]
    - validate_params(skill, params) -> list[str]  # error messages, empty means OK
"""
from __future__ import annotations

import json
import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "skills_seed.json"

for _parent in Path(__file__).resolve().parents:
    _spec_py = _parent / "packages" / "botclaw-spec" / "python"
    if _spec_py.exists():
        sys.path.insert(0, str(_spec_py))
        break

from botclaw_spec import Skill  # noqa: E402


@lru_cache(maxsize=1)
def _load() -> list[dict[str, Any]]:
    if not _SEED_PATH.exists():
        log.warning("skills_seed.json not found at %s", _SEED_PATH)
        return []
    try:
        data = json.loads(_SEED_PATH.read_text(encoding="utf-8"))
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            log.error("skills_seed.json: `skills` must be a list")
            return []
        valid: list[dict[str, Any]] = []
        for idx, raw in enumerate(skills):
            try:
                skill = Skill.model_validate(raw)
                valid.append(skill.model_dump(mode="json", exclude_none=True))
            except Exception as e:  # noqa: BLE001
                log.error("skills_seed.json: skills[%s] failed BotClaw validation: %s", idx, e)
        return valid
    except Exception as e:  # noqa: BLE001
        log.exception("failed to load skills_seed.json: %s", e)
        return []


def reload_registry() -> None:
    """Force a fresh read from disk (useful during dev / after hot edits)."""
    _load.cache_clear()


def list_skills() -> list[dict[str, Any]]:
    return list(_load())


def get_skill(skill_id: str) -> dict[str, Any] | None:
    for s in _load():
        if s.get("skill_id") == skill_id:
            return s
    return None


def get_compatible_skills(runtime_robot_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in _load():
        rt = s.get("robot_type")
        compat = s.get("compatible_types") or []
        if rt == runtime_robot_type or runtime_robot_type in compat:
            out.append(s)
    return out


def validate_params(skill: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Validate user-supplied params against `params_schema` entries.

    Returns a list of human-readable error strings (empty = OK).
    Only does basic checks (required / type / min / max / enum) — matches the
    "basic line" scope. More elaborate schema enforcement belongs later.
    """
    schema = skill.get("params_schema") or []
    if not isinstance(schema, list):
        return ["params_schema on this skill is malformed"]

    errors: list[str] = []
    params = params or {}

    for entry in schema:
        key = entry.get("key")
        if not key:
            continue
        label = entry.get("label") or key
        required = bool(entry.get("required"))
        value = params.get(key)
        vtype = entry.get("type") or "string"

        if value is None or value == "":
            if required:
                errors.append(f"{label} ({key}) is required")
            continue

        if vtype == "number":
            try:
                num = float(value)
            except (TypeError, ValueError):
                errors.append(f"{label} must be a number")
                continue
            mn = entry.get("min")
            mx = entry.get("max")
            if mn is not None and num < mn:
                errors.append(f"{label} must be ≥ {mn}")
            if mx is not None and num > mx:
                errors.append(f"{label} must be ≤ {mx}")
        elif vtype == "bool":
            if not isinstance(value, bool):
                errors.append(f"{label} must be true/false")
        elif vtype == "enum":
            options = entry.get("options") or []
            if value not in options:
                errors.append(f"{label} must be one of: {', '.join(map(str, options))}")
        else:  # string / fallback
            if not isinstance(value, (str, int, float)):
                errors.append(f"{label} must be a string")

    return errors
