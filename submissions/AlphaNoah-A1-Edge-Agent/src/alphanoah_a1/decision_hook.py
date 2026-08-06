"""Deterministic DecisionHook for the bounded hackathon workflow."""

from __future__ import annotations

from .models import (
    Decision,
    EventStatus,
    HookAction,
    HookResult,
    HumanReviewOutcome,
)


class DecisionHook:
    """Route a validated decision without delegating control to a model."""

    def evaluate(self, decision: Decision) -> HookResult:
        if not decision.evidence or decision.confidence < 0.50:
            return HookResult(
                action=HookAction.REQUEST_MORE_EVIDENCE,
                target_status=EventStatus.NEEDS_MORE_EVIDENCE,
                reason="Decision evidence is incomplete or confidence is below 0.50.",
            )

        if decision.risk_level == "CRITICAL":
            return HookResult(
                action=HookAction.ESCALATE,
                target_status=EventStatus.ESCALATED,
                reason="Critical-risk decisions require escalation outside the demo.",
            )

        if decision.requires_human_review:
            return HookResult(
                action=HookAction.REQUEST_HUMAN_REVIEW,
                target_status=EventStatus.PENDING_HUMAN_REVIEW,
                reason="The validated decision requires a human decision.",
            )

        if decision.decision_type == "no_issue":
            return HookResult(
                action=HookAction.AUTO_APPROVE,
                target_status=EventStatus.CLOSED,
                reason=(
                    "The deterministic rule found no anomaly requiring a task; "
                    "the event can close without an execution step."
                ),
            )

        return HookResult(
            action=HookAction.REQUEST_HUMAN_REVIEW,
            target_status=EventStatus.PENDING_HUMAN_REVIEW,
            reason="Unrecognized non-critical outcomes default to human review.",
        )

    def after_human_review(
        self, decision: Decision, outcome: HumanReviewOutcome
    ) -> HookResult:
        """Route an explicit human outcome; never synthesize the human actor."""

        if outcome is HumanReviewOutcome.APPROVED:
            return HookResult(
                action=HookAction.CREATE_TASK,
                target_status=EventStatus.APPROVED,
                reason=(
                    f"Human approval authorizes task creation for "
                    f"{decision.decision_id}."
                ),
            )
        if outcome is HumanReviewOutcome.REJECTED:
            return HookResult(
                action=HookAction.REJECT,
                target_status=EventStatus.REJECTED,
                reason="The human reviewer rejected the proposed decision.",
            )
        return HookResult(
            action=HookAction.REQUEST_MORE_EVIDENCE,
            target_status=EventStatus.NEEDS_MORE_EVIDENCE,
            reason="The human reviewer requested a revised decision or evidence.",
        )
