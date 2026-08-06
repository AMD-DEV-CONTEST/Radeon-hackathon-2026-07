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
TOOL_ID = "agent_team"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "start":
        output = _start(arguments, resources)
    elif action == "cancel":
        output = _cancel(arguments, resources)
    else:
        raise ValueError(f"unsupported agent_team action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"start", "cancel"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["team delegation starts or cancels multiple independent Agent runs"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]
    ).model_dump(mode="json")


def _start(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    tasks = _normalized_tasks(arguments.get("tasks"))
    ordered_tasks = _topological_tasks(tasks)
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    repository = AgentPackageRepository.from_paths()
    for item in tasks:
        if item["package_id"] == parent.package_id:
            raise ValueError("agent_team cannot assign the current Agent as its own worker")
        repository.load(item["package_id"])
    client = background_task_client(resources)
    call_id = background_task_request_id(tool_id=TOOL_ID)
    task_ids = {
        item["task_key"]: task_id_for_request(parent.session_id, f"{call_id}:{item['task_key']}")
        for item in tasks
    }
    created = []
    for item in ordered_tasks:
        task_id = task_ids[item["task_key"]]
        user_config = runtime_user_config(resources)
        user_config["delegation_context"] = {
            "task_id": task_id,
            "parent_session_id": parent.session_id,
            "parent_workspace_root": str(parent.workspace_root),
            "child_package_id": item["package_id"],
            "delivery_protocol": DELIVERY_PROTOCOL,
        }
        task = client.submit(
            parent.task_owner(),
            type="sub_agent",
            request_id=f"{call_id}:{item['task_key']}",
            task_text=item["task"],
            assignee_package_id=item["package_id"],
            payload={"user_config": user_config},
            depends_on=[task_ids[key] for key in item["depends_on"]],
            delivery_standard={
                "output_path": PROTOCOL_OUTPUT_PATH,
                "acceptance_criteria": item["acceptance_criteria"],
            },
            visible_context={
                "team_title": _required_text(arguments, "title"),
                "task_key": item["task_key"],
                "delivery_protocol": DELIVERY_PROTOCOL,
                "expected_artifacts": item["expected_artifacts"],
                "parent_context": item["context"],
            },
        )
        created.append(task)
    return {
        "action": "start",
        "status": "queued",
        "tasks": [
            {
                "task_key": item["task_key"],
                "task_id": task_ids[item["task_key"]],
                "package_id": item["package_id"],
                "depends_on": [task_ids[key] for key in item["depends_on"]],
            }
            for item in tasks
        ],
        "message": f"{len(created)} child-Agent tasks entered the unified background queue.",
        "next_step": "Briefly summarize the member assignments to the user, then end this turn and wait for active member updates. Do not call background_tasks to query progress.",
    }


def _cancel(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    task_ids = _string_list(arguments.get("task_ids"))
    if not task_ids:
        raise ValueError("agent_team cancel requires task_ids")
    reason = str(arguments.get("reason") or "The primary Agent cancelled the team tasks.").strip()
    client = background_task_client(resources)
    tasks = [
        client.cancel_owned(parent.session_id, task_id, reason=reason)
        for task_id in task_ids
    ]
    return {
        "action": "cancel",
        "status": "cancelling"
        if any(task.status == "cancelling" for task in tasks)
        else "cancelled",
        "task_ids": [task.task_id for task in tasks],
        "message": reason,
    }


def _normalized_tasks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("agent_team requires at least two tasks")
    tasks: list[dict[str, Any]] = []
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("agent_team task must be an object")
        task_key = _required_text(item, "task_key")
        if task_key in keys:
            raise ValueError(f"duplicate team task_key: {task_key}")
        keys.add(task_key)
        criteria = _string_list(item.get("acceptance_criteria"))
        if not criteria:
            raise ValueError(f"team task {task_key} requires acceptance_criteria")
        tasks.append(
            {
                "task_key": task_key,
                "package_id": _required_text(item, "package_id"),
                "task": _required_text(item, "task"),
                "acceptance_criteria": criteria,
                "depends_on": _string_list(item.get("depends_on")),
                "expected_artifacts": _artifact_expectations(item.get("expected_artifacts")),
                "context": item.get("context") if isinstance(item.get("context"), dict) else {},
            }
        )
    missing = sorted(
        dependency
        for item in tasks
        for dependency in item["depends_on"]
        if dependency not in keys
    )
    if missing:
        raise ValueError("unknown team task dependencies: " + ", ".join(missing))
    return tasks


def _topological_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {item["task_key"]: item for item in tasks}
    pending = set(by_key)
    ordered: list[dict[str, Any]] = []
    completed: set[str] = set()
    while pending:
        ready = sorted(key for key in pending if set(by_key[key]["depends_on"]) <= completed)
        if not ready:
            raise ValueError("agent_team task dependency graph contains a cycle")
        for key in ready:
            ordered.append(by_key[key])
            completed.add(key)
            pending.remove(key)
    return ordered


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
