from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from policyseal.application.approvals import ApprovalService, approval_binding
from policyseal.application.state_machine import ALLOWED_TRANSITIONS, transition_status
from policyseal.domain.enums import ApprovalStatus, Channel, RevisionStatus
from policyseal.domain.errors import ApprovalDenied, InvalidStateTransition
from policyseal.domain.models import DisclosureRevision
from policyseal.storage.repositories import PolicySealRepository


def test_requester_cannot_approve_own_revision(
    approval_service: ApprovalService,
    pending_revision: DisclosureRevision,
) -> None:
    approval_service.request(pending_revision.id, actor=pending_revision.requester_id)

    with pytest.raises(ApprovalDenied):
        approval_service.approve(pending_revision.id, actor=pending_revision.requester_id)


def test_blocked_revision_can_never_be_approved(
    approval_service: ApprovalService,
    blocked_revision: DisclosureRevision,
) -> None:
    with pytest.raises(ApprovalDenied):
        approval_service.approve(blocked_revision.id, actor="reviewer-1")


def test_approval_is_bound_to_exact_revision_and_single_use(
    approval_service: ApprovalService,
    pending_revision: DisclosureRevision,
) -> None:
    requested = approval_service.request(
        pending_revision.id,
        actor=pending_revision.requester_id,
    )
    approved = approval_service.approve(
        pending_revision.id,
        actor="reviewer-1",
        expected_binding_sha256=requested.binding_sha256,
    )

    assert approved.status is ApprovalStatus.APPROVED
    assert approval_service.consume(approved.id, pending_revision.id).consumed is True
    with pytest.raises(ApprovalDenied):
        approval_service.consume(approved.id, pending_revision.id)


def test_any_revision_mismatch_invalidates_approval(
    pending_revision: DisclosureRevision,
) -> None:
    original = approval_binding(pending_revision)
    changed_context = replace(
        pending_revision,
        context=pending_revision.context.with_channel(Channel.PERSONAL_EMAIL),
    )
    changed_output = replace(pending_revision, output_sha256="d" * 64)

    assert approval_binding(changed_context).sha256 != original.sha256
    assert approval_binding(changed_output).sha256 != original.sha256


def test_expired_request_cannot_be_approved(
    repository: PolicySealRepository,
    pending_revision: DisclosureRevision,
) -> None:
    times = iter(
        (
            datetime(2026, 8, 2, 1, 0, tzinfo=UTC),
            datetime(2026, 8, 2, 3, 0, tzinfo=UTC),
        )
    )
    service = ApprovalService(repository, clock=lambda: next(times), id_factory=lambda: "a1")
    service.request(
        pending_revision.id,
        actor=pending_revision.requester_id,
        validity=timedelta(hours=1),
    )

    with pytest.raises(ApprovalDenied):
        service.approve(pending_revision.id, actor="reviewer-1")


def test_reviewer_can_reject_but_cannot_edit(
    approval_service: ApprovalService,
    pending_revision: DisclosureRevision,
) -> None:
    approval_service.request(pending_revision.id, actor=pending_revision.requester_id)
    rejected = approval_service.reject(
        pending_revision.id,
        actor="reviewer-1",
        reason_code="nonstandard_obligation_not_approved",
    )

    assert rejected.status is ApprovalStatus.REJECTED
    stored_revision = approval_service.repository.get_revision(pending_revision.id)
    assert stored_revision.status is RevisionStatus.REJECTED
    assert not hasattr(approval_service, "edit_output")


def test_all_nine_states_reject_every_unlisted_transition() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(RevisionStatus)
    for current in RevisionStatus:
        for target in RevisionStatus:
            if target in ALLOWED_TRANSITIONS[current]:
                assert transition_status(current, target) is target
            else:
                with pytest.raises(InvalidStateTransition):
                    transition_status(current, target)
