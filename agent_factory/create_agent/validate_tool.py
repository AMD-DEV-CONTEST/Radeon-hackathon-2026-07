from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.models import PackageValidationState
from agent_factory.create_agent.stage_sync import sync_validation_stage
from agent_factory.create_agent.validation_state import (
    changed_files,
    package_fingerprint,
    tool_probe_digest,
    validation_scope_for_focus,
)
from agent_factory.create_agent.validator import CreateAgentPackageValidator, ValidationScope
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_VALIDATE_TOOL_ID = "create_agent_validate"


def build_create_agent_validate_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_VALIDATE_TOOL_ID,
        description=(
            "Run create-agent package validation explicitly. Use after a complete capability increment, "
            "and use scope='full_static' before finalize/publish."
        ),
        entrypoint="agent_factory.create_agent.validate_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["current_focus", "full_static"],
                    "description": "Validate the current focus scope or the full static publish-readiness scope.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short reason for running validation now.",
                },
            },
            "required": ["scope", "reason"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "scope": {"type": "string"},
                "reason": {"type": "string"},
                "active_focus_id": {"type": "string"},
                "validation_path": {"type": "string"},
                "validation_state_path": {"type": "string"},
                "package_fingerprint": {"type": "object", "additionalProperties": {"type": "string"}},
                "probe_digest": {"type": "string"},
                "report": {"type": "object", "additionalProperties": True},
            },
            "required": [
                "scope",
                "reason",
                "active_focus_id",
                "validation_path",
                "validation_state_path",
                "package_fingerprint",
                "probe_digest",
                "report",
            ],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.validate_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    requested_scope = _requested_scope(arguments)
    reason = _reason(arguments)
    active = workspace.read_system_state().active_stage()
    active_focus_id = active.system_id if active else ""
    scope = _validation_scope(requested_scope=requested_scope, active_validation_focus=active.validation_focus if active else "")
    previous_state = workspace.read_validation_state()
    current_fingerprint = package_fingerprint(workspace.root)
    current_probe_digest = tool_probe_digest(workspace)
    changed = changed_files(previous_state.package_fingerprint if previous_state else {}, current_fingerprint)
    report = CreateAgentPackageValidator().validate(workspace.root, scope=scope, changed_files=changed)
    workspace.write_validation(report)
    synced_state = sync_validation_stage(workspace, report)
    synced_active = synced_state.active_stage()
    workspace.write_validation_state(
        PackageValidationState(
            package_fingerprint=current_fingerprint,
            probe_digest=current_probe_digest,
            validation_scope=report.validation_scope,
            active_focus_id=synced_active.system_id if synced_active else active_focus_id,
            updated_at=datetime.now(UTC).isoformat(),
        )
    )
    return tool_envelope(
        {
            "scope": requested_scope,
            "reason": reason,
            "active_focus_id": synced_active.system_id if synced_active else active_focus_id,
            "validation_path": str(workspace.validation_path),
            "validation_state_path": str(workspace.validation_state_path),
            "package_fingerprint": current_fingerprint,
            "probe_digest": current_probe_digest,
            "report": report.model_dump(mode="json"),
        },
        summary=f"Validation {report.status}: {report.validation_scope}. {report.summary}",
    )


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    try:
        scope = _requested_scope(arguments)
        reason = _reason(arguments)
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent validation request: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent validation is read-only for package files and writes managed validation state"],
        facts={"scope": scope, "reason": reason},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _requested_scope(arguments: dict[str, Any]) -> str:
    value = str(arguments.get("scope") or "").strip()
    if value not in {"current_focus", "full_static"}:
        raise ValueError("scope must be one of: current_focus, full_static")
    return value


def _reason(arguments: dict[str, Any]) -> str:
    value = str(arguments.get("reason") or "").strip()
    if not value:
        raise ValueError("reason is required")
    return value


def _validation_scope(*, requested_scope: str, active_validation_focus: str) -> ValidationScope:
    if requested_scope == "full_static":
        return "full_static"
    return validation_scope_for_focus(active_validation_focus)
