"""Layered memory: Session/Task/Namespace three layers."""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class MemoryLayer(Enum):
    """Memory layer enum."""
    SESSION_SHORT_TERM = "session_short_term"
    TASK_WORKSPACE = "task_workspace"
    NAMESPACE_LONG_TERM = "namespace_long_term"
    RULE_RECORD = "rule_record"
    REFLECTION_CANDIDATE = "reflection_candidate"


@dataclass
class MemoryRecord:
    """A memory record."""
    id: str
    layer: MemoryLayer
    collection: str
    kind: str
    scope: dict[str, str]
    summary: str
    body: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None
    priority: int = 50
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def create_session_record(
    session_id: str,
    tenant_id: str,
    memo: dict[str, Any],
) -> MemoryRecord:
    """Create a Session short-term memory record."""
    return MemoryRecord(
        id=f"session-memo-{session_id}",
        layer=MemoryLayer.SESSION_SHORT_TERM,
        collection="sessions",
        kind="session_memo",
        scope={"tenant_id": tenant_id, "session_id": session_id},
        summary=f"context summary for session {session_id}",
        body=memo,
        priority=60,
    )


def create_task_record(
    task_id: str,
    tenant_id: str,
    evidence_text: str,
    source_ref: str,
) -> MemoryRecord:
    """Create a Task workspace memory record."""
    return MemoryRecord(
        id=f"task-evidence-{task_id}",
        layer=MemoryLayer.TASK_WORKSPACE,
        collection="task_workspace",
        kind="evidence",
        scope={"tenant_id": tenant_id, "task_id": task_id},
        summary="task evidence",
        body={"source_ref": source_ref, "text": evidence_text},
        priority=55,
    )


def create_long_term_record(
    namespace: str,
    tenant_id: str,
    preference_text: str,
    evidence_refs: list[str],
) -> MemoryRecord:
    """Create a Namespace long-term memory record."""
    return MemoryRecord(
        id=f"long-term-{namespace}",
        layer=MemoryLayer.NAMESPACE_LONG_TERM,
        collection="memory",
        kind="long_term_memory",
        scope={"tenant_id": tenant_id, "namespace": namespace},
        summary=f"long-term preference: {namespace}",
        body={"text": preference_text, "evidence_refs": evidence_refs},
        priority=40,
    )
