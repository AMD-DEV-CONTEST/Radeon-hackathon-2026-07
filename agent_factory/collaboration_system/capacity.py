from __future__ import annotations

from typing import Any


DEFAULT_MAX_PARALLEL_SUB_AGENTS = 5


def normalize_max_parallel_sub_agents(
    value: Any,
    *,
    fallback: int = DEFAULT_MAX_PARALLEL_SUB_AGENTS,
) -> int:
    if value is None or str(value).strip() == "":
        return fallback
    if isinstance(value, bool):
        raise ValueError("max_parallel_sub_agents must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_parallel_sub_agents must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError("max_parallel_sub_agents must be a positive integer")
    return normalized
