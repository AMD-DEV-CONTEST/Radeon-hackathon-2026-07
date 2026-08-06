from __future__ import annotations

from datetime import UTC, datetime

from agent_factory.create_agent.models import PackageValidationReport, SystemManufacturingState, SystemStageStatus
from agent_factory.create_agent.workspace import CreateAgentWorkspace


AUTHORING_STAGE_BY_ACTION: dict[str, str] = {
    "set_identity": "capability_implementation",
    "configure_model_bindings": "capability_implementation",
    "materialize_mcp_inheritance": "capability_implementation",
    "upsert_package_tool": "capability_implementation",
    "configure_dependencies": "capability_implementation",
    "remove_package_tool": "capability_implementation",
    "upsert_scheduler_seed": "capability_implementation",
    "upsert_resources": "capability_implementation",
    "upsert_knowledge_file": "capability_implementation",
    "remove_knowledge_file": "capability_implementation",
    "reset_contract": "capability_implementation",
    "configure_pattern_assembly": "experience_assembly",
}

VALIDATION_STAGE_BY_SCOPE: dict[str, str] = {
    "workspace_hygiene": "requirement_focus",
    "package_shape": "capability_implementation",
    "runtime_contract_build": "capability_implementation",
    "python_syntax": "capability_implementation",
    "assembly_compile": "experience_assembly",
    "full_static": "validation_publish",
}


def sync_authoring_stage(workspace: CreateAgentWorkspace, action: str) -> SystemManufacturingState:
    target = AUTHORING_STAGE_BY_ACTION.get(str(action or "").strip())
    if target is None:
        return workspace.read_system_state()
    return sync_stage(
        workspace,
        focus_id=target,
        status=SystemStageStatus.in_progress,
        invalidate_downstream=True,
    )


def sync_probe_stage(
    workspace: CreateAgentWorkspace,
    *,
    passed: bool,
    success_path: bool,
) -> SystemManufacturingState:
    if passed and success_path:
        return sync_stage(
            workspace,
            focus_id="validation_publish",
            status=SystemStageStatus.in_progress,
            invalidate_downstream=False,
        )
    if passed:
        return sync_stage(
            workspace,
            focus_id="capability_implementation",
            status=SystemStageStatus.in_progress,
            invalidate_downstream=True,
        )
    return sync_stage(
        workspace,
        focus_id="capability_implementation",
        status=SystemStageStatus.failed_needs_repair,
        invalidate_downstream=True,
    )


def sync_validation_stage(workspace: CreateAgentWorkspace, report: PackageValidationReport) -> SystemManufacturingState:
    target = VALIDATION_STAGE_BY_SCOPE.get(str(report.validation_scope or "").strip(), "validation_publish")
    if report.status == "passed":
        return sync_stage(
            workspace,
            focus_id=target,
            status=SystemStageStatus.in_progress,
            invalidate_downstream=False,
        )
    return sync_stage(
        workspace,
        focus_id=target,
        status=SystemStageStatus.failed_needs_repair,
        invalidate_downstream=True,
    )


def sync_publish_stage(workspace: CreateAgentWorkspace) -> SystemManufacturingState:
    return sync_stage(
        workspace,
        focus_id="validation_publish",
        status=SystemStageStatus.done,
        invalidate_downstream=False,
    )


def sync_stage(
    workspace: CreateAgentWorkspace,
    *,
    focus_id: str,
    status: SystemStageStatus,
    invalidate_downstream: bool,
) -> SystemManufacturingState:
    state = workspace.read_system_state()
    target = _known_stage_order(state, focus_id)
    stages = []
    for stage in state.stages:
        next_status = stage.status
        if stage.system_id == focus_id:
            next_status = status
        elif stage.stage_order < target:
            next_status = SystemStageStatus.done
        elif invalidate_downstream and stage.stage_order > target:
            next_status = SystemStageStatus.pending
        if next_status == stage.status:
            stages.append(stage)
        else:
            stages.append(stage.model_copy(update={"status": next_status}))
    updated = state.model_copy(
        update={
            "stages": stages,
            "active_focus_id": focus_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    workspace.write_system_state(updated)
    return updated


def _known_stage_order(state: SystemManufacturingState, focus_id: str) -> int:
    for stage in state.stages:
        if stage.system_id == focus_id:
            return stage.stage_order
    raise ValueError(f"unknown create-agent focus_id: {focus_id}")
