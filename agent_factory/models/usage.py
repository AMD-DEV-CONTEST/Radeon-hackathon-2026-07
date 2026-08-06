from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_hit_tokens: int | None = None
    cache_miss_tokens: int | None = None

    def model_payload(self) -> dict[str, int | None]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
        }


def normalize_usage_metadata(usage: Any) -> NormalizedModelUsage:
    if not isinstance(usage, dict):
        return NormalizedModelUsage()

    input_tokens = _first_int(usage, "input_tokens", "prompt_tokens")
    output_tokens = _first_int(usage, "output_tokens", "completion_tokens")
    total_tokens = _first_int(usage, "total_tokens")
    cache_hit_tokens = _first_int(usage, "prompt_cache_hit_tokens", "cache_hit_tokens")
    cache_miss_tokens = _first_int(usage, "prompt_cache_miss_tokens", "cache_miss_tokens")

    input_details = _first_dict(usage, "input_token_details", "prompt_tokens_details")
    if input_details:
        cache_hit_tokens = cache_hit_tokens or _first_int(input_details, "cache_read", "cached_tokens")
        cache_miss_tokens = cache_miss_tokens or _first_int(input_details, "cache_miss", "uncached_tokens")

    output_details = _first_dict(usage, "output_token_details", "completion_tokens_details")
    reasoning_tokens = _first_int(usage, "reasoning_tokens")
    if output_details:
        reasoning_tokens = reasoning_tokens or _first_int(output_details, "reasoning", "reasoning_tokens")

    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)

    return NormalizedModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        cache_hit_tokens=cache_hit_tokens,
        cache_miss_tokens=cache_miss_tokens,
    )


def _first_int(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def _first_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None
