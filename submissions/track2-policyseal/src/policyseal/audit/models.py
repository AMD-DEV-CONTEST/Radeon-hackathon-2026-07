from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

AuditValue = str | int | bool | tuple[str, ...]
SanitizedPayload = tuple[tuple[str, AuditValue], ...]


class AuditEventType(StrEnum):
    TASK_CREATED = "task_created"
    SOURCE_VIEWED = "source_viewed"
    CONTEXT_CHANGED = "context_changed"
    REVISION_CREATED = "revision_created"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    ANALYSIS_FAILED = "analysis_failed"
    DECISION = "decision"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXCEPTION_REQUESTED = "exception_requested"
    EXPORTED = "exported"
    COPILOT_USED = "copilot_used"
    TASK_DELETED = "task_deleted"


def payload_as_dict(payload: SanitizedPayload) -> dict[str, AuditValue]:
    return dict(payload)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: AuditEventType
    occurred_at: datetime
    actor: str
    task_id: str | None
    revision_id: str | None
    policy_sha256: str | None
    payload: SanitizedPayload
    previous_hash: str
    event_hash: str

    def canonical_bytes(self) -> bytes:
        value = {
            "actor": self.actor,
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(timespec="microseconds"),
            "payload": payload_as_dict(self.payload),
            "policy_sha256": self.policy_sha256,
            "previous_hash": self.previous_hash,
            "revision_id": self.revision_id,
            "task_id": self.task_id,
        }
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class AuditVerification:
    valid: bool
    checked_events: int
    first_invalid_index: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class AuditAppendResult:
    accepted: bool
    event: AuditEvent | None = None
    error: str | None = None
