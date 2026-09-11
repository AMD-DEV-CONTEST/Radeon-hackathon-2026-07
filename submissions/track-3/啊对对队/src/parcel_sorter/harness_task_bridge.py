"""Compile validated Agent directives into bounded PI0.5 task conditions."""

from __future__ import annotations

from typing import Any, Mapping

from .harness_agent import AgentIdentity, sha256_json, validate_task_directive


GRASP_MODE_TO_RUNTIME = {
    "top": "top_suction",
    "side": "side_suction",
    "cradle": "cooperative_cradle",
    "auto": "auto",
}


def compile_task_directive_for_pi05(
    directive: Mapping[str, Any], *, task_agent: AgentIdentity
) -> dict[str, Any]:
    """Create task conditioning only; no action or safety authority is compiled."""

    model_fields = {
        "schema_version",
        "protocol",
        "directive_id",
        "agent_id",
        "goal",
        "grasp_mode",
        "recovery_strategy",
        "memory_refs",
        "rationale",
    }
    derived_fields = {"authority", "task_observation_sha256"}
    unexpected = sorted(set(directive) - model_fields - derived_fields)
    if unexpected:
        raise ValueError(f"task bridge received undeclared fields: {unexpected}")
    if directive.get("authority", "high_level_only") != "high_level_only":
        raise ValueError("task bridge requires high-level-only Agent authority")
    validated = validate_task_directive(
        {key: directive[key] for key in model_fields if key in directive},
        task_agent=task_agent,
    )
    grasp_mode = str(validated["grasp_mode"])
    runtime_mode = GRASP_MODE_TO_RUNTIME[grasp_mode]
    task_text = (
        f"{validated['goal']}. Use {grasp_mode} grasp mode. "
        f"On failure use {validated['recovery_strategy']}."
    )
    return {
        "schema_version": 1,
        "protocol": "parcel-agent-pi05-task-bridge-v1",
        "directive_id": validated["directive_id"],
        "directive_sha256": sha256_json(validated),
        "task_text": task_text,
        "runtime_grasp_mode": runtime_mode,
        "recovery_strategy": validated["recovery_strategy"],
        "authority": "task_conditioning_only",
        "forbidden_authority": [
            "servo_action",
            "cartesian_target",
            "joint_target",
            "safety_override",
            "checkpoint_activation",
        ],
    }
