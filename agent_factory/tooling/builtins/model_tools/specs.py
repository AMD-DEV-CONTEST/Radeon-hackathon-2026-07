from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_factory.tooling.spec import ToolSpec


MODEL_TOOL_RUNTIME_RESOURCE = "model_tool_runtime"


def get_model_tool_specs(runtime_tools: Mapping[str, Any] | None) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for tool_id, runtime_tool in sorted((runtime_tools or {}).items()):
        capability = str(runtime_tool.get("capability") or "")
        if capability not in {"image_input", "image_output", "image_edit", "audio_input", "audio_output"}:
            raise ValueError(f"unsupported local model tool capability: {capability}")
        tool_resources = {"model_tool": f"{MODEL_TOOL_RUNTIME_RESOURCE}.{tool_id}"}
        if capability in {"image_output", "image_edit"}:
            tool_resources["workspace_root"] = "workspace_root"
        specs.append(
            ToolSpec(
                id=tool_id,
                description=_description(
                    capability=capability,
                    configured=str(runtime_tool.get("description") or ""),
                ),
                entrypoint="agent_factory.tooling.builtins.model_tools.model_tool:run",
                input_schema=_input_schema(capability),
                output_schema=_output_schema(capability),
                resources=tool_resources,
                risk_level="low",
                concurrent=capability not in {"image_output", "image_edit"},
                permission_scope="model",
            )
        )
    return specs


def _description(*, capability: str, configured: str) -> str:
    if configured:
        return configured
    descriptions = {
        "image_input": "Uses the configured auxiliary vision model to understand an image and return structured text.",
        "image_output": "Uses the configured auxiliary image model to generate an image from text requirements.",
        "image_edit": "Uses the configured auxiliary image model to edit or transform referenced images.",
        "audio_input": "Uses the configured auxiliary audio model to transcribe or understand audio and return text.",
        "audio_output": "Uses the configured auxiliary audio model to synthesize audio from text.",
    }
    return descriptions.get(capability, "Uses the configured auxiliary model for the current Agent capability.")


def _input_schema(capability: str) -> dict[str, Any]:
    if capability == "image_input":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string"},
                "input_attachment_ids": {"type": "array", "items": {"type": "string"}},
                "input_paths": {"type": "array", "items": {"type": "string"}},
                "image_url": {"type": "string"},
                "image_base64": {"type": "string"},
                "mime_type": {"type": "string"},
            },
            "required": ["prompt"],
            "anyOf": [
                {"required": ["input_attachment_ids"]},
                {"required": ["input_paths"]},
                {"required": ["image_url"]},
                {"required": ["image_base64"]},
            ],
        }
    if capability == "image_output":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string"},
                "size": {"type": "string"},
                "aspect_ratio": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 4},
                "seed": {"type": "integer"},
                "negative_prompt": {"type": "string"},
                "provider_options": {"type": "object", "additionalProperties": True},
            },
            "required": ["prompt"],
        }
    if capability == "image_edit":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string"},
                "input_attachment_ids": {"type": "array", "items": {"type": "string"}},
                "input_paths": {"type": "array", "items": {"type": "string"}},
                "image_url": {"type": "string"},
                "size": {"type": "string"},
                "aspect_ratio": {"type": "string"},
                "count": {"type": "integer", "minimum": 1, "maximum": 4},
                "seed": {"type": "integer"},
                "negative_prompt": {"type": "string"},
                "provider_options": {"type": "object", "additionalProperties": True},
            },
            "required": ["prompt"],
        }
    if capability == "audio_input":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string"},
                "audio_url": {"type": "string"},
                "audio_base64": {"type": "string"},
                "mime_type": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["prompt"],
            "anyOf": [{"required": ["audio_url"]}, {"required": ["audio_base64"]}],
        }
    if capability == "audio_output":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string"},
                "voice": {"type": "string"},
                "format": {"type": "string"},
            },
            "required": ["text"],
        }
    return {"type": "object", "additionalProperties": True}


def _output_schema(capability: str) -> dict[str, Any]:
    if capability in {"image_output", "image_edit"}:
        return _image_generation_output_schema()
    return _textual_output_schema()


def _textual_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "capability": {"type": "string"},
            "profile_id": {"type": "string"},
            "content": {"type": "string"},
            "artifacts": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "raw_content": {},
            "metadata": {"type": "object", "additionalProperties": True},
        },
        "required": ["capability", "profile_id", "content", "artifacts", "metadata"],
    }


def _image_generation_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "capability": {"type": "string"},
            "profile_id": {"type": "string"},
            "assets": {
                "type": "array",
                "items": {"type": "object", "additionalProperties": True},
                "minItems": 1,
            },
            "metadata": {"type": "object", "additionalProperties": True},
        },
        "required": ["capability", "profile_id", "assets", "metadata"],
    }
