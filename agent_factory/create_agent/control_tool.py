from __future__ import annotations

from typing import Any

from agent_factory.create_agent.models import CreateAgentAction
from agent_factory.create_agent.output_safety import looks_like_internal_observation_text
from agent_factory.create_agent.resource_contract import resource_request_payloads
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_CONTROL_TOOL_ID = "create_agent_control"
CREATE_AGENT_WORKSPACE_RESOURCE = "create_agent_workspace"


def build_create_agent_control_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_CONTROL_TOOL_ID,
        description=(
            "Control the create-agent authoring loop for manufacturing or evolution. Use this instead of editing "
            ".factory/action.json directly when asking the user, continuing, or finalizing. "
            "Whenever the response needs a user choice, confirmation, authorization, or missing information, "
            "call action='ask_user' in that same response; plain assistant text does not count as asking the user."
        ),
        entrypoint="agent_factory.create_agent.control_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["inspect", "continue", "ask_user", "finalize"],
                    "description": "The next create-agent control action.",
                },
                "message": {
                    "type": "string",
                    "description": "Natural-language user question or finalization summary.",
                },
                "resource_facts": {
                    "type": "array",
                    "items": _resource_fact_schema(),
                    "default": [],
                    "description": "Optional resource facts already established by the conversation.",
                },
                "resource_requests": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "resource_id": {"type": "string"},
                            "description": {"type": "string"},
                            "secret": {"type": "boolean"},
                        },
                        "required": ["resource_id"],
                        "additionalProperties": False,
                    },
                    "default": [],
                    "description": (
                        "Resources to render as schema forms. Every resource_id must already be declared with a "
                        "non-empty value_schema in contracts/resources.json before ask_user is called."
                    ),
                },
            },
            "required": ["action"],
            "oneOf": [
                {"properties": {"action": {"const": "inspect"}}, "required": ["action"]},
                {"properties": {"action": {"const": "continue"}}, "required": ["action"]},
                {"properties": {"action": {"const": "ask_user"}}, "required": ["action", "message"]},
                {"properties": {"action": {"const": "finalize"}}, "required": ["action"]},
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["inspect", "continue", "ask_user", "finalize"]},
                "message": {"type": "string"},
                "action_path": {"type": "string"},
                "resource_fact_count": {"type": "integer"},
                "current_action": {"type": "object", "additionalProperties": True},
                "publish_decision": {"type": "object", "additionalProperties": True},
            },
            "required": ["action", "message", "action_path", "resource_fact_count"],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.control_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    requested_action = str(arguments.get("action") or "").strip()
    if requested_action == "inspect":
        current_action = workspace.read_action()
        publish_decision = workspace.read_publish_decision()
        return tool_envelope({
            "action": "inspect",
            "message": "Current create-agent control state.",
            "action_path": str(workspace.action_path),
            "resource_fact_count": len(current_action.resource_facts),
            "current_action": current_action.model_dump(mode="json"),
            "publish_decision": publish_decision.model_dump(mode="json"),
        })
    action = CreateAgentAction.model_validate(
        {
            "action": requested_action,
            "message": str(arguments.get("message") or "").strip(),
            "resource_facts": arguments.get("resource_facts") or [],
            "resource_requests": arguments.get("resource_requests") or [],
        }
    )
    if action.action == "ask_user" and not action.message.strip():
        raise ValueError("message is required when action is ask_user")
    if action.resource_requests and action.action != "ask_user":
        raise ValueError("resource_requests are only valid when action is ask_user")
    if action.action == "ask_user":
        resource_request_payloads(workspace, action.resource_requests)
    if action.action == "finalize" and looks_like_internal_observation_text(action.message):
        raise ValueError("finalize message must be a concise user-facing summary, not raw tool/probe JSON")
    workspace.write_action(action)
    return tool_envelope({
        "action": action.action,
        "message": action.message,
        "action_path": str(workspace.action_path),
        "resource_fact_count": len(action.resource_facts),
    })


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        action = str(arguments.get("action") or "").strip()
        if action not in {"inspect", "continue", "ask_user", "finalize"}:
            raise ValueError("action must be one of: inspect, continue, ask_user, finalize")
        if action == "inspect":
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["create-agent control inspect is read-only"],
                facts={"action": action},
            ).model_dump(mode="json")
        message = str(arguments.get("message") or "").strip()
        if action == "ask_user" and not message:
            raise ValueError("message is required when action is ask_user")
        if action == "finalize" and looks_like_internal_observation_text(message):
            raise ValueError("finalize message must be a concise user-facing summary, not raw tool/probe JSON")
        CreateAgentAction.model_validate(
            {
                "action": action,
                "message": message,
            "resource_facts": arguments.get("resource_facts") or [],
            "resource_requests": arguments.get("resource_requests") or [],
            }
        )
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent control action: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent control action is schema-validated"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _resource_fact_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {},
            "secret": {"type": "boolean", "default": False},
            "source": {
                "type": "string",
                "enum": ["user", "tool", "mcp", "skill", "default", "system"],
                "default": "user",
            },
            "confidence": {"type": "number", "default": 1.0},
            "evidence_refs": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["key"],
        "additionalProperties": False,
    }
