from __future__ import annotations

from typing import Any

from agent_factory.model_pool import ModelPoolSelector, ModelSelectionRequest
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_MODEL_POOL_TOOL_ID = "model_pool_select"


def build_model_pool_select_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_MODEL_POOL_TOOL_ID,
        description=(
            "Select runnable model profiles from the local model pool for the AgentPackage being manufactured. "
            "This is the first capability-assembly step after task analysis: run it before inherited MCP "
            "candidate evaluation, SkillHub search/install, and package tool authoring. Pass requirements for main/task/compression models, "
            "tool_requirements for auxiliary image/audio model tools, and an embedding requirement when the package uses RAG or semantic memory. "
            "Structural capabilities are hard constraints; each result also includes "
            "a ranked candidates list with every profile description. Inspect those descriptions against the requested purpose before choosing "
            "the final profile id; the first candidate is only the deterministic capability-based default. Never write provider credentials "
            "into the package."
        ),
        entrypoint="agent_factory.create_agent.model_pool_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["main", "task", "compression", "embedding"]},
                            "purpose": {"type": "string"},
                            "kind": {"type": "string", "enum": ["chat", "embedding", "image_generation"]},
                            "input_modalities": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["text", "image", "audio"]},
                            },
                            "output_modalities": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["text", "image", "audio"]},
                            },
                            "tool_calling": {"type": "boolean"},
                            "structured_output_methods": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["function_calling", "json_mode", "json_schema"]},
                            },
                            "reasoning_required": {"type": "boolean"},
                            "min_context_window_tokens": {"type": "integer", "minimum": 1},
                            "excluded_profile_ids": {"type": "array", "items": {"type": "string"}},
                            "optimize_for": {
                                "type": "string",
                                "enum": ["balanced", "quality", "cost", "latency", "context"],
                            },
                            "max_candidates": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["role"],
                        "additionalProperties": False,
                    },
                },
                "tool_requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool_id": {"type": "string"},
                            "capability": {
                                "type": "string",
                                "enum": ["image_input", "image_output", "image_edit", "audio_input", "audio_output"],
                            },
                            "purpose": {"type": "string"},
                            "min_context_window_tokens": {"type": "integer", "minimum": 1},
                            "excluded_profile_ids": {"type": "array", "items": {"type": "string"}},
                            "optimize_for": {
                                "type": "string",
                                "enum": ["balanced", "quality", "cost", "latency", "context"],
                            },
                            "max_candidates": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["tool_id", "capability"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "blocked"]},
                "recommendations": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "tool_recommendations": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "unmatched": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "profile_count": {"type": "integer"},
                "enabled_profile_count": {"type": "integer"},
            },
            "required": ["status", "recommendations", "tool_recommendations", "unmatched", "profile_count", "enabled_profile_count"],
            "additionalProperties": False,
        },
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.model_pool_tool:evaluate_risk"),
        concurrent=True,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    del resources
    request = ModelSelectionRequest.model_validate(arguments)
    result = ModelPoolSelector().select(request)
    summary = (
        "Model pool selection completed."
        if result.status == "completed"
        else "Model pool selection is blocked because no enabled profile satisfies one or more requirements."
    )
    return tool_envelope(result.model_dump(mode="json"), evidence={"model_selection": result.model_dump(mode="json")}, summary=summary)


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    try:
        ModelSelectionRequest.model_validate(arguments)
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid model pool selection request: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["model_pool_select is read-only and returns profile ids without secrets"],
    ).model_dump(mode="json")
