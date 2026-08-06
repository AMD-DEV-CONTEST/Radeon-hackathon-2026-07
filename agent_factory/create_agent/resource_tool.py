from __future__ import annotations

from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.resource_contract import load_resource_descriptors
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_contracts.schema import ResourceDescriptor
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_RESOURCE_TOOL_ID = "create_agent_resource"


def build_create_agent_resource_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_RESOURCE_TOOL_ID,
        description=(
            "Inspect or securely configure declared runtime Resources during manufacturing. Use action='put' only "
            "when the user has explicitly supplied the complete value in the conversation. Never invent missing "
            "credentials, API keys, account details, endpoints, or defaults. Stored values are schema-validated and "
            "encrypted; tool observations never return the value."
        ),
        entrypoint="agent_factory.create_agent.resource_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "put"]},
                "resource_id": {"type": "string", "minLength": 1},
                "value": {},
            },
            "required": ["action"],
            "allOf": [
                {
                    "if": {"properties": {"action": {"const": "put"}}, "required": ["action"]},
                    "then": {"required": ["resource_id", "value"]},
                }
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "put"]},
                "message": {"type": "string"},
                "resource_id": {"type": "string"},
                "configured": {"type": "boolean"},
                "updated_at": {"type": "string"},
                "resources": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "required": ["action", "message"],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.resource_tool:evaluate_risk"),
        concurrent=False,
        sensitive_argument_paths=["/value"],
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    descriptors = load_resource_descriptors(workspace)
    store = ResourceStore()
    action = str(arguments.get("action") or "").strip()
    if action == "status":
        statuses = store.status(workspace.root.name, descriptors)
        return tool_envelope(
            {
                "action": action,
                "message": "Runtime Resource configuration status loaded.",
                "resources": statuses,
            }
        )
    if action != "put":
        raise ValueError("action must be one of: status, put")
    resource_id = str(arguments.get("resource_id") or "").strip()
    descriptor = _descriptor(descriptors, resource_id)
    result = store.put(workspace.root.name, descriptor, arguments.get("value"))
    return tool_envelope(
        {
            "action": action,
            "message": "Runtime Resource was schema-validated and stored securely.",
            **result,
        }
    )


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action not in {"status", "put"}:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=["invalid create-agent Resource action"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent Resource access is constrained by the declared descriptor and encrypted store"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _descriptor(descriptors: list[ResourceDescriptor], resource_id: str) -> ResourceDescriptor:
    for descriptor in descriptors:
        if descriptor.resource_id == resource_id:
            return descriptor
    raise ValueError(f"runtime Resource is not declared by the package: {resource_id}")
