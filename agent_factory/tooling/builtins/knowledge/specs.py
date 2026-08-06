from __future__ import annotations

from agent_factory.knowledge_system.schema import KnowledgeToolInput
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_knowledge_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="knowledge",
            description=(
                "Queries and manages private knowledge mounted on the current Agent. Call it when the question "
                "depends on internal documents, project facts, product parameters, business rules, procedures, "
                "coding standards, historical material, or when the user explicitly asks for an answer based on "
                "a knowledge base, document, or policy. Do not answer solely from model memory. Search first "
                "(mode=auto by default), then open/read matched content as needed. Report no-result honestly and "
                "never fabricate knowledge content or claim a search that did not occur. To add a source, call "
                "prepare_source before confirm_source. For session attachments or workspace files, use a relative "
                "source.path or the logical /workdir path, never a host installation path."
            ),
            entrypoint="agent_factory.knowledge_system.tools:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                "knowledge_runtime": "knowledge_runtime",
                "workspace_root": "workspace_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.knowledge_system.tools:evaluate_risk",
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    schema = KnowledgeToolInput.model_json_schema()
    schema["oneOf"] = [
        {"properties": {"action": {"enum": ["list_sources"]}}, "required": ["action"]},
        {
            "properties": {
                "action": {"enum": ["prepare_source", "confirm_source"]},
                "source": {"$ref": "#/$defs/KnowledgeSourceInput"},
            },
            "required": ["action", "source"],
        },
        {"properties": {"action": {"enum": ["describe_source", "reindex", "remove_source"]}}, "required": ["action", "source_id"]},
        {"properties": {"action": {"const": "list_documents"}}, "required": ["action"]},
        {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
        {"properties": {"action": {"enum": ["open", "read"]}}, "required": ["action"]},
    ]
    return schema
