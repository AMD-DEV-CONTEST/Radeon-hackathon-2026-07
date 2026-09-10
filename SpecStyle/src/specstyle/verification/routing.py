"""Pure, order-independent verification report routing."""

from __future__ import annotations

from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId
from specstyle.errors import DomainError
from specstyle.verification.rule_models import (
    ArtifactDecision,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)


_EXHAUSTED = frozenset(
    {
        RepairStopReason.NO_ACTION,
        RepairStopReason.NO_IMPROVEMENT,
        RepairStopReason.MAX_ROUNDS,
    }
)


def decide_artifact(
    report: VerificationReport,
    artifact_id: ArtifactId,
    *,
    repair_stop_reason: RepairStopReason | None = None,
    accepted_with_override: bool = False,
) -> ArtifactDecision:
    if type(report) is not VerificationReport:
        raise DomainError("report must be VerificationReport")
    if type(artifact_id) is not ArtifactId:
        raise DomainError("artifact_id must be ArtifactId")
    if (
        repair_stop_reason is not None
        and type(repair_stop_reason) is not RepairStopReason
    ):
        raise DomainError("repair_stop_reason must be RepairStopReason or None")
    if type(accepted_with_override) is not bool:
        raise DomainError("accepted_with_override must be bool")
    if artifact_id not in {artifact.artifact_id for artifact in report.artifacts}:
        raise DomainError("artifact_id is not in report")

    relevant = _results_affecting_artifact(report, artifact_id)
    required = [(rule, result) for rule, result in relevant if rule.required]
    if not required:
        raise DomainError("artifact has no applicable required gate")
    required_nonpass = any(
        result.status is not RuleStatus.PASS for _, result in required
    )
    _validate_stop_reason(repair_stop_reason, required)

    if any(
        result.status is RuleStatus.UNVERIFIABLE
        and rule.gate_policy.on_unverifiable == "reject"
        for rule, result in required
    ):
        status, reason = (
            ArtifactStatus.REJECTED,
            DecisionReason.REQUIRED_GATE_UNVERIFIABLE,
        )
    elif repair_stop_reason in _EXHAUSTED and required_nonpass:
        status, reason = ArtifactStatus.REJECTED, DecisionReason.REPAIR_EXHAUSTED
    elif any(
        result.status is RuleStatus.FAIL
        or (
            result.status is RuleStatus.WARNING
            and rule.gate_policy.on_warning == "reject"
        )
        for rule, result in required
    ):
        status, reason = ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED
    elif repair_stop_reason is RepairStopReason.MANUAL_REQUEST or _has_manual_policy(
        relevant
    ):
        status, reason = ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY
    elif all(result.status is RuleStatus.PASS for _, result in required):
        status, reason = ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS
    else:
        raise DomainError("required gate state has no valid terminal route")

    if accepted_with_override and status is not ArtifactStatus.MANUAL_REVIEW:
        raise DomainError("override is only valid for manual review")
    return ArtifactDecision(
        artifact_id, status, reason, repair_stop_reason, accepted_with_override
    )


def _results_affecting_artifact(
    report: VerificationReport, artifact_id: ArtifactId
) -> list[tuple[RuleDefinition, RuleResult]]:
    rules = {rule.rule_id: rule for rule in report.rules}
    return [
        (rules[result.rule_id], result)
        for result in report.results
        if artifact_id in result.affected_artifact_ids
        and rules[result.rule_id].applicability is StaticApplicability.APPLICABLE
        and rules[result.rule_id].scope in {RuleScope.ITEM, RuleScope.BATCH}
    ]


def _validate_stop_reason(
    stop_reason: RepairStopReason | None,
    required: list[tuple[RuleDefinition, RuleResult]],
) -> None:
    required_nonpass = any(
        result.status is not RuleStatus.PASS for _, result in required
    )
    if stop_reason is RepairStopReason.PASS_ALL_REQUIRED and required_nonpass:
        raise DomainError("PASS_ALL_REQUIRED conflicts with required non-pass result")
    if stop_reason in _EXHAUSTED and not required_nonpass:
        raise DomainError("repair exhaustion conflicts with all required pass")
    if stop_reason is RepairStopReason.UNVERIFIABLE and not any(
        result.status is RuleStatus.UNVERIFIABLE for _, result in required
    ):
        raise DomainError("UNVERIFIABLE stop requires required unverifiable result")


def _has_manual_policy(relevant: list[tuple[RuleDefinition, RuleResult]]) -> bool:
    for rule, result in relevant:
        if (
            result.status is RuleStatus.WARNING
            and rule.gate_policy.on_warning == "manual_review"
        ):
            return True
        if (
            result.status is RuleStatus.UNVERIFIABLE
            and rule.gate_policy.on_unverifiable == "manual_review"
        ):
            return True
    return False
