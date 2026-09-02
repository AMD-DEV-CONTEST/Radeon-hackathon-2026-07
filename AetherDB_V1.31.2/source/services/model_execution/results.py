"""Result contract returned to model-backed business workflows."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from services.model_execution.task_types import resolve_task_type


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        total = self.total_tokens
        if total is None and self.input_tokens is not None and self.output_tokens is not None:
            total = self.input_tokens + self.output_tokens
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": total,
        }


def _token_count(raw: Mapping[str, Any], names: Sequence[str]) -> int | None:
    for name in names:
        value = raw.get(name)
        if value is None or isinstance(value, bool):
            continue
        try:
            count = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if count >= 0:
            return count
    return None


def normalize_usage(raw: Mapping[str, Any] | None) -> dict[str, int | None]:
    raw = raw or {}
    input_tokens = _token_count(
        raw,
        ("input_tokens", "prompt_tokens", "prompt_eval_count", "prompt_token_count"),
    )
    output_tokens = _token_count(
        raw,
        ("output_tokens", "completion_tokens", "eval_count", "candidates_token_count"),
    )
    total_tokens = _token_count(raw, ("total_tokens", "total_token_count"))
    return NormalizedUsage(input_tokens, output_tokens, total_tokens).as_dict()


@dataclass(frozen=True)
class NormalizedProviderResponse:
    content: str
    thinking_content: str = ""
    usage: Mapping[str, int | None] = field(default_factory=dict)
    finish_reason: str | None = None
    provider_request_id: str | None = None
    warnings: tuple[str, ...] = ()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_choice(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = raw.get("choices")
    if isinstance(choices, Sequence) and not isinstance(choices, (str, bytes)) and choices:
        return _mapping(choices[0])
    return {}


def _text_field(sources: Sequence[Mapping[str, Any]], names: Sequence[str]) -> str:
    for source in sources:
        for name in names:
            value = source.get(name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError("Provider response content must be text")
            return value
    return ""


def _has_nonempty_field(sources: Sequence[Mapping[str, Any]], names: Sequence[str]) -> bool:
    return any(source.get(name) not in (None, "", [], {}) for source in sources for name in names)


def normalize_provider_response(raw: Any) -> NormalizedProviderResponse:
    if isinstance(raw, str):
        return NormalizedProviderResponse(content=raw, usage=normalize_usage(None))
    if not isinstance(raw, Mapping):
        raise ValueError("Provider response must be text or a mapping")

    choice = _first_choice(raw)
    message = _mapping(choice.get("message")) or _mapping(choice.get("delta")) or _mapping(raw.get("message"))
    sources = (message, choice, raw)
    content = _text_field(sources, ("content", "response"))
    thinking = _text_field(sources, ("thinking_content", "reasoning_content", "thinking"))

    usage_source = _mapping(raw.get("usage")) or _mapping(raw.get("usage_metadata")) or raw
    finish_reason = raw.get("finish_reason") or choice.get("finish_reason") or raw.get("done_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        finish_reason = str(finish_reason)

    warnings = []
    if finish_reason and finish_reason.lower() in {"length", "max_tokens", "max_output_tokens"}:
        warnings.append("OUTPUT_TRUNCATED")
    if _has_nonempty_field(sources, ("tool_call", "tool_calls")):
        warnings.append("TOOL_CALLS_IGNORED")
    if _has_nonempty_field(sources, ("plan", "action")):
        warnings.append("NON_FINAL_PROVIDER_FIELDS_IGNORED")

    request_id = raw.get("provider_request_id") or raw.get("request_id") or raw.get("id")
    if request_id is not None and not isinstance(request_id, str):
        request_id = str(request_id)
    return NormalizedProviderResponse(
        content=content,
        thinking_content=thinking,
        usage=normalize_usage(usage_source),
        finish_reason=finish_reason,
        provider_request_id=request_id,
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class ModelTaskResult:
    task_id: str
    model_profile_id: str
    provider_id: str
    content: str
    usage: Mapping[str, int | None] = field(default_factory=dict)
    raw_provider_request_id: str | None = None
    provider_model_name: str | None = None
    thinking_content: str = ""
    finish_reason: str | None = None
    warnings: tuple[str, ...] = ()
    task_type: str | None = None
    legacy_task_type: str | None = None
    runtime: str | None = None
    model_revision: str | None = None
    device: str | None = None
    status: str = "completed"
    execution_evidence: Mapping[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    created_at: str | None = None
    completed_at: str | None = None

    def to_read_model(self, source_task_type: str | None = None) -> dict[str, Any]:
        resolution = resolve_task_type(source_task_type or self.task_type or "")
        now = datetime.now(timezone.utc).isoformat()
        return {
            "task_id": self.task_id,
            "task_type": resolution.canonical,
            "legacy_task_type": self.legacy_task_type or resolution.legacy_source,
            "runtime": self.runtime,
            "model_id": self.model_profile_id,
            "model_revision": self.model_revision,
            "device": self.device,
            "status": self.status,
            "output": {"content": self.content},
            "warnings": list(self.warnings),
            "usage": dict(self.usage),
            "execution_evidence": dict(self.execution_evidence),
            "fallback_used": self.fallback_used,
            "created_at": self.created_at or now,
            "completed_at": self.completed_at or now,
        }
