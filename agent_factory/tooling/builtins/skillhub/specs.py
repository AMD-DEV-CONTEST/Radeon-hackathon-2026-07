from __future__ import annotations

from agent_factory.tooling.skillhub.constants import SKILLHUB_RUNTIME_RESOURCE
from agent_factory.tooling.skillhub.search_query import (
    SKILLHUB_SEARCH_QUERY_MAX_CHARS,
    SKILLHUB_SEARCH_QUERY_PATTERN,
)
from agent_factory.tooling.spec import ToolOutputCompressionActionConfig, ToolOutputCompressionConfig, ToolRiskEvaluatorConfig, ToolSpec


def get_skillhub_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skillhub",
            description=(
                "Searches SkillHUB, checks global SkillHUB CLI status, or installs/removes a SkillHUB skill "
                "for the current Agent extension directory."
            ),
            entrypoint="agent_factory.tooling.builtins.skillhub.skillhub:run",
            input_schema=_input_schema(),
            output_schema=_output_schema(),
            resources={"skillhub": SKILLHUB_RUNTIME_RESOURCE},
            risk_level="high",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.skillhub.skillhub:evaluate_risk",
            ),
            concurrent=False,
            output_compression=_output_compression(),
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["status", "search", "install", "remove"]},
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": SKILLHUB_SEARCH_QUERY_MAX_CHARS,
                "pattern": SKILLHUB_SEARCH_QUERY_PATTERN,
                "description": (
                    "Used only with action=search. Supply one to three short keywords or an exact skill name, "
                    "not a sentence, requirement description, or synonym pile. Split broad exploration into "
                    "multiple searches with a few high-signal terms, for example frontend, design, frontend "
                    "design, ppt, or web."
                ),
                "examples": ["frontend", "design", "frontend design", "ppt", "web"],
            },
            "skill": {
                "type": "string",
                "description": "SkillHUB skill name for action=install or action=remove.",
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"const": "status"}}, "required": ["action"]},
            {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
            {"properties": {"action": {"const": "install"}}, "required": ["action", "skill"]},
            {"properties": {"action": {"const": "remove"}}, "required": ["action", "skill"]},
        ],
    }


def _output_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "action": {"type": "string"},
            "status": {"type": "string"},
            "message": {"type": "string"},
            "cli_available": {"type": "boolean"},
            "cli_path": {"type": "string"},
            "cli_version": {"type": "string"},
            "extension_root": {"type": "string"},
            "skills_dir": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "raw_output": {"type": "string"},
            "installed_skill": {"type": ["object", "null"], "additionalProperties": True},
            "removed_skill": {"type": ["object", "null"], "additionalProperties": True},
            "restart_required": {"type": "boolean"},
        },
    }


def _output_compression() -> ToolOutputCompressionConfig:
    return ToolOutputCompressionConfig(
        action_argument="action",
        actions={
            "status": ToolOutputCompressionActionConfig(
                schema=_status_compression_schema(),
                prompt=_skillhub_action_prompt("Keep CLI availability, path, version, extension root, and skills directory."),
            ),
            "search": ToolOutputCompressionActionConfig(
                schema=_search_compression_schema(),
                prompt=_skillhub_action_prompt(
                    "Compress SkillHUB search results into candidates. Preserve every candidate install_name exactly. "
                    "Do not merge install_name with version, title, summary, or punctuation. "
                    "Keep the highest-signal candidates for the query and include their version and short summary."
                ),
            ),
            "install": ToolOutputCompressionActionConfig(
                schema=_install_compression_schema(),
                prompt=_skillhub_action_prompt(
                    "Compress SkillHUB install output. Preserve installed_skill.skill_id and path exactly. "
                    "If installation failed, preserve the exact error text."
                ),
            ),
            "remove": ToolOutputCompressionActionConfig(
                schema=_remove_compression_schema(),
                prompt=_skillhub_action_prompt(
                    "Compress SkillHUB remove output. Preserve removed_skill.skill_id, removed paths, and missing paths exactly."
                ),
            ),
        },
    )


def _skillhub_action_prompt(action_prompt: str) -> str:
    return (
        "This is SkillHUB output. Preserve machine-installable skill names exactly. "
        "Never concatenate a skill name with its version. If a search candidate has install_name, "
        "copy that install_name verbatim and use it as the only value to pass to action=install. "
        + action_prompt
    )


def _status_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "cli_available": {"type": "boolean"},
            "cli_path": {"type": "string"},
            "cli_version": {"type": "string"},
            "extension_root": {"type": "string"},
            "skills_dir": {"type": "string"},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "cli_available",
            "cli_path",
            "cli_version",
            "extension_root",
            "skills_dir",
            "insufficient",
            "read_original_reason",
        ],
    }


def _search_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "query": {"type": "string"},
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "install_name": {"type": "string"},
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "summary": {"type": "string"},
                        "score": {"type": "integer"},
                    },
                    "required": ["install_name", "name", "version", "summary", "score"],
                },
            },
            "selection_guidance": {"type": "string"},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "query",
            "candidates",
            "selection_guidance",
            "insufficient",
            "read_original_reason",
        ],
    }


def _install_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "installed": {"type": "boolean"},
            "installed_skill_id": {"type": "string"},
            "installed_skill_path": {"type": "string"},
            "restart_required": {"type": "boolean"},
            "errors": {"type": "array", "items": {"type": "string"}},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "installed",
            "installed_skill_id",
            "installed_skill_path",
            "restart_required",
            "errors",
            "insufficient",
            "read_original_reason",
        ],
    }


def _remove_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "removed_skill_id": {"type": "string"},
            "removed_paths": {"type": "array", "items": {"type": "string"}},
            "missing_paths": {"type": "array", "items": {"type": "string"}},
            "restart_required": {"type": "boolean"},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "removed_skill_id",
            "removed_paths",
            "missing_paths",
            "restart_required",
            "insufficient",
            "read_original_reason",
        ],
    }
