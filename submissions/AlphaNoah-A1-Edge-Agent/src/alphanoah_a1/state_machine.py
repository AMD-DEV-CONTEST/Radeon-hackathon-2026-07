"""Explicit event-state transition rules."""

from __future__ import annotations

from .exceptions import InvalidStateTransition
from .models import EventStatus


ALLOWED_TRANSITIONS: dict[EventStatus, frozenset[EventStatus]] = {
    EventStatus.NEW: frozenset(
        {EventStatus.ANALYZED, EventStatus.FAILED, EventStatus.CANCELLED}
    ),
    EventStatus.ANALYZED: frozenset(
        {
            EventStatus.PENDING_HUMAN_REVIEW,
            EventStatus.APPROVED,
            EventStatus.CLOSED,
            EventStatus.REJECTED,
            EventStatus.NEEDS_MORE_EVIDENCE,
            EventStatus.ESCALATED,
            EventStatus.FAILED,
        }
    ),
    EventStatus.PENDING_HUMAN_REVIEW: frozenset(
        {
            EventStatus.APPROVED,
            EventStatus.REJECTED,
            EventStatus.NEEDS_MORE_EVIDENCE,
            EventStatus.ESCALATED,
            EventStatus.CANCELLED,
        }
    ),
    EventStatus.APPROVED: frozenset(
        {EventStatus.TASK_CREATED, EventStatus.CANCELLED}
    ),
    EventStatus.TASK_CREATED: frozenset(
        {EventStatus.IN_PROGRESS, EventStatus.FAILED, EventStatus.CANCELLED}
    ),
    EventStatus.IN_PROGRESS: frozenset(
        {
            EventStatus.EVIDENCE_SUBMITTED,
            EventStatus.FAILED,
            EventStatus.CANCELLED,
            EventStatus.ESCALATED,
        }
    ),
    EventStatus.EVIDENCE_SUBMITTED: frozenset(
        {
            EventStatus.UNDER_REVIEW,
            EventStatus.IN_PROGRESS,
            EventStatus.FAILED,
        }
    ),
    EventStatus.UNDER_REVIEW: frozenset(
        {
            EventStatus.CLOSED,
            EventStatus.NEEDS_MORE_EVIDENCE,
            EventStatus.FAILED,
            EventStatus.ESCALATED,
        }
    ),
    EventStatus.NEEDS_MORE_EVIDENCE: frozenset(
        {
            EventStatus.ANALYZED,
            EventStatus.IN_PROGRESS,
            EventStatus.REJECTED,
            EventStatus.CANCELLED,
            EventStatus.ESCALATED,
        }
    ),
    EventStatus.FAILED: frozenset(
        {EventStatus.NEW, EventStatus.CANCELLED, EventStatus.ESCALATED}
    ),
    EventStatus.CLOSED: frozenset(),
    EventStatus.REJECTED: frozenset(),
    EventStatus.CANCELLED: frozenset(),
    EventStatus.ESCALATED: frozenset(),
}


def ensure_transition(previous: EventStatus, target: EventStatus) -> None:
    """Reject transitions not present in the declared workflow graph."""

    if target not in ALLOWED_TRANSITIONS[previous]:
        raise InvalidStateTransition(
            f"Illegal event transition: {previous.value} -> {target.value}"
        )
