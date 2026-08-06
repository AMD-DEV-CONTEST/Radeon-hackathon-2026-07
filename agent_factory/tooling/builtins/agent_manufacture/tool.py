from __future__ import annotations

from typing import Any

from agent_factory.collaboration_system.parent_controller import (
    background_task_client,
    background_task_request_id,
    parent_agent_context,
    runtime_user_config,
)
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


TOOL_ID = "agent_manufacture"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    request_payload = _request_payload(arguments)
    parent = parent_agent_context(resources, tool_id=TOOL_ID)
    request_id = background_task_request_id(tool_id=TOOL_ID)
    task = background_task_client(resources).submit(
        parent.task_owner(),
        type="manufacture",
        request_id=request_id,
        task_text=_manufacturing_prompt(request_payload),
        payload={
            "request": request_payload,
            "user_config": runtime_user_config(resources),
        },
        delivery_standard={"requirements": request_payload["delivery_standards"]},
        visible_context={"source_agent_search": request_payload["source_agent_search"]},
    )
    output = {
        "status": task.status,
        "task_id": task.task_id,
        "create_agent_session_id": task.assignee_session_id,
        "message": "The manufacturing request entered the unified background-task queue and will notify this session when complete.",
        "next_step": "Briefly tell the user that manufacturing started, then end this turn and wait for active updates. Do not query progress. After publication, call agent_search for the new package_id.",
    }
    return tool_envelope(output, summary=output["message"])


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    missing = [
        key
        for key in (
            "agent_name",
            "purpose",
            "delivery_standards",
            "reason_existing_agents_insufficient",
        )
        if _is_empty(arguments.get(key))
    ]
    if missing:
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["missing required manufacturing fields: " + ", ".join(missing)],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="inherit",
        risk_level="medium",
        reasons=["agent manufacturing creates and publishes a new package"],
    ).model_dump(mode="json")


def _manufacturing_prompt(payload: dict[str, Any]) -> str:
    lines = [
        f"Manufacture Agent: {payload['agent_name']}",
        f"Purpose: {payload['purpose']}",
        f"Why existing Agents are insufficient: {payload['reason_existing_agents_insufficient']}",
    ]
    if payload["target_tasks"]:
        lines.append("Target tasks:\n- " + "\n- ".join(payload["target_tasks"]))
    lines.append("Delivery standards:\n- " + "\n- ".join(payload["delivery_standards"]))
    if payload["constraints"]:
        lines.append("Constraints:\n- " + "\n- ".join(payload["constraints"]))
    if payload["preferred_pattern"]:
        lines.append(f"Preferred runtime pattern: {payload['preferred_pattern']}")
    return "\n\n".join(lines)


def _request_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_name": _required_text(arguments, "agent_name"),
        "purpose": _required_text(arguments, "purpose"),
        "target_tasks": _string_list(arguments.get("target_tasks")),
        "delivery_standards": _required_string_list(arguments, "delivery_standards"),
        "reason_existing_agents_insufficient": _required_text(
            arguments, "reason_existing_agents_insufficient"
        ),
        "preferred_pattern": _optional_text(arguments.get("preferred_pattern")),
        "constraints": _string_list(arguments.get("constraints")),
        "source_agent_search": arguments.get("source_agent_search")
        if isinstance(arguments.get("source_agent_search"), dict)
        else {},
    }


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = _optional_text(arguments.get(key))
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item or "").strip())))


def _required_string_list(arguments: dict[str, Any], key: str) -> list[str]:
    result = _string_list(arguments.get(key))
    if not result:
        raise ValueError(f"{key} must contain at least one item")
    return result


def _is_empty(value: Any) -> bool:
    if isinstance(value, list):
        return not _string_list(value)
    return not str(value or "").strip()
