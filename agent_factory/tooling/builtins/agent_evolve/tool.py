from __future__ import annotations

from typing import Any

from agent_factory.collaboration_system.parent_controller import (
    background_task_client,
    background_task_request_id,
    parent_agent_context,
    runtime_user_config,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_repository import AgentPackageRepository
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


TOOL_ID = "agent_evolve"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "start":
        output = _start(arguments, resources)
    elif action == "respond":
        output = _respond(arguments, resources)
    elif action == "cancel":
        output = _cancel(arguments, resources)
    else:
        raise ValueError(f"unsupported agent_evolve action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"start", "respond", "cancel"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["Agent evolution mutates a published package or its active evolution state"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]
    ).model_dump(mode="json")


def _start(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    package_id = _required_text(arguments, "package_id")
    if package_id == parent.package_id:
        raise ValueError("agent_evolve cannot evolve the currently running parent Agent")
    repository = AgentPackageRepository.from_paths()
    manifest_path = repository.manifest_path(package_id)
    repository.load_manifest(manifest_path)
    if repository.package_origin(manifest_path) != "user":
        raise ValueError("built-in Agent packages cannot be evolved")
    goal = _required_text(arguments, "goal")
    constraints = _string_list(arguments.get("constraints"))
    request_id = background_task_request_id(tool_id=TOOL_ID)
    task = background_task_client(resources).submit(
        parent.task_owner(),
        type="evolve",
        request_id=request_id,
        task_text=_evolution_goal(goal, constraints),
        assignee_package_id=package_id,
        payload={
            "goal": goal,
            "constraints": constraints,
            "user_config": runtime_user_config(resources),
        },
        visible_context={
            "goal": goal,
            "constraints": constraints,
        },
    )
    return {
        "action": "start",
        "status": task.status,
        "task_id": task.task_id,
        "package_id": package_id,
        "message": f"Evolution of {package_id} entered the unified background-task queue.",
        "next_step": "Briefly tell the user that evolution started, then end this turn and wait for active updates. Do not query background-task progress.",
    }


def _respond(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    client = background_task_client(resources)
    task_id = _required_text(arguments, "task_id")
    task = client.owned_task(parent.session_id, task_id)
    decision = str(arguments.get("decision") or "").strip()
    response = str(arguments.get("response") or "").strip()
    if task.status == "waiting_approval":
        if decision not in {"approve", "deny", "revise"}:
            raise ValueError("waiting approval requires decision=approve, deny, or revise")
        task = client.approve_owned(
            parent.session_id,
            task_id,
            decision=decision,
            payload={"response": response} if response else {},
        )
    elif task.status == "waiting_external":
        if not response:
            raise ValueError("waiting external input requires response")
        task = client.resume_owned(parent.session_id, task_id, payload={"response": response})
    else:
        raise ValueError("agent_evolve respond requires a waiting task")
    return {
        "action": "respond",
        "status": task.status,
        "task_id": task.task_id,
        "message": "The additional information was submitted to the original evolution task.",
    }


def _cancel(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    task_id = _required_text(arguments, "task_id")
    reason = str(arguments.get("reason") or "The primary Agent cancelled the evolution task.").strip()
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


def _evolution_goal(goal: str, constraints: list[str]) -> str:
    if not constraints:
        return goal
    return goal + "\n\nConstraints:\n- " + "\n- ".join(constraints)


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item or "").strip())))
