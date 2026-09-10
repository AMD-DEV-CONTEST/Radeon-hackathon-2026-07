"""Artifact routing total-function and priority contract tests."""

from __future__ import annotations

import itertools

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RepairStopReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.verification.routing import decide_artifact
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)


def artifact(value: str) -> ArtifactRef:
    return ArtifactRef(ArtifactId(value), Sha256("a" * 64))


def rule(
    value: str,
    *,
    required: bool = True,
    scope: RuleScope = RuleScope.ITEM,
    warning: str = "manual_review",
    unverifiable: str = "reject",
) -> RuleDefinition:
    return RuleDefinition(
        RuleId(value),
        RuleLevel.L1,
        scope,
        required,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", unverifiable, warning),
    )  # type: ignore[arg-type]


def result(
    value: str, status: RuleStatus, ids: tuple[str, ...] = ("one",)
) -> RuleResult:
    return RuleResult(RuleId(value), status, tuple(ArtifactId(x) for x in ids), None)


def report(
    rules: tuple[RuleDefinition, ...],
    results: tuple[RuleResult, ...],
    artifacts: tuple[ArtifactRef, ...] = (artifact("one"),),
) -> VerificationReport:
    return VerificationReport(artifacts, rules, results)


def assert_decision(decision, status: ArtifactStatus, reason: DecisionReason) -> None:
    assert (decision.artifact_status, decision.decision_reason) == (status, reason)


def test_approved_only_when_all_affecting_required_results_pass() -> None:
    decision = decide_artifact(
        report(
            (rule("item"), rule("batch", scope=RuleScope.BATCH)),
            (result("item", RuleStatus.PASS), result("batch", RuleStatus.PASS)),
        ),
        ArtifactId("one"),
    )
    assert_decision(decision, ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS)
    assert decision.repair_stop_reason is None
    assert not decision.accepted_with_override


def test_required_warning_manual_policy_routes_to_manual_review() -> None:
    decision = decide_artifact(
        report(
            (rule("rule", warning="manual_review"),),
            (result("rule", RuleStatus.WARNING),),
        ),
        ArtifactId("one"),
    )
    assert_decision(
        decision, ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY
    )


@pytest.mark.parametrize(
    "stop",
    (
        RepairStopReason.NO_ACTION,
        RepairStopReason.NO_IMPROVEMENT,
        RepairStopReason.MAX_ROUNDS,
    ),
)
def test_exhausted_repair_with_remaining_required_nonpass_rejects(
    stop: RepairStopReason,
) -> None:
    decision = decide_artifact(
        report(
            (rule("rule", warning="manual_review"),),
            (result("rule", RuleStatus.WARNING),),
        ),
        ArtifactId("one"),
        repair_stop_reason=stop,
    )
    assert_decision(decision, ArtifactStatus.REJECTED, DecisionReason.REPAIR_EXHAUSTED)


def test_required_failure_and_reject_warning_route_to_gate_failure() -> None:
    fail = decide_artifact(
        report((rule("rule"),), (result("rule", RuleStatus.FAIL),)), ArtifactId("one")
    )
    warning = decide_artifact(
        report(
            (rule("rule", warning="reject"),), (result("rule", RuleStatus.WARNING),)
        ),
        ArtifactId("one"),
    )
    assert_decision(fail, ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED)
    assert_decision(
        warning, ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED
    )


def test_required_unverifiable_reject_has_highest_priority() -> None:
    decision = decide_artifact(
        report(
            (rule("unverifiable", unverifiable="reject"), rule("failed")),
            (
                result("unverifiable", RuleStatus.UNVERIFIABLE),
                result("failed", RuleStatus.FAIL),
            ),
        ),
        ArtifactId("one"),
        repair_stop_reason=RepairStopReason.NO_ACTION,
    )
    assert_decision(
        decision, ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_UNVERIFIABLE
    )


def test_required_fail_outranks_manual_candidate_and_repair_exhaustion_outranks_fail() -> (
    None
):
    rules = (rule("failed"), rule("manual", warning="manual_review"))
    results = (result("failed", RuleStatus.FAIL), result("manual", RuleStatus.WARNING))
    assert_decision(
        decide_artifact(report(rules, results), ArtifactId("one")),
        ArtifactStatus.REJECTED,
        DecisionReason.REQUIRED_GATE_FAILED,
    )
    assert_decision(
        decide_artifact(
            report(rules, results),
            ArtifactId("one"),
            repair_stop_reason=RepairStopReason.MAX_ROUNDS,
        ),
        ArtifactStatus.REJECTED,
        DecisionReason.REPAIR_EXHAUSTED,
    )


def test_advisory_fail_does_not_block_approval_but_manual_advisory_warning_does() -> (
    None
):
    approved = decide_artifact(
        report(
            (rule("required"), rule("advisory", required=False)),
            (result("required", RuleStatus.PASS), result("advisory", RuleStatus.FAIL)),
        ),
        ArtifactId("one"),
    )
    manual = decide_artifact(
        report(
            (
                rule("required"),
                rule("advisory", required=False, warning="manual_review"),
            ),
            (
                result("required", RuleStatus.PASS),
                result("advisory", RuleStatus.WARNING),
            ),
        ),
        ArtifactId("one"),
    )
    assert_decision(approved, ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS)
    assert_decision(manual, ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY)


def test_advisory_reject_or_continue_never_turns_warning_or_unverifiable_into_rejection() -> (
    None
):
    for status, warning in itertools.product(
        (RuleStatus.WARNING, RuleStatus.UNVERIFIABLE), ("reject", "continue")
    ):
        unverifiable = "reject"
        decision = decide_artifact(
            report(
                (
                    rule("required"),
                    rule(
                        "advisory",
                        required=False,
                        warning=warning,
                        unverifiable=unverifiable,
                    ),
                ),
                (result("required", RuleStatus.PASS), result("advisory", status)),
            ),
            ArtifactId("one"),
        )
        assert_decision(
            decision, ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS
        )


def test_manual_stop_routes_to_manual_review_and_override_only_allowed_there() -> None:
    manual = decide_artifact(
        report((rule("required"),), (result("required", RuleStatus.PASS),)),
        ArtifactId("one"),
        repair_stop_reason=RepairStopReason.MANUAL_REQUEST,
        accepted_with_override=True,
    )
    assert_decision(manual, ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY)
    assert manual.accepted_with_override
    with pytest.raises(DomainError):
        decide_artifact(
            report((rule("required"),), (result("required", RuleStatus.PASS),)),
            ArtifactId("one"),
            accepted_with_override=True,
        )


def test_stop_reason_consistency_is_enforced() -> None:
    passed = report((rule("required"),), (result("required", RuleStatus.PASS),))
    failed = report((rule("required"),), (result("required", RuleStatus.FAIL),))
    unverified = report(
        (rule("required", unverifiable="manual_review"),),
        (result("required", RuleStatus.UNVERIFIABLE),),
    )
    with pytest.raises(DomainError):
        decide_artifact(
            failed,
            ArtifactId("one"),
            repair_stop_reason=RepairStopReason.PASS_ALL_REQUIRED,
        )
    with pytest.raises(DomainError):
        decide_artifact(
            passed, ArtifactId("one"), repair_stop_reason=RepairStopReason.NO_ACTION
        )
    with pytest.raises(DomainError):
        decide_artifact(
            passed, ArtifactId("one"), repair_stop_reason=RepairStopReason.UNVERIFIABLE
        )
    with pytest.raises(DomainError):
        decide_artifact(
            failed, ArtifactId("one"), repair_stop_reason=RepairStopReason.UNVERIFIABLE
        )
    assert_decision(
        decide_artifact(
            unverified,
            ArtifactId("one"),
            repair_stop_reason=RepairStopReason.UNVERIFIABLE,
        ),
        ArtifactStatus.MANUAL_REVIEW,
        DecisionReason.MANUAL_POLICY,
    )


def test_route_requires_an_applicable_required_gate_for_target() -> None:
    with pytest.raises(DomainError):
        decide_artifact(
            report(
                (rule("advisory", required=False),),
                (result("advisory", RuleStatus.PASS),),
            ),
            ArtifactId("one"),
        )


def test_unknown_artifact_and_wrong_optional_field_types_are_domain_errors() -> None:
    valid = report((rule("required"),), (result("required", RuleStatus.PASS),))
    with pytest.raises(DomainError):
        decide_artifact(valid, ArtifactId("missing"))
    with pytest.raises(DomainError):
        decide_artifact(valid, "one")  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        decide_artifact(valid, ArtifactId("one"), repair_stop_reason="NO_ACTION")  # type: ignore[arg-type]
    with pytest.raises(DomainError):
        decide_artifact(valid, ArtifactId("one"), accepted_with_override=1)  # type: ignore[arg-type]


def test_decision_is_invariant_to_rule_and_result_permutations() -> None:
    rules = (
        rule("item"),
        rule("batch", scope=RuleScope.BATCH),
        rule("advisory", required=False),
    )
    results = (
        result("item", RuleStatus.PASS),
        result("batch", RuleStatus.PASS),
        result("advisory", RuleStatus.FAIL),
    )
    expected = decide_artifact(report(rules, results), ArtifactId("one"))
    for rule_order in itertools.permutations(rules):
        for result_order in itertools.permutations(results):
            assert (
                decide_artifact(report(rule_order, result_order), ArtifactId("one"))
                == expected
            )
