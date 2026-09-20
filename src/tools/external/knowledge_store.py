"""Candidate knowledge store — TTL-scoped, isolated from long-term memory.

Per the approved design (review fix #3): external snapshots MUST NOT
silently enter SemanticMemory. They live in a candidate zone that:

- is keyed by (tool, symbol/query) and expires via `effective_until`;
- can be read back while still valid (fresh snapshot reuse);
- is only promoted into long-term memory when EXPLICITLY confirmed or
  when the source is highly trusted (source_confidence >= 0.8).
  Mock/synthetic data (confidence 0.4) can never be promoted.

This mirrors the memory-consistency guardrails: unverified snapshots are
kept separate from model-internal knowledge so they can't contaminate
later reasoning (the S8 cancellation problem, applied to data).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .protocol import ToolResult, now_iso

PROMOTE_THRESHOLD = 0.8  # only official-class sources may auto-promote


@dataclass
class CandidateKnowledge:
    key: str
    tool: str
    source: str
    source_confidence: float
    retrieved_at: str
    effective_until: str
    data_mode: str
    data: dict
    promoted: bool = False


def _is_expired(item: CandidateKnowledge) -> bool:
    try:
        return datetime.fromisoformat(item.effective_until) < datetime.fromisoformat(now_iso())
    except (TypeError, ValueError):
        return True  # unparseable TTL → treat as expired (fail-closed)


class CandidateKnowledgeStore:
    """In-memory candidate zone; survives within a process run.

    File persistence is intentionally omitted in v1: candidates are
    session-scoped snapshots, not durable knowledge. Durable, verified
    knowledge belongs in SemanticMemory via `promote()`.
    """

    def __init__(self) -> None:
        self._items: dict[str, CandidateKnowledge] = {}

    # ── Write ──────────────────────────────────────────────────────

    def add(self, key: str, result: ToolResult) -> CandidateKnowledge:
        item = CandidateKnowledge(
            key=key,
            tool=result.tool,
            source=result.source,
            source_confidence=result.source_confidence,
            retrieved_at=result.retrieved_at,
            effective_until=result.effective_until,
            data_mode=result.data_mode,
            data=result.data,
        )
        self._items[key] = item  # overwrite old snapshot with the freshest
        return item

    # ── Read (TTL-aware) ───────────────────────────────────────────

    def get(self, key: str) -> CandidateKnowledge | None:
        item = self._items.get(key)
        if item is None or _is_expired(item):
            return None
        return item

    def list_valid(self) -> list[CandidateKnowledge]:
        return [i for i in self._items.values() if not _is_expired(i)]

    # ── Promotion (guarded) ────────────────────────────────────────

    def promote(self, key: str, semantic_memory, label: str | None = None) -> bool:
        """Promote a candidate into SemanticMemory IF it qualifies.

        Guardrails:
        - key must exist and be unexpired;
        - source_confidence >= PROMOTE_THRESHOLD, OR the caller passes
          explicit_confirm=True (user said "记住这条") — see `promote_confirmed`.
        Mock/synthetic snapshots (0.4) are never auto-promoted.
        """
        item = self.get(key)
        if item is None:
            return False
        if item.source_confidence < PROMOTE_THRESHOLD:
            return False
        return self._commit(item, semantic_memory, label)

    def promote_confirmed(self, key: str, semantic_memory, label: str | None = None) -> bool:
        """Promote regardless of confidence — reserved for explicit user
        confirmation (e.g. user says '记住这条信息')."""
        item = self.get(key)
        if item is None:
            return False
        return self._commit(item, semantic_memory, label)

    def _commit(self, item: CandidateKnowledge, semantic_memory, label: str | None) -> bool:
        # Accept either AgentMemory facade or SemanticMemory directly
        target = getattr(semantic_memory, "semantic", semantic_memory)
        rule = (
            f"[VERIFIED:{item.tool}@{item.source}] {label or ''} "
            f"(retrieved {item.retrieved_at}, confidence {item.source_confidence:.2f})"
        ).strip()
        if rule not in getattr(target, "experience_rules", []):
            target.experience_rules.append(rule)
        if hasattr(target, "_persist"):
            target._persist()
        item.promoted = True
        return True

    # ── Maintenance ────────────────────────────────────────────────

    def cleanup(self) -> int:
        expired = [k for k, v in self._items.items() if _is_expired(v)]
        for k in expired:
            del self._items[k]
        return len(expired)

    def __len__(self) -> int:
        return len(self._items)


# Process-wide singleton used by the registry
store = CandidateKnowledgeStore()
