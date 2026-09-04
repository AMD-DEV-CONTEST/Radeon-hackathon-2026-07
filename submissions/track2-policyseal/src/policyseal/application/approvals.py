from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from policyseal.application.state_machine import transition_status
from policyseal.domain.enums import ApprovalStatus, RevisionStatus
from policyseal.domain.errors import ApprovalDenied, StorageConflictError
from policyseal.domain.models import ApprovalRecord, DisclosureRevision


@dataclass(frozen=True, slots=True)
class ApprovalBinding:
    revision_id: str
    source_sha256: str
    context_sha256: str
    policy_version: str
    policy_sha256: str
    output_sha256: str
    decision_manifest_sha256: str

    @property
    def sha256(self) -> str:
        payload = {
            "context_sha256": self.context_sha256,
            "decision_manifest_sha256": self.decision_manifest_sha256,
            "output_sha256": self.output_sha256,
            "policy_sha256": self.policy_sha256,
            "policy_version": self.policy_version,
            "revision_id": self.revision_id,
            "source_sha256": self.source_sha256,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class ApprovalRepository(Protocol):
    def get_revision(self, revision_id: str) -> DisclosureRevision: ...

    def add_approval(self, approval: ApprovalRecord) -> None: ...

    def get_approval(self, approval_id: str) -> ApprovalRecord: ...

    def get_approval_for_revision(self, revision_id: str) -> ApprovalRecord: ...

    def resolve_approval(
        self,
        approval_id: str,
        *,
        reviewer_id: str,
        status: ApprovalStatus,
        reviewed_at: datetime,
        reason_code: str | None,
        expected_revision_status: RevisionStatus,
        target_revision_status: RevisionStatus,
    ) -> ApprovalRecord: ...

    def consume_approval(self, approval_id: str) -> ApprovalRecord: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def approval_binding(revision: DisclosureRevision) -> ApprovalBinding:
    if revision.output_sha256 is None or revision.decision_manifest_sha256 is None:
        raise ApprovalDenied("approval requires a rendered output and decision manifest")
    return ApprovalBinding(
        revision_id=revision.id,
        source_sha256=revision.source_sha256,
        context_sha256=revision.context.sha256,
        policy_version=revision.context.policy_version,
        policy_sha256=revision.policy_sha256,
        output_sha256=revision.output_sha256,
        decision_manifest_sha256=revision.decision_manifest_sha256,
    )


class ApprovalService:
    def __init__(
        self,
        repository: ApprovalRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self._clock = clock
        self._id_factory = id_factory or (lambda: f"approval-{uuid.uuid4().hex}")

    def request(
        self,
        revision_id: str,
        *,
        actor: str,
        validity: timedelta = timedelta(hours=24),
    ) -> ApprovalRecord:
        revision = self._revision_or_deny(revision_id)
        if actor != revision.requester_id:
            raise ApprovalDenied("only the revision requester can request approval")
        if revision.status is not RevisionStatus.AWAITING_APPROVAL:
            raise ApprovalDenied("only an awaiting-approval revision can request approval")
        if validity <= timedelta(0):
            raise ApprovalDenied("approval validity must be positive")
        binding = approval_binding(revision)
        now = self._now()
        approval = ApprovalRecord(
            id=self._id_factory(),
            revision_id=revision.id,
            requester_id=revision.requester_id,
            status=ApprovalStatus.PENDING,
            binding_sha256=binding.sha256,
            source_sha256=binding.source_sha256,
            context_sha256=binding.context_sha256,
            policy_sha256=binding.policy_sha256,
            output_sha256=binding.output_sha256,
            decision_manifest_sha256=binding.decision_manifest_sha256,
            expires_at=now + validity,
            created_at=now,
        )
        try:
            self.repository.add_approval(approval)
        except StorageConflictError as error:
            raise ApprovalDenied("this exact revision already has an approval request") from error
        return approval

    def approve(
        self,
        revision_id: str,
        *,
        actor: str,
        expected_binding_sha256: str | None = None,
    ) -> ApprovalRecord:
        return self._resolve(
            revision_id,
            actor=actor,
            status=ApprovalStatus.APPROVED,
            target=RevisionStatus.APPROVED,
            reason_code=None,
            expected_binding_sha256=expected_binding_sha256,
        )

    def reject(
        self,
        revision_id: str,
        *,
        actor: str,
        reason_code: str,
    ) -> ApprovalRecord:
        if not reason_code.strip():
            raise ApprovalDenied("rejection requires a controlled reason code")
        return self._resolve(
            revision_id,
            actor=actor,
            status=ApprovalStatus.REJECTED,
            target=RevisionStatus.REJECTED,
            reason_code=reason_code,
            expected_binding_sha256=None,
        )

    def consume(self, approval_id: str, revision_id: str) -> ApprovalRecord:
        revision = self._revision_or_deny(revision_id)
        try:
            approval = self.repository.get_approval(approval_id)
        except KeyError as error:
            raise ApprovalDenied("approval does not exist") from error
        if approval.revision_id != revision.id:
            raise ApprovalDenied("approval belongs to a different revision")
        if approval.status is not ApprovalStatus.APPROVED or approval.consumed:
            raise ApprovalDenied("approval is not available for export")
        if revision.status is not RevisionStatus.APPROVED:
            raise ApprovalDenied("revision is not approved")
        self._validate_exact(approval, revision, self._now())
        try:
            return self.repository.consume_approval(approval.id)
        except StorageConflictError as error:
            raise ApprovalDenied("approval was already consumed") from error

    def _resolve(
        self,
        revision_id: str,
        *,
        actor: str,
        status: ApprovalStatus,
        target: RevisionStatus,
        reason_code: str | None,
        expected_binding_sha256: str | None,
    ) -> ApprovalRecord:
        revision = self._revision_or_deny(revision_id)
        if revision.status is RevisionStatus.BLOCKED:
            raise ApprovalDenied("a blocked revision can never be approved")
        if revision.status is not RevisionStatus.AWAITING_APPROVAL:
            raise ApprovalDenied("revision is not awaiting approval")
        if not actor.strip() or actor == revision.requester_id:
            raise ApprovalDenied("the requester cannot review their own revision")
        try:
            approval = self.repository.get_approval_for_revision(revision_id)
        except KeyError as error:
            raise ApprovalDenied("revision has no pending approval request") from error
        now = self._now()
        self._validate_exact(approval, revision, now)
        if (
            expected_binding_sha256 is not None
            and expected_binding_sha256 != approval.binding_sha256
        ):
            raise ApprovalDenied("presented approval binding is stale")
        transition_status(revision.status, target)
        try:
            return self.repository.resolve_approval(
                approval.id,
                reviewer_id=actor,
                status=status,
                reviewed_at=now,
                reason_code=reason_code,
                expected_revision_status=revision.status,
                target_revision_status=target,
            )
        except StorageConflictError as error:
            raise ApprovalDenied("approval was changed concurrently") from error

    @staticmethod
    def _validate_exact(
        approval: ApprovalRecord,
        revision: DisclosureRevision,
        now: datetime,
    ) -> None:
        if approval.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise ApprovalDenied("approval is no longer active")
        if approval.expires_at <= now:
            raise ApprovalDenied("approval request has expired")
        binding = approval_binding(revision)
        if binding.sha256 != approval.binding_sha256:
            raise ApprovalDenied("revision no longer matches the exact approval binding")
        if (
            approval.source_sha256 != binding.source_sha256
            or approval.context_sha256 != binding.context_sha256
            or approval.policy_sha256 != binding.policy_sha256
            or approval.output_sha256 != binding.output_sha256
            or approval.decision_manifest_sha256 != binding.decision_manifest_sha256
        ):
            raise ApprovalDenied("approval component hashes do not match the revision")

    def _revision_or_deny(self, revision_id: str) -> DisclosureRevision:
        try:
            return self.repository.get_revision(revision_id)
        except KeyError as error:
            raise ApprovalDenied("revision does not exist") from error

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ApprovalDenied("approval clock must be timezone aware")
        return value.astimezone(UTC)
