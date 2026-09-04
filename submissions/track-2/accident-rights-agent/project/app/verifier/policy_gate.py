"""Aggregate all fail-closed checks before Human Approval."""

from __future__ import annotations

from app.schemas.verification import (
    ComponentVerifierResult,
    PolicyGateDecision,
    PolicyGateResult,
    RiskAction,
    RiskLanguageResult,
    VerificationIssue,
    VerificationSeverity,
)


class FinalPolicyGate:
    def evaluate(
        self,
        *,
        evidence: ComponentVerifierResult,
        legal: ComponentVerifierResult,
        consistency: ComponentVerifierResult,
        risk_language: RiskLanguageResult,
        protected_fields_valid: bool,
        approval_state: str,
    ) -> PolicyGateResult:
        blocking = [
            issue
            for result in (evidence, legal, consistency)
            for issue in result.issues
            if issue.severity is VerificationSeverity.BLOCKING
        ]
        warnings = [
            issue
            for result in (evidence, legal, consistency)
            for issue in result.issues
            if issue.severity is VerificationSeverity.WARNING
        ]
        for match in risk_language.matches:
            issue = VerificationIssue(
                code=f"RISK-{match.pattern_id}",
                message=f"High-risk wording at {match.path}: {match.matched_text}",
                severity=(
                    VerificationSeverity.BLOCKING
                    if match.action is RiskAction.HARD_BLOCK
                    else VerificationSeverity.WARNING
                ),
                path=match.path,
                required_action=(
                    "Remove prohibited language."
                    if match.action is RiskAction.HARD_BLOCK
                    else "Apply the configured qualified rewrite."
                ),
            )
            (blocking if issue.severity is VerificationSeverity.BLOCKING else warnings).append(
                issue
            )
        if not protected_fields_valid:
            blocking.append(
                VerificationIssue(
                    code="POLICY-PROTECTED-FIELDS",
                    message="ProtectedField validation did not pass.",
                    severity=VerificationSeverity.BLOCKING,
                    required_action="Restore all protected fields and rerun the node.",
                )
            )
        if approval_state != "approved":
            warnings.append(
                VerificationIssue(
                    code="POLICY-HUMAN-APPROVAL-PENDING",
                    message="External submission remains blocked pending human approval.",
                    severity=VerificationSeverity.WARNING,
                    required_action="A human approver must review the exact document version.",
                )
            )
        if blocking:
            decision = PolicyGateDecision.BLOCK
        elif warnings:
            decision = PolicyGateDecision.PASS_WITH_WARNINGS
        else:
            decision = PolicyGateDecision.PASS
        return PolicyGateResult(
            decision=decision,
            blocking_issues=blocking,
            warnings=warnings,
            required_actions=sorted(
                {
                    item.required_action
                    for item in [*blocking, *warnings]
                    if item.required_action
                }
            ),
            verified_evidence_ids=evidence.verified_ids,
            verified_law_ids=legal.verified_ids,
            approval_required=True,
            audit_event_ids=[
                *evidence.audit_event_ids,
                *legal.audit_event_ids,
                *consistency.audit_event_ids,
                *risk_language.audit_event_ids,
            ],
        )
