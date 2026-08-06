#!/usr/bin/env python3
"""Validate apps/api/app/data/skills_seed.json against BotClaw Skill models.

This is intentionally dependency-light: it uses the local Pydantic models from
packages/botclaw-spec/python instead of requiring jsonschema in API venvs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SPEC_PY = ROOT / "packages" / "botclaw-spec" / "python"
SEED_PATH = ROOT / "apps" / "api" / "app" / "data" / "skills_seed.json"

if str(SPEC_PY) not in sys.path:
    sys.path.insert(0, str(SPEC_PY))

from botclaw_spec import Skill  # noqa: E402


def main() -> int:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    skills = data.get("skills")
    if not isinstance(skills, list):
        print("ERROR: skills_seed.json must contain a top-level 'skills' list", file=sys.stderr)
        return 2

    seen: set[str] = set()
    failures = 0
    for idx, raw in enumerate(skills):
        try:
            skill = Skill.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR: skills[{idx}] failed validation: {exc}", file=sys.stderr)
            continue
        if skill.skill_id in seen:
            failures += 1
            print(f"ERROR: duplicate skill_id: {skill.skill_id}", file=sys.stderr)
        seen.add(skill.skill_id)
        if skill.robot_type not in skill.compatible_types and skill.robot_type != "generic":
            failures += 1
            print(
                f"ERROR: {skill.skill_id}: compatible_types should include primary robot_type "
                f"'{skill.robot_type}'",
                file=sys.stderr,
            )

    if failures:
        print(f"BotClaw skill seed validation failed: {failures} issue(s)", file=sys.stderr)
        return 1

    print(f"BotClaw skill seed validation passed: {len(skills)} skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
