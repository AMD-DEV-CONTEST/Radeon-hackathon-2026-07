from __future__ import annotations

from typing import Any

from agent_factory.collaboration_system.parent_controller import (
    background_task_client,
    background_task_request_id,
    parent_agent_context,
    runtime_user_config,
)
from agent_factory.collaboration_system.result_delivery import DELIVERY_PROTOCOL
from agent_factory.collaboration_system.task_client import task_id_for_request
from agent_factory.factory_graph.frontend_bridge.agent_package_repository import AgentPackageRepository
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


PROTOCOL_OUTPUT_PATH = ".agent_delivery/result.json"
TOOL_ID = "agent_delegate"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "start":
        output = _start(arguments, resources)
    elif action == "cancel":
        output = _cancel(arguments, resources)
    else:
        raise ValueError(f"unsupported agent_delegate action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"start", "cancel"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["delegation starts or cancels an independent Agent run"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]
    ).model_dump(mode="json")


def _start(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    task_text = _required_text(arguments, "task")
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    package_id = _required_text(arguments, "package_id")
    if package_id == parent.package_id:
        raise ValueError("agent_delegate cannot delegate a task back to the current Agent")
    AgentPackageRepository.from_paths().load(package_id)
    criteria = _string_list(arguments.get("acceptance_criteria"))
    if not criteria:
        raise ValueError("acceptance_criteria must contain at least one item")
    expected_artifacts = _artifact_expectations(arguments.get("expected_artifacts"))
    request_id = background_task_request_id(tool_id=TOOL_ID)
    task_id = task_id_for_request(parent.session_id, request_id)
    user_config = runtime_user_config(resources)
    user_config["delegation_context"] = {
        "task_id": task_id,
        "parent_session_id": parent.session_id,
        "parent_workspace_root": str(parent.workspace_root),
        "child_package_id": package_id,
        "delivery_protocol": DELIVERY_PROTOCOL,
    }
    task = background_task_client(resources).submit(
        parent.task_owner(),
        type="sub_agent",
        request_id=request_id,
        task_text=task_text,
        assignee_package_id=package_id,
        payload={"user_config": user_config},
        delivery_standard={
            "output_path": PROTOCOL_OUTPUT_PATH,
            "acceptance_criteria": criteria,
        },
        visible_context={
            "delivery_protocol": DELIVERY_PROTOCOL,
            "expected_artifacts": expected_artifacts,
            "parent_context": arguments.get("context")
            if isinstance(arguments.get("context"), dict)
            else {},
        },
    )
    return {
        "action": "start",
        "status": task.status,
        "task_id": task.task_id,
        "package_id": package_id,
        "child_session_id": task.assignee_session_id,
        "message": f"The task was delegated asynchronously to {package_id}; delivery will notify this session.",
        "next_step": "Briefly tell the user what started and who owns it, then end this turn and wait for active updates. Do not query background-task progress.",
    }


def _cancel(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    task_id = _required_text(arguments, "task_id")
    reason = str(arguments.get("reason") or "The primary Agent cancelled the delegated task.").strip()
    task = background_task_client(resources).cancel_owned(
        parent.session_id,
        task_id,
        reason=reason,
    )
    return {
        "action": "cancel",
        "status": task.status,
        "task_id": task.task_id,
        "message": reason if task.status in {"cancelling", "cancelled"} else "The task has already finished.",
    }


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item or "").strip())))


def _artifact_expectations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "description": str(item.get("description") or "").strip(),
            **(
                {"suggested_name": suggested}
                if (suggested := str(item.get("suggested_name") or "").strip())
                else {}
            ),
        }
        for item in value
        if isinstance(item, dict) and str(item.get("description") or "").strip()
    ]
