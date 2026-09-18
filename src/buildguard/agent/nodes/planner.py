"""Plan generation and safety validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from buildguard.agent.nodes.prompts import load_prompt
from buildguard.agent.state import AgentState
from buildguard.config import AgentConfig
from buildguard.exceptions import BuildGuardError
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.schemas.agent import PlanStep, TaskPlan

BANNED_TOOLS = {"shell", "python", "exec", "bash", "powershell"}


class PlanValidationError(BuildGuardError):
    """A generated plan violates configured safety constraints."""


def _argument_references(value: Any) -> list[str]:
    if isinstance(value, str) and value.startswith("$"):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _argument_references(child)]
    if isinstance(value, list):
        return [item for child in value for item in _argument_references(child)]
    return []


def validate_plan(plan: TaskPlan, config: AgentConfig) -> None:
    if len(plan.steps) > config.max_plan_steps:
        raise PlanValidationError(f"Plan exceeds maximum of {config.max_plan_steps} steps")
    identifiers = [step.step_id for step in plan.steps]
    if len(identifiers) != len(set(identifiers)):
        raise PlanValidationError("Plan step IDs must be unique")
    positions = {step_id: index for index, step_id in enumerate(identifiers)}
    for step in plan.steps:
        if step.tool_name is None:
            raise PlanValidationError(f"Step {step.step_id} must reference a registered tool")
        if step.tool_name.lower() in BANNED_TOOLS or step.tool_name not in config.registered_tools:
            raise PlanValidationError(f"Tool is not registered: {step.tool_name}")
        for dependency in step.depends_on:
            if dependency not in positions:
                raise PlanValidationError(f"Unknown dependency: {dependency}")
            if positions[dependency] >= positions[step.step_id]:
                raise PlanValidationError("Plan dependencies must form an ordered DAG")
        for reference in _argument_references(step.arguments):
            if reference in {
                "$user.query",
                "$session.id",
                "$attachments.images",
                "$state.inspection_results",
                "$state.retrieved_evidence",
            }:
                continue
            parts = reference.split(".")
            if len(parts) < 4 or parts[0] != "$steps" or parts[2] != "output":
                raise PlanValidationError(f"Invalid argument reference: {reference}")
            source = parts[1]
            if source not in step.depends_on or positions[source] >= positions[step.step_id]:
                raise PlanValidationError(
                    f"Argument reference must use a prior dependency: {reference}"
                )


def generate_plan(
    state: AgentState,
    backend: LocalLLMBackend,
    config: AgentConfig,
    *,
    replanning: bool = False,
    tool_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, object]:
    if state["image_paths"] and (
        not replanning or state["plan_phase"] == "visual"
    ):
        _VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}
        _single_path = state["image_paths"][0] if len(state["image_paths"]) == 1 else None
        _is_video = (
            _single_path is not None
            and Path(str(_single_path)).suffix.lower() in _VIDEO_EXTS
        )
        tool_name = (
            "inspect_video"
            if _is_video and "inspect_video" in config.registered_tools
            else "inspect_single_image"
            if len(state["image_paths"]) == 1
            and "inspect_single_image" in config.registered_tools
            else "inspect_image_batch_structured"
            if "inspect_image_batch_structured" in config.registered_tools
            else "inspect_image_batch"
            if "inspect_image_batch" in config.registered_tools
            else "inspect_image"
        )
        arguments: dict[str, object]
        if tool_name == "inspect_video":
            arguments = {"video_path": str(state["image_paths"][0])}
        elif tool_name in {"inspect_single_image", "inspect_image"}:
            arguments = {"image_path": str(state["image_paths"][0])}
        else:
            arguments = {
                "image_paths": "$attachments.images",
                "max_items": len(state["image_paths"]),
            }
        plan = TaskPlan(
            goal="先获取结构化视觉证据，再由 Agent 决定后续检索和风险工具",
            steps=[
                PlanStep(
                    step_id="visual_inspection",
                    description="调用视觉巡检能力；具体模型由视觉路由器决定",
                    tool_name=tool_name,
                    arguments=arguments,
                    requires_confirmation=(
                        tool_name
                        in {"inspect_image_batch", "inspect_image_batch_structured", "inspect_video"}
                    ),
                )
            ],
        )
        validate_plan(plan, config)
        return {
            "plan": plan,
            "plan_phase": "visual",
            "current_step": 0,
            "errors": [],
        }
    intent = state["intent"]
    thinking = replanning or (intent is not None and intent.complexity == "multi_step")
    suffix = " Replanned after recoverable failure." if replanning else ""
    registered = ", ".join(config.registered_tools)
    catalog = ""
    if tool_metadata:
        compact = [
            {
                "name": item.get("name"),
                "description": item.get("description"),
                "input_schema": item.get("input_schema"),
                "permission": item.get("permission"),
                "read_only": item.get("read_only"),
            }
            for item in tool_metadata
            if item.get("name") in config.registered_tools
        ]
        catalog = "\nTool catalog (use only these input fields): " + json.dumps(
            compact,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    prompt = (
        f"{load_prompt('planner.txt')}\n"
        f"Registered tools: {registered}.{catalog}\n"
        "Set requires_confirmation=true when the catalog permission is confirm.\n"
        "Available context references: $user.query and $session.id. "
        "For generate_inspection_report and session-scoped history, pass "
        '{"session_id":"$session.id"}. '
        f"Requested action hint: {state['requested_action'] or 'auto'}. "
        f"User query: {state['user_query']}.{suffix}"
    )
    plan = backend.structured_chat(
        [ChatMessage(role="user", content=prompt)],
        TaskPlan,
        thinking=thinking,
        profile="complex_replan" if replanning else "structured_plan",
    )
    validate_plan(plan, config)
    trace = [*state["performance_trace"], *getattr(backend, "metrics_history", [])[-1:]]
    return {
        "plan": plan,
        "plan_phase": "general",
        "current_step": 0,
        "errors": [],
        "performance_trace": trace,
    }
