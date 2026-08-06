from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.models import SystemManufacturingState, SystemStageStatus
from agent_factory.create_agent.stage_context import CreateAgentStageContext
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_STAGE_TOOL_ID = "create_agent_stage"


def build_create_agent_stage_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_STAGE_TOOL_ID,
        description=(
            "Inspect and explicitly set the active create-agent authoring focus for manufacturing or evolution. "
            "Use this instead of editing .factory/system_state.json directly."
        ),
        entrypoint="agent_factory.create_agent.stage_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["inspect", "set_focus", "mark_waiting_user"],
                },
                "focus_id": {"type": "string"},
                "system_id": {"type": "string"},
                "reason": {"type": "string"},
                "summary": {"type": "string"},
                "issue": {"type": "object", "additionalProperties": True},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "message": {"type": "string"},
                "state": {"type": "object", "additionalProperties": True},
                "active_focus": {"type": ["object", "null"], "additionalProperties": True},
                "task_analysis": {"type": "object", "additionalProperties": True},
                "latest_validation": {"type": ["object", "null"], "additionalProperties": True},
                "updated_at": {"type": "string"},
                "warnings": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "manufacturing_guidance": {"type": "object", "additionalProperties": True},
            },
            "required": [
                "action",
                "message",
                "state",
                "active_focus",
                "task_analysis",
                "latest_validation",
                "updated_at",
                "warnings",
                "manufacturing_guidance",
            ],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.stage_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    context = _stage_context(resources)
    state = context.read_state()
    action = str(arguments.get("action") or "").strip()
    if action == "inspect":
        return tool_envelope(_output(action=action, message="Current create-agent authoring focus state.", state=state, workspace=workspace))
    if action == "set_focus":
        focus_id = _requested_focus_id(arguments)
        _reason(arguments)
        state = state.set_focus(focus_id)
        context.write_state(state)
        return tool_envelope(_output(action=action, message=f"Active authoring focus set to: {focus_id}", state=state, workspace=workspace))
    if action == "mark_waiting_user":
        stage = _active_stage(state)
        state = state.update_stage(stage.model_copy(update={"status": SystemStageStatus.blocked_waiting_user}))
        context.write_state(state)
        return tool_envelope(_output(action=action, message=f"Focus waiting for user input: {stage.system_id}", state=state, workspace=workspace))
    raise ValueError("action must be one of: inspect, set_focus, mark_waiting_user")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action not in {"inspect", "set_focus", "mark_waiting_user"}:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=["invalid create-agent stage action"],
        ).model_dump(mode="json")
    try:
        state = _stage_context(dict(context.get("resources") or {})).read_state()
        if action == "set_focus":
            _known_stage(state, _requested_focus_id(arguments))
            _reason(arguments)
        elif action == "mark_waiting_user":
            _active_stage(state)
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent focus operation: {type(exc).__name__}: {exc}"],
            facts={
                "action": action,
                "requested_focus_id": str(arguments.get("focus_id") or arguments.get("system_id") or ""),
                "error_type": type(exc).__name__,
                "required_follow_up": "inspect available focus ids, then call set_focus with a valid focus_id and reason",
            },
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent focus action is schema-validated"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _stage_context(resources: dict[str, Any]) -> CreateAgentStageContext:
    return CreateAgentStageContext.from_workspace_root(_workspace(resources).root)


def _requested_focus_id(arguments: dict[str, Any]) -> str:
    value = str(arguments.get("focus_id") or arguments.get("system_id") or "").strip()
    if not value:
        raise ValueError("focus_id must be provided")
    return value


def _reason(arguments: dict[str, Any]) -> str:
    value = str(arguments.get("reason") or arguments.get("summary") or "").strip()
    if not value:
        raise ValueError("reason must be provided")
    return value


def _active_stage(state: SystemManufacturingState):
    active = state.active_stage()
    if active is None:
        raise ValueError("no active focus")
    return active


def _known_stage(state: SystemManufacturingState, focus_id: str):
    for stage in state.stages:
        if stage.system_id == focus_id:
            return stage
    raise ValueError(f"unknown focus_id: {focus_id}")


def _output(*, action: str, message: str, state: SystemManufacturingState, workspace: CreateAgentWorkspace) -> dict[str, Any]:
    active = state.active_stage()
    return {
        "action": action,
        "message": message,
        "state": state.working_set(),
        "active_focus": active.to_digest() if active else None,
        "task_analysis": _task_analysis_digest(workspace),
        "latest_validation": _latest_validation_digest(workspace=workspace, state=state),
        "updated_at": datetime.now(UTC).isoformat(),
        "warnings": _stage_warnings(workspace=workspace, state=state),
        "manufacturing_guidance": _manufacturing_guidance(active, workflow_kind=state.workflow_kind),
    }


def _manufacturing_guidance(active: Any, *, workflow_kind: str) -> dict[str, Any]:
    focus_id = active.system_id if active else ""
    guidance: dict[str, Any] = {
        "workflow_kind": workflow_kind,
        "baseline_package_is_scaffolded": workflow_kind == "manufacture",
        "existing_package_is_baseline": workflow_kind == "evolution",
        "focus_files_are_advisory": True,
    }
    if focus_id == "capability_implementation":
        guidance["next_action_hint"] = "write a coherent capability increment, then validate"
    elif focus_id == "requirement_focus":
        guidance["next_action_hint"] = "collect missing user-confirmed facts or set package identity"
    elif focus_id == "experience_assembly":
        guidance["next_action_hint"] = "bind implemented capabilities to the selected runtime pattern"
    elif focus_id == "validation_publish":
        guidance["next_action_hint"] = "run full_static validation, then finalize to mark the package publish-ready"
    return guidance


def _task_analysis_digest(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    task = workspace.read_task_analysis()
    payload = task.model_dump(mode="json")
    digest = {
        "version": payload.get("version", ""),
        "selected_pattern_id": task.selected_pattern_id,
        "resource_requirements": payload.get("resource_requirements", [])[:8],
    }
    if payload.get("version") == "evolution_task_analysis.v0":
        digest.update(
            {
                "goal_summary": payload.get("goal_summary", ""),
                "affected_systems": payload.get("affected_systems", [])[:8],
                "capability_changes": payload.get("capability_changes", [])[:8],
                "preserved_systems": payload.get("preserved_systems", [])[:8],
            }
        )
    else:
        digest.update(
            {
                "requires_dynamic_plan": payload.get("requires_dynamic_plan", False),
                "intent_summary": payload.get("intent_summary", ""),
                "capability_goals": payload.get("capability_goals", [])[:8],
            }
        )
    return digest


def _latest_validation_digest(*, workspace: CreateAgentWorkspace, state: SystemManufacturingState) -> dict[str, Any] | None:
    try:
        validation = workspace.read_validation()
    except Exception as exc:
        return {
            "readable": False,
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
    active = state.active_stage()
    if validation is None:
        return None
    digest = validation.to_digest().model_dump(mode="json")
    expected_scope = active.validation_focus if active else ""
    digest["active_focus_id"] = active.system_id if active else ""
    digest["expected_validation_focus"] = expected_scope
    digest["covers_active_focus"] = validation.validation_scope in {expected_scope, "full_static"}
    digest["use_this_instead_of_private_validation_file"] = True
    return digest


def _stage_warnings(*, workspace: CreateAgentWorkspace, state: SystemManufacturingState) -> list[dict[str, Any]]:
    try:
        validation = workspace.read_validation()
    except Exception as exc:
        return [
            {
                "kind": "validation_evidence_unreadable",
                "message": f"Latest validation evidence could not be read: {type(exc).__name__}: {exc}",
                "latest_validation_scope": "",
                "latest_validation_status": "unreadable",
                "active_focus_id": state.active_focus_id,
            }
        ]
    active = state.active_stage()
    if validation is None or active is None:
        return []
    warnings: list[dict[str, Any]] = []
    if validation.status != "passed":
        warnings.append(
            {
                "kind": "validation_not_passed_for_current_focus",
                "message": "Latest validation is not passed; focus changes are advisory and should be reconciled with validator evidence.",
                "latest_validation_scope": validation.validation_scope,
                "latest_validation_status": validation.status,
                "active_focus_id": active.system_id,
            }
        )
    expected_scope = active.validation_focus
    covered = validation.validation_scope in {expected_scope, "full_static"}
    if validation.status == "passed" and not covered:
        warnings.append(
            {
                "kind": "validation_scope_does_not_cover_current_focus",
                "message": "Latest validation passed, but it did not validate the active focus scope.",
                "latest_validation_scope": validation.validation_scope,
                "expected_validation_focus": expected_scope,
                "latest_validation_status": validation.status,
                "active_focus_id": active.system_id,
            }
        )
    return warnings
