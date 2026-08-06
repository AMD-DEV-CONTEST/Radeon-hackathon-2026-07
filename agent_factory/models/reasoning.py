from __future__ import annotations

from dataclasses import replace
from typing import Any


REASONING_CONTENT_BLOCK_TYPES = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "thinking",
    }
)
RUNTIME_REASONING_INTENSITY_MAX = 4


def is_reasoning_content_block(value: Any) -> bool:
    return isinstance(value, dict) and str(value.get("type") or "").strip() in REASONING_CONTENT_BLOCK_TYPES


def reasoning_content_from_message(message: Any) -> str | None:
    candidates = [
        _mapping_value(getattr(message, "additional_kwargs", None), "reasoning_content"),
        _mapping_value(getattr(message, "response_metadata", None), "reasoning_content"),
        _mapping_value(getattr(message, "additional_kwargs", None), "reasoning"),
        _mapping_value(getattr(message, "response_metadata", None), "reasoning"),
        reasoning_content_from_blocks(getattr(message, "content", None)),
    ]
    for candidate in candidates:
        reasoning_content = coerce_reasoning_content(candidate)
        if reasoning_content is not None:
            return reasoning_content
    return None


def reasoning_content_from_raw_message(message: dict[str, Any]) -> str | None:
    candidates = [
        message.get("reasoning_content"),
        message.get("reasoning"),
        message.get("reasoning_details"),
        reasoning_content_from_blocks(message.get("content")),
    ]
    for candidate in candidates:
        reasoning_content = coerce_reasoning_content(candidate)
        if reasoning_content is not None:
            return reasoning_content
    return None


def reasoning_content_from_stream_chunk(chunk: dict[str, Any]) -> str | None:
    choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
    if not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        return None
    return reasoning_content_from_raw_message(delta)


def reasoning_content_from_blocks(content: Any) -> str | None:
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for block in content:
        if not is_reasoning_content_block(block):
            continue
        text = (
            block.get("reasoning_content")
            or block.get("thinking")
            or block.get("text")
            or block.get("content")
        )
        if text:
            parts.append(str(text))
    if not parts:
        return None
    return "\n".join(parts)


def coerce_reasoning_content(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("reasoning_content", "text", "content", "summary"):
            if key in value:
                return coerce_reasoning_content(value[key])
        return str(value)
    if isinstance(value, list):
        parts = [coerce_reasoning_content(item) for item in value]
        return "\n".join(part for part in parts if part)
    return str(value)


def apply_reasoning_intensity(settings: Any, intensity: int) -> Any:
    level = max(0, min(RUNTIME_REASONING_INTENSITY_MAX, int(intensity)))
    current = getattr(settings, "reasoning", None)
    if current is None:
        from agent_factory.models.protocol import ModelReasoningSettings

        current = ModelReasoningSettings()
    if level == 0:
        return replace(
            settings,
            reasoning=replace(current, enabled=False, effort=None, budget_tokens=None),
        )

    if not bool(getattr(settings, "reasoning_supported", False)):
        raise ValueError("the selected model does not support reasoning")

    efforts = tuple(getattr(settings, "reasoning_efforts", ()) or ())
    effort = _effort_for_intensity(efforts, level)
    budget_tokens = _budget_for_intensity(settings, efforts, current, level)
    return replace(
        settings,
        reasoning=replace(
            current,
            enabled=True,
            effort=effort,
            budget_tokens=budget_tokens,
        ),
    )


def _effort_for_intensity(efforts: tuple[str, ...], level: int) -> str | None:
    if not efforts or "budget_tokens" in efforts:
        return None
    ordered = [
        item
        for item in ("low", "medium", "high", "xhigh", "max", "adaptive")
        if item in efforts
    ]
    candidates = ordered or list(efforts)
    index = min(len(candidates) - 1, ((level * len(candidates)) - 1) // RUNTIME_REASONING_INTENSITY_MAX)
    return candidates[index]


def _budget_for_intensity(
    settings: Any,
    efforts: tuple[str, ...],
    current: Any,
    level: int,
) -> int | None:
    if "budget_tokens" not in efforts:
        return None
    ceiling = getattr(current, "budget_tokens", None) or getattr(settings, "max_output_tokens", None)
    if not isinstance(ceiling, int) or ceiling <= 0:
        return None
    return max(1, (ceiling * level) // RUNTIME_REASONING_INTENSITY_MAX)


def _mapping_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None
