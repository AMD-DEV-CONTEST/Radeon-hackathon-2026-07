"""Durable local notification intent without an external delivery channel."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Self
from uuid import uuid4

from .models import AuditRecord, Decision, Event, utc_now
from .responsibility import ResponsibilityAssignment

if TYPE_CHECKING:
    from .storage import SQLiteStore


class NotificationStatus(StrEnum):
    CREATED = "CREATED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


@dataclass(slots=True)
class Notification:
    notification_id: str
    event_id: str
    trace_id: str
    decision_id: str
    recipient_id: str
    recipient_name: str
    title: str
    content: str
    channel: str
    status: NotificationStatus
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            **{
                **data,
                "status": NotificationStatus(data["status"]),
            }
        )


class LocalNotificationOutbox:
    """Persist one CREATED notification; never perform message delivery."""

    channel = "local_outbox"

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def enqueue(
        self,
        *,
        event: Event,
        decision: Decision,
        assignment: ResponsibilityAssignment,
        actor: str,
    ) -> Notification:
        existing = self.store.find_notification_by_decision(
            decision.decision_id
        )
        if existing is not None:
            return existing

        notification = Notification(
            notification_id=f"notification_{uuid4().hex}",
            event_id=event.event_id,
            trace_id=event.trace_id,
            decision_id=decision.decision_id,
            recipient_id=assignment.owner_id,
            recipient_name=assignment.owner_name,
            title="Industrial incident requires human review",
            content=(
                f"Event {event.event_id} produced Decision "
                f"{decision.decision_id}. "
                "Review is required; this record is not a delivered message."
            ),
            channel=self.channel,
            status=NotificationStatus.CREATED,
            created_at=utc_now(),
        )
        audit = AuditRecord(
            audit_id=f"audit_{uuid4().hex}",
            actor=actor,
            action="notification_created",
            object_type="Notification",
            object_id=notification.notification_id,
            previous_state=None,
            new_state=notification.status.value,
            timestamp=notification.created_at,
            trace_id=event.trace_id,
            details={
                "channel": notification.channel,
                "recipient_id": notification.recipient_id,
                "match_type": assignment.match_type,
                "matched_key": assignment.matched_key,
            },
        )
        return self.store.register_notification(notification, audit)
