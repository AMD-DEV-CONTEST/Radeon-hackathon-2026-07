from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.parent_controller import background_task_client
from agent_factory.collaboration_system.result_delivery import DELIVERY_PROTOCOL, commit_agent_result
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    context, identity = _delegation_identity(resources)
    task_id = _required_text(context, "task_id")
    package_id = _required_text(context, "child_package_id")
    session_id = _required_text(identity, "session_id")
    client = background_task_client(resources)
    task = client.tasks.get(task_id)
    _validate_child_identity(task, package_id=package_id, session_id=session_id)
    existing_delivery = task.result.get("delivery") if isinstance(task.result, dict) else None
    if isinstance(existing_delivery, dict) and existing_delivery.get("protocol") == DELIVERY_PROTOCOL:
        output = {
            "status": "already_delivered",
            "task_id": task_id,
            "delivery": existing_delivery,
            "artifacts": task.artifact_refs,
            "message": "This task was already formally delivered; the idempotent result is returned.",
        }
        return tool_envelope(output, summary=output["message"])
    if context.get("delivery_protocol") != DELIVERY_PROTOCOL:
        raise ValueError("current background task does not use the Agent delivery protocol")
    parent_workspace = Path(_required_text(context, "parent_workspace_root"))
    child_workspace = Path(_required_text(resources, "workdir_root"))
    status = _required_text(arguments, "status")
    summary = _required_text(arguments, "summary")
    commit = commit_agent_result(
        parent_workspace=parent_workspace,
        child_workspace=child_workspace,
        task_id=task_id,
        package_id=package_id,
        child_session_id=session_id,
        status=status,
        summary=summary,
        artifacts=_artifact_list(arguments.get("artifacts")),
        key_findings=_string_list(arguments.get("key_findings")),
        remaining_issues=_string_list(arguments.get("remaining_issues")),
        recommended_next_actions=_string_list(arguments.get("recommended_next_actions")),
    )
    delivery = {
        "protocol": DELIVERY_PROTOCOL,
        "delivery_id": commit.delivery_id,
        "bundle_path": commit.bundle_path,
        "reported_status": status,
        "summary": summary,
        "key_findings": _string_list(arguments.get("key_findings")),
        "remaining_issues": _string_list(arguments.get("remaining_issues")),
        "recommended_next_actions": _string_list(arguments.get("recommended_next_actions")),
    }
    client.record_child_delivery(
        task_id,
        assignee_package_id=package_id,
        assignee_session_id=session_id,
        result_summary=summary,
        result={"delivery": delivery},
        artifact_refs=commit.artifact_refs,
    )
    output = {
        "status": "delivered",
        "task_id": task_id,
        "delivery": delivery,
        "artifacts": commit.artifact_refs,
        "message": "Delivery was written transactionally to the parent workspace and the structured report will be sent to the parent Agent.",
    }
    return tool_envelope(output, summary=output["message"])


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    if not str(arguments.get("summary") or "").strip():
        return ToolRiskResult(
            action="deny", risk_level="low", reasons=["deliver_result requires summary"]
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["delivery is scoped to the authenticated parent-child run relationship"],
    ).model_dump(mode="json")


def _delegation_identity(resources: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    execution = resources.get("runtime_execution_config")
    if not isinstance(execution, dict):
        raise ValueError("deliver_result requires runtime execution context")
    user_config = execution.get("user_config")
    identity = execution.get("identity")
    context = user_config.get("delegation_context") if isinstance(user_config, dict) else None
    if not isinstance(context, dict) or not isinstance(identity, dict):
        raise ValueError("deliver_result is only available in a delegated child run")
    return context, identity


def _validate_child_identity(task: Any, *, package_id: str, session_id: str) -> None:
    if task.assignee_session_id != session_id:
        raise PermissionError("delegated child session does not match the assigned task")
    if task.assignee_package_id != package_id:
        raise PermissionError("delegated child package does not match the assigned task")


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item or "").strip())))


def _artifact_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "path": str(item.get("path") or "").strip(),
            "description": str(item.get("description") or "").strip(),
        }
        for item in value
        if isinstance(item, dict)
    ]
