"""Human-approval state machine and external-status guardrails."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.schemas.rights import (
    EXTERNAL_TASK_STATES,
    ApprovalDecision,
    ApprovalRecord,
    HumanApprovalState,
    ReviewApplicationDraft,
    RightsTaskStatus,
)


class ApprovalRequired(PermissionError):
    pass


class HumanApprovalManager:
    @staticmethod
    def pending_for(draft: ReviewApplicationDraft) -> HumanApprovalState:
        return HumanApprovalState(
            state=ApprovalDecision.PENDING,
            document_version=draft.document_version,
            inputs_hash=draft.inputs_hash,
        )

    @staticmethod
    def decide(
        approval: HumanApprovalState,
        *,
        decision: ApprovalDecision,
        approver: str,
        comments: str,
        audit_event_id: str,
        document_version: int,
        inputs_hash: str,
        timestamp: datetime | None = None,
    ) -> HumanApprovalState:
        if decision in {ApprovalDecision.PENDING, ApprovalDecision.EXPIRED}:
            raise ValueError("Human decisions must be approved, rejected, or changes_requested.")
        if (
            approval.document_version != document_version
            or approval.inputs_hash != inputs_hash
        ):
            raise ValueError("Document version or inputs hash changed before approval.")
        record = ApprovalRecord(
            approver=approver,
            timestamp=timestamp or datetime.now(ZoneInfo("Asia/Shanghai")),
            decision=decision,
            comments=comments,
            document_version=document_version,
            inputs_hash=inputs_hash,
            audit_event_id=audit_event_id,
        )
        return HumanApprovalState(
            state=decision,
            document_version=document_version,
            inputs_hash=inputs_hash,
            record=record,
        )

    @staticmethod
    def invalidate_if_changed(
        approval: HumanApprovalState,
        *,
        document_version: int,
        inputs_hash: str,
    ) -> HumanApprovalState:
        if (
            approval.document_version == document_version
            and approval.inputs_hash == inputs_hash
        ):
            return approval
        return HumanApprovalState(
            state=ApprovalDecision.PENDING,
            document_version=document_version,
            inputs_hash=inputs_hash,
            invalidation_reason=(
                "文书版本或关键输入已变化，原审批自动失效并重新进入pending。"
            ),
        )

    @staticmethod
    def expire(
        approval: HumanApprovalState,
        *,
        actor: str,
        comments: str,
        audit_event_id: str,
        timestamp: datetime | None = None,
    ) -> HumanApprovalState:
        record = ApprovalRecord(
            approver=actor,
            timestamp=timestamp or datetime.now(ZoneInfo("Asia/Shanghai")),
            decision=ApprovalDecision.EXPIRED,
            comments=comments,
            document_version=approval.document_version,
            inputs_hash=approval.inputs_hash,
            audit_event_id=audit_event_id,
        )
        return HumanApprovalState(
            state=ApprovalDecision.EXPIRED,
            document_version=approval.document_version,
            inputs_hash=approval.inputs_hash,
            record=record,
        )

    @staticmethod
    def enforce_task_status(
        requested_status: RightsTaskStatus,
        approval: HumanApprovalState,
        draft: ReviewApplicationDraft | None = None,
    ) -> None:
        if requested_status not in EXTERNAL_TASK_STATES:
            return
        if approval.state is not ApprovalDecision.APPROVED:
            raise ApprovalRequired(
                f"{requested_status.value} requires a fresh approved human decision."
            )
        if draft is None:
            raise ApprovalRequired(
                f"{requested_status.value} requires the current reviewed draft."
            )
        if not draft.submittable_after_approval:
            raise ApprovalRequired(
                f"{requested_status.value} is blocked by incomplete draft fields."
            )
