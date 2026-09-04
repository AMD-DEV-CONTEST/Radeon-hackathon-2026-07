from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from policyseal.domain.enums import RevisionStatus
from policyseal.domain.errors import InvalidStateTransition

ALLOWED_TRANSITIONS: Final[Mapping[RevisionStatus, frozenset[RevisionStatus]]] = MappingProxyType(
    {
        RevisionStatus.DRAFT: frozenset({RevisionStatus.ANALYZING}),
        RevisionStatus.ANALYZING: frozenset(
            {
                RevisionStatus.AWAITING_CONFIRMATION,
                RevisionStatus.EXPORTABLE,
                RevisionStatus.AWAITING_APPROVAL,
                RevisionStatus.BLOCKED,
                RevisionStatus.PROCESSING_FAILED,
            }
        ),
        RevisionStatus.AWAITING_CONFIRMATION: frozenset(
            {
                RevisionStatus.ANALYZING,
                RevisionStatus.BLOCKED,
                RevisionStatus.PROCESSING_FAILED,
            }
        ),
        RevisionStatus.EXPORTABLE: frozenset(),
        RevisionStatus.AWAITING_APPROVAL: frozenset(
            {RevisionStatus.APPROVED, RevisionStatus.REJECTED}
        ),
        RevisionStatus.APPROVED: frozenset(),
        RevisionStatus.REJECTED: frozenset(),
        RevisionStatus.BLOCKED: frozenset(),
        RevisionStatus.PROCESSING_FAILED: frozenset(),
    }
)


def transition_status(current: RevisionStatus, target: RevisionStatus) -> RevisionStatus:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(f"cannot transition {current.value} to {target.value}")
    return target
