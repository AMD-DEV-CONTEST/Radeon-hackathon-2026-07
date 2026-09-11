#!/usr/bin/env python3
"""Audit a strict PI0.5 closed-loop configuration for expert leakage."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from parcel_sorter.mobile_pi05_contract import PI05_GRASP_MODES


MODE_LANGUAGE = re.compile(
    r"\b(top|side|suction|cradle|grasp family|selected grasp|selected mode)\b",
    re.IGNORECASE,
)
ZERO_VECTOR_FIELDS = (
    "recovery_contact_offset_m",
    "recovery_left_lift_offset_m",
    "recovery_right_lift_offset_m",
)
ZERO_SCALAR_FIELDS = (
    "recovery_contact_penetration_delta_m",
    "recovery_cradle_engagement_delta_m",
)


def audit_strict_config(config: dict[str, Any]) -> dict[str, Any]:
    errors = []
    episodes = list(config.get("episodes") or ())
    modes = [str(episode.get("grasp_mode")) for episode in episodes]
    if sorted(modes) != sorted(PI05_GRASP_MODES):
        errors.append("episodes_must_cover_each_grasp_mode_once")
    tasks = [str(episode.get("task_text") or "") for episode in episodes]
    if len(set(tasks)) != 1 or not tasks or not tasks[0].strip():
        errors.append("task_text_must_be_one_shared_nonempty_instruction")
    for episode in episodes:
        episode_id = str(episode.get("episode_id") or "unknown")
        task = str(episode.get("task_text") or "")
        if MODE_LANGUAGE.search(task):
            errors.append(f"mode_language_leakage:{episode_id}")
        for field in ZERO_VECTOR_FIELDS:
            values = episode.get(field, (0.0, 0.0, 0.0))
            if any(abs(float(value)) > 1e-9 for value in values):
                errors.append(f"expert_vector_correction:{episode_id}:{field}")
        for field in ZERO_SCALAR_FIELDS:
            if abs(float(episode.get(field, 0.0))) > 1e-9:
                errors.append(f"expert_scalar_correction:{episode_id}:{field}")
    return {
        "schema_version": 1,
        "protocol": "pi05-strict-config-audit-v1",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "error_count": len(errors),
        "metrics": {
            "episodes": len(episodes),
            "modes": modes,
            "unique_task_texts": len(set(tasks)),
            "expert_contact_or_lift_corrections": sum(
                error.startswith("expert_") for error in errors
            ),
        },
        "claim_boundary": "Configuration leakage audit only; it does not measure closed-loop success.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = audit_strict_config(
        json.loads(args.config.read_text(encoding="utf-8"))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
