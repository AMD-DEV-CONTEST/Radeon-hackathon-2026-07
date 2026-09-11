#!/usr/bin/env python3
"""Bind an audited Agent plan to a bounded PI0.5 development demo config."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--agent-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-episodes", type=int, default=6)
    parser.add_argument(
        "--shape",
        help="Optionally restrict source episodes to one physical object shape",
    )
    parser.add_argument(
        "--episode-id",
        action="append",
        default=[],
        help="Select an exact source episode; repeat to preserve an explicit order",
    )
    args = parser.parse_args()
    if args.max_episodes < 1:
        parser.error("max-episodes must be positive")

    source = _read_json(args.source_config)
    plan = _read_json(args.agent_plan)
    if plan.get("protocol") != "parcel-agent-pi05-episode-plan-v1":
        raise ValueError("unsupported Agent plan protocol")
    if plan.get("status") != "passed":
        raise ValueError("Agent plan must have passed fail-closed validation")
    trace = _mapping(plan, "agent_trace")
    directive = _mapping(plan, "directive")
    bridge = _mapping(plan, "pi05_task_bridge")
    if trace.get("status") != "passed":
        raise ValueError("Agent trace must have passed")
    if bridge.get("authority") != "task_conditioning_only":
        raise ValueError("Agent bridge must be task-conditioning-only")

    episodes = source.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        raise ValueError("source config must contain episodes")
    runtime_mode = str(bridge["runtime_grasp_mode"])
    eligible = [
        item
        for item in episodes
        if isinstance(item, dict)
        and (runtime_mode == "auto" or item.get("grasp_mode") == runtime_mode)
        and (args.shape is None or item.get("shape") == args.shape)
    ]
    if args.episode_id:
        by_id = {str(item.get("episode_id")): item for item in eligible}
        missing = [episode_id for episode_id in args.episode_id if episode_id not in by_id]
        if missing:
            raise ValueError(f"requested episodes are not eligible: {missing}")
        eligible = [by_id[episode_id] for episode_id in args.episode_id]
    if not eligible:
        raise ValueError(
            "source config has no episodes matching the Agent grasp mode and shape"
        )
    selected = [dict(item) for item in eligible[: args.max_episodes]]
    for episode in selected:
        episode["task_text"] = str(bridge["task_text"])
        episode["agent_directive_id"] = str(directive["directive_id"])
        episode["agent_recovery_strategy"] = str(bridge["recovery_strategy"])

    selected_cells = {
        str(episode.get("design_cell"))
        for episode in selected
        if episode.get("design_cell")
    }
    source_cells = source.get("cells")
    if isinstance(source_cells, list) and selected_cells:
        source["cells"] = [
            {
                **cell,
                "candidate_attempts": sum(
                    episode.get("design_cell") == cell.get("cell_id")
                    for episode in selected
                ),
                "target_successes": 0,
            }
            for cell in source_cells
            if isinstance(cell, dict) and cell.get("cell_id") in selected_cells
        ]
    source["planned_attempts"] = len(selected)
    source["target_successes"] = 0
    source.pop("success_quotas_by_sampling_stratum", None)

    source.update(
        {
            "collection_id": "v21-agent-hybrid-development",
            "protocol": "pi05-v21-agent-hybrid-development-v1",
            "status": "agent_conditioned_development_smoke",
            "agent_plan": {
                "path": args.agent_plan.name,
                "sha256": _sha256_file(args.agent_plan),
                "requested_model": str(trace["requested_model"]),
                "actual_model": str(trace["actual_model"]),
                "fallback_used": bool(trace["fallback_used"]),
                "directive_id": str(directive["directive_id"]),
            },
            "attribution_requirements": {
                "system_control_class": "agent_conditioned_harnessed_vla",
                "pure_vla": False,
                "scripted_fallback_allowed": True,
                "agent_servo_authority": False,
            },
            "claim_boundary": (
                "Development-only Agent-conditioned harnessed-VLA run. Report "
                "VLA accepted steps, scripted fallbacks, and actual Agent model."
            ),
            "episodes": selected,
        }
    )
    _write_json_atomic(args.output, source)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "episodes": len(selected),
                "actual_model": trace["actual_model"],
                "fallback_used": trace["fallback_used"],
            },
            indent=2,
        )
    )
    return 0


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
