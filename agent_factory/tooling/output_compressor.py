"""Tool output compression for model-visible observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import ToolOutputCompressionActionConfig


DEFAULT_COMPRESSION_MAX_CHARS = 6000
DEFAULT_MAX_ATTEMPTS = 2

COMPRESSION_SYSTEM_PROMPT = (
    "You are the small-task model used only for tool output compression. "
    "Return structured JSON that preserves the information another agent needs to continue safely.\n\n"
    "Rules:\n"
    "- Preserve identifiers, ids, slugs, file paths, directory names, package-relative paths, schemas, and contract keys verbatim.\n"
    "- Preserve error messages, exception types, stack traces, numeric counts, and status fields.\n"
    "- Preserve numeric counts (number of files, entries, etc.).\n"
    "- Remove redundant formatting and repeated boilerplate.\n"
    "- Do not invent fields, ids, paths, resources, versions, or conclusions.\n"
    "- If compressed information may be insufficient, set insufficient=true and explain what must be read from the raw output.\n"
    "- Return JSON only."
)

DEFAULT_COMPRESSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "important_facts": {"type": "array", "items": {"type": "string"}},
        "preserved_identifiers": {"type": "array", "items": {"type": "string"}},
        "errors": {"type": "array", "items": {"type": "string"}},
        "next_actions": {"type": "array", "items": {"type": "string"}},
        "insufficient": {"type": "boolean"},
        "read_original_reason": {"type": "string"},
    },
    "required": [
        "summary",
        "important_facts",
        "preserved_identifiers",
        "errors",
        "next_actions",
        "insufficient",
        "read_original_reason",
    ],
}


class DefaultToolOutputCompression(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    important_facts: list[str] = Field(default_factory=list)
    preserved_identifiers: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    insufficient: bool = False
    read_original_reason: str = ""


@dataclass(frozen=True, slots=True)
class ToolOutputCompression:
    compressed_output: dict[str, Any]
    compressed: bool
    original_chars: int
    compressed_chars: int
    method: str


def compress_tool_output(
    output: dict[str, Any],
    *,
    tool_id: str,
    arguments: dict[str, Any],
    max_chars: int = DEFAULT_COMPRESSION_MAX_CHARS,
    model: BaseChatModel | None = None,
    config: ToolOutputCompressionActionConfig | None = None,
) -> ToolOutputCompression:
    raw_text = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    original_chars = len(raw_text)

    if original_chars <= max_chars:
        return ToolOutputCompression(
            compressed_output=output,
            compressed=False,
            original_chars=original_chars,
            compressed_chars=original_chars,
            method="none",
        )

    compression_config = config or ToolOutputCompressionActionConfig()
    if model is None or compression_config.mode == "deterministic":
        return _fallback_truncation(raw_text, max_chars=max_chars, original_chars=original_chars)

    try:
        compressed = _invoke_structured_compression(
            model=model,
            raw_text=raw_text,
            tool_id=tool_id,
            arguments=arguments,
            max_chars=max_chars,
            config=compression_config,
        )
        compressed_chars = len(json.dumps(compressed, ensure_ascii=False, sort_keys=True, default=str))
        return ToolOutputCompression(
            compressed_output=compressed,
            compressed=True,
            original_chars=original_chars,
            compressed_chars=compressed_chars,
            method="structured_json",
        )
    except Exception:
        return _fallback_truncation(raw_text, max_chars=max_chars, original_chars=original_chars)


def _invoke_structured_compression(
    *,
    model: BaseChatModel,
    raw_text: str,
    tool_id: str,
    arguments: dict[str, Any],
    max_chars: int,
    config: ToolOutputCompressionActionConfig,
) -> dict[str, Any]:
    schema = config.schema or DEFAULT_COMPRESSION_SCHEMA
    output_model = (
        compile_json_schema(schema=schema, model_name=f"{tool_id}_compressed_output").pydantic_model
        if config.schema
        else DefaultToolOutputCompression
    )
    args_summary = json.dumps(arguments, ensure_ascii=False, default=str)[:200]
    user_content = _compression_user_prompt(
        raw_text=raw_text,
        tool_id=tool_id,
        args_summary=args_summary,
        max_chars=max_chars,
        schema=schema,
        custom_prompt=config.prompt,
    )
    messages = [
        SystemMessage(content=COMPRESSION_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    last_error: Exception | None = None
    for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
        try:
            structured_model = model.with_structured_output(output_model, method="json_mode").with_config(
                tags=["nostream", "tool-output-compression", f"tool:{tool_id}"]
            )
            result = structured_model.invoke(messages)
            parsed = result if isinstance(result, output_model) else output_model.model_validate(result)
            return parsed.model_dump(mode="json")
        except Exception as exc:
            last_error = exc
            if attempt >= DEFAULT_MAX_ATTEMPTS:
                break
            messages.append(
                HumanMessage(
                    content=(
                        "The previous compression output failed schema validation.\n"
                        f"Error: {type(exc).__name__}: {exc}\n"
                        "Return JSON only using the required schema. Preserve identifiers verbatim."
                    )
                )
            )
    raise last_error or ValueError("structured compression failed")


def _compression_user_prompt(
    *,
    raw_text: str,
    tool_id: str,
    args_summary: str,
    max_chars: int,
    schema: dict[str, Any],
    custom_prompt: str,
) -> str:
    sections = [
        f"Tool: {tool_id}",
        f"Arguments: {args_summary}",
        f"Target JSON length: ≤{max_chars} characters",
        f"Original length: {len(raw_text)} characters",
        f"Output JSON schema:\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}",
    ]
    if custom_prompt.strip():
        sections.append(f"Action-specific compression instructions:\n{custom_prompt.strip()}")
    sections.append(f"--- RAW OUTPUT START ---\n{raw_text}\n--- RAW OUTPUT END ---")
    return "\n\n".join(sections)


def _fallback_truncation(raw_text: str, *, max_chars: int, original_chars: int) -> ToolOutputCompression:
    half = max(200, (max_chars - 100) // 2)
    truncated = f"{raw_text[:half]}\n... [truncated {original_chars - 2 * half} chars] ...\n{raw_text[-half:]}"
    if len(truncated) > max_chars:
        truncated = raw_text[:max_chars - 50] + f"\n... [truncated, total {original_chars} chars]"
    output = {
        "summary": "Tool output was structurally truncated because structured compression was unavailable.",
        "preview": truncated,
        "important_facts": [],
        "preserved_identifiers": [],
        "errors": [],
        "next_actions": [],
        "insufficient": True,
        "read_original_reason": "The model-visible output is a deterministic preview of a larger raw tool output.",
    }
    return ToolOutputCompression(
        compressed_output=output,
        compressed=True,
        original_chars=original_chars,
        compressed_chars=len(json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)),
        method="deterministic",
    )
