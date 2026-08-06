from __future__ import annotations

import json
from typing import Any

from langgraph.store.base import SearchItem

from agent_factory.memory_system.config import MemoryRankingConfig
from agent_factory.memory_system.schema import MemoryContextItem


def rank_memory_items(
    *,
    items: list[SearchItem],
    query: str,
    config: MemoryRankingConfig,
) -> tuple[list[MemoryContextItem], int]:
    query_tokens = {part.lower() for part in query.split() if part.strip()}
    candidates: list[MemoryContextItem] = []
    for item in items:
        value = dict(item.value or {})
        content = str(value.get("content") or "")
        kind = str(value.get("kind") or "fact")
        score = _score(value=value, content=content, query_tokens=query_tokens, store_score=getattr(item, "score", None))
        if score < config.min_score:
            continue
        candidates.append(
            MemoryContextItem(
                memory_id=str(value.get("memory_id") or item.key),
                source_scope=_source_scope(value=value, namespace=tuple(item.namespace)),
                memory_type=_memory_type(value.get("memory_type")),
                kind=kind if kind in {"fact", "preference", "decision", "constraint", "artifact"} else "fact",
                content=content,
                score=score,
                metadata=dict(value.get("metadata") or {}),
                namespace=tuple(item.namespace),
                updated_at=str(value.get("updated_at") or getattr(item, "updated_at", "") or ""),
            )
        )
    candidates.sort(key=lambda candidate: (candidate.score, candidate.updated_at or ""), reverse=True)
    selected: list[MemoryContextItem] = []
    per_kind_counts: dict[str, int] = {}
    token_total = 0
    for item in candidates:
        if len(selected) >= config.max_items_total:
            break
        limit = int(config.per_kind_limits.get(item.kind, config.max_items_total))
        if per_kind_counts.get(item.kind, 0) >= limit:
            continue
        estimated = estimate_tokens(item.content)
        if token_total + estimated > config.max_tokens_total:
            continue
        selected.append(item)
        token_total += estimated
        per_kind_counts[item.kind] = per_kind_counts.get(item.kind, 0) + 1
    return selected, token_total


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _score(
    *,
    value: dict[str, Any],
    content: str,
    query_tokens: set[str],
    store_score: float | None,
) -> float:
    if store_score is not None:
        return max(0.0, min(1.0, float(store_score)))
    metadata = dict(value.get("metadata") or {})
    importance = _float(metadata.get("importance"), default=_float(value.get("importance"), default=0.5))
    haystack = f"{content} {json.dumps(metadata, ensure_ascii=False)}".lower()
    if not query_tokens:
        lexical = 0.0
    else:
        matched = sum(1 for token in query_tokens if token in haystack)
        lexical = matched / max(len(query_tokens), 1)
    return max(0.0, min(1.0, 0.35 + importance * 0.35 + lexical * 0.3))


def _float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _memory_type(value: Any) -> str:
    if value in {"semantic", "episodic", "procedural"}:
        return str(value)
    return "semantic"


def _source_scope(*, value: dict[str, Any], namespace: tuple[str, ...]) -> str:
    scope = str(value.get("scope") or "")
    if scope in {"factory", "workspace", "agent", "user"}:
        return scope
    if len(namespace) >= 2 and namespace[0] == "memory" and namespace[1] in {"factory", "workspace", "agent", "user"}:
        return namespace[1]
    return "none"
