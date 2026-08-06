from __future__ import annotations

from typing import Any

from agent_factory.tooling.skills.skill_tool_actions import SkillToolActionRunner
from agent_factory.tooling.skills.skill_tool_protocol import (
    SKILL_ACTIONS,
    SKILL_GATEWAY_STATE_RESOURCE_KEY,
    SKILL_RESOURCE_KEY,
    SKILL_TOOL_ID,
)
from agent_factory.tooling.skills.skill_tool_risk import evaluate_skill_tool_risk
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def build_skill_tool_spec(
    *,
    persist_gateway_state: bool = False,
    stage_context_resource: str | None = None,
) -> ToolSpec:
    tool_resources = {SKILL_RESOURCE_KEY: SKILL_RESOURCE_KEY}
    if persist_gateway_state:
        tool_resources[SKILL_GATEWAY_STATE_RESOURCE_KEY] = SKILL_GATEWAY_STATE_RESOURCE_KEY
    if stage_context_resource:
        tool_resources[stage_context_resource] = stage_context_resource
    return ToolSpec(
        id=SKILL_TOOL_ID,
        description=_tool_description(),
        entrypoint="agent_factory.tooling.skills.skill_tool:run",
        input_schema=_input_schema(),
        output_schema=_output_schema(),
        resources=tool_resources,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.tooling.skills.skill_tool:evaluate_risk"),
        concurrent=True,
        permission_scope="extension",
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    return tool_envelope(SkillToolActionRunner(resources).run(arguments))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return evaluate_skill_tool_risk(arguments, context)


def _input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(SKILL_ACTIONS),
                "description": (
                    "Skill Gateway action. Use describe before read_resource for the same current_system. "
                    "list/search/describe expose metadata only. "
                    "load returns SKILL.md for one tracked manufacturing focus. list_loaded returns loaded state. "
                    "read_resource reads one referenced skill resource or script source listed by describe/load. "
                    "read_repair_resources reads validator-recommended resources as a compact bundle."
                ),
            },
            "name": {
                "type": "string",
                "description": "Required for describe/load/read_resource. Do not pass this for list/search/list_loaded.",
            },
            "path": {
                "type": "string",
                "description": "Required only for read_resource.",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Required only for read_repair_resources. Use validator recommended_resources exactly.",
            },
            "mode": {
                "type": "string",
                "enum": ["outline", "fragment", "content"],
                "default": "outline",
                "description": (
                    "Optional for read_resource. outline returns a compact resource index; "
                    "fragment returns one JSON pointer subtree; content returns raw text only for non-schema resources "
                    "or text script sources that have not already been read. Schema resources should use fragment."
                ),
            },
            "pointer": {
                "type": "string",
                "description": "JSON pointer required when read_resource mode is fragment, such as /properties/nodes.",
            },
            "current_system": {
                "type": "string",
                "description": "Required for describe/load/list_loaded/read_resource. Use the manufacturing focus or system id whose skill state should be tracked; it is advisory state, not a stage gate.",
            },
            "reason": {
                "type": "string",
                "description": "Required for load and full schema content reads. Explain why this skill/resource is needed.",
            },
            "query": {
                "type": "string",
                "description": "Required only for search. Searches enabled skill metadata and resource names.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "Optional search result limit. Defaults to 20.",
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"const": "list"}}, "required": ["action"]},
            {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
            {"properties": {"action": {"const": "describe"}}, "required": ["action", "name", "current_system"]},
            {"properties": {"action": {"const": "load"}}, "required": ["action", "name", "current_system", "reason"]},
            {"properties": {"action": {"const": "list_loaded"}}, "required": ["action", "current_system"]},
            {
                "properties": {"action": {"const": "read_resource"}},
                "required": ["action", "name", "path", "current_system"],
            },
            {
                "properties": {"action": {"const": "read_repair_resources"}},
                "required": ["action", "name", "paths", "current_system"],
            },
        ],
        "additionalProperties": False,
    }


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(SKILL_ACTIONS)},
            "message": {"type": "string"},
            "skills": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "skill": {"type": ["object", "null"], "additionalProperties": True},
            "resource": {"type": ["object", "null"], "additionalProperties": True},
            "loaded_state": {"type": ["object", "null"], "additionalProperties": True},
        },
        "required": ["action", "message", "skills", "skill", "resource", "loaded_state"],
        "additionalProperties": False,
    }


def _tool_description() -> str:
    lines = [
        "Skill Gateway for enabled skills using progressive disclosure.",
        (
            "Protocol: call action=describe for the target skill and current_system before action=read_resource. "
            "When validator provides recommended_skill/recommended_resources, prefer action=read_repair_resources "
            "with those exact paths instead of guessing individual resource paths. "
            "Use action=list/search/describe to inspect metadata before loading content. "
            "Use action=load with current_system and reason only when the current manufacturing context needs that SKILL.md body. "
            "Use action=list_loaded to inspect loaded state. "
            "Use action=read_resource with current_system only for resources or scripts explicitly listed by describe/load. "
            "read_resource defaults to a compact outline. Use mode=fragment for schema pointers. "
            "Use mode=content for capability examples, guidance, or script source inspection, not for scaffold audits. "
            "Full schema content is a last resort and requires a reason; repeated content reads return summaries."
        ),
        (
            "This gateway does not execute scripts directly. A skill script becomes executable capability only "
            "when it is exposed as a registered ToolSpec or wrapped by a dedicated allowed execution tool, "
            "so permission, risk approval, trace, and output validation still apply."
        ),
    ]
    lines.append("Call action=list or action=search to inspect available skills.")
    return "\n".join(lines)
