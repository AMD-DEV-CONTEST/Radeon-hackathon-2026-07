"""Verification core rule/report model contract tests."""

from __future__ import annotations

import dataclasses
import math

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import (
    ArtifactStatus,
    DecisionReason,
    RuleLevel,
    RuleScope,
    RuleStatus,
    StaticApplicability,
)
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.verification.rule_models import (
    ArtifactDecision,
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)


def artifact(value: str) -> ArtifactRef:
    return ArtifactRef(ArtifactId(value), Sha256("a" * 64))


def policy(
    *, warning: str = "manual_review", unverifiable: str = "reject"
) -> GatePolicy:
    return GatePolicy("reject", unverifiable, warning)  # type: ignore[arg-type]


def rule(
    value: str,
    *,
    scope: RuleScope = RuleScope.ITEM,
    required: bool = True,
    applicability: StaticApplicability = StaticApplicability.APPLICABLE,
    gate_policy: GatePolicy | None = None,
) -> RuleDefinition:
    return RuleDefinition(
        RuleId(value),
        RuleLevel.L1,
        scope,
        required,
        applicability,
        gate_policy or policy(),
    )


def item_result(
    value: str, artifact_id: str, status: RuleStatus = RuleStatus.PASS
) -> RuleResult:
    return RuleResult(RuleId(value), status, (ArtifactId(artifact_id),), 0.5)


def batch_result(
    value: str, artifact_ids: tuple[str, ...], status: RuleStatus = RuleStatus.PASS
) -> RuleResult:
    return RuleResult(
        RuleId(value), status, tuple(ArtifactId(x) for x in artifact_ids), None
    )


def test_models_are_frozen_slots_dataclasses() -> None:
    verification_report = VerificationReport(
        (artifact("one"),), (rule("rule"),), (item_result("rule", "one"),)
    )
    decision = ArtifactDecision(
        ArtifactId("one"),
        ArtifactStatus.APPROVED,
        DecisionReason.ALL_REQUIRED_PASS,
        None,
        False,
    )
    objects = (
        policy(),
        rule("rule"),
        item_result("rule", "one"),
        verification_report,
        decision,
    )
    for value in objects:
        assert dataclasses.is_dataclass(value)
        assert not hasattr(value, "__dict__")
        with pytest.raises(dataclasses.FrozenInstanceError):
            value.__class__.__setattr__(
                value, next(iter(value.__dataclass_fields__)), None
            )


@pytest.mark.parametrize("field", ("on_fail", "on_unverifiable", "on_warning"))
def test_gate_policy_rejects_non_exact_or_unknown_policy_values(field: str) -> None:
    values = {
        "on_fail": "reject",
        "on_unverifiable": "reject",
        "on_warning": "continue",
    }
    values[field] = "invalid"
    with pytest.raises(DomainError):
        GatePolicy(**values)
    values[field] = True  # type: ignore[assignment]
    with pytest.raises(DomainError):
        GatePolicy(**values)


def test_required_rule_cannot_continue_on_warning() -> None:
    with pytest.raises(DomainError):
        rule("rule", gate_policy=policy(warning="continue"))


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("rule_id", "rule"),
        ("level", "L1"),
        ("scope", "ITEM"),
        ("required", 1),
        ("applicability", "APPLICABLE"),
    ),
)
def test_rule_definition_requires_exact_field_types(field: str, bad: object) -> None:
    values: dict[str, object] = {
        "rule_id": RuleId("rule"),
        "level": RuleLevel.L1,
        "scope": RuleScope.ITEM,
        "required": True,
        "applicability": StaticApplicability.APPLICABLE,
        "gate_policy": policy(),
    }
    values[field] = bad
    with pytest.raises(DomainError):
        RuleDefinition(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", (0, True, "0.5", math.nan, math.inf, -math.inf))
def test_rule_result_rejects_non_exact_or_non_finite_score(bad: object) -> None:
    with pytest.raises(DomainError):
        RuleResult(RuleId("rule"), RuleStatus.PASS, (ArtifactId("one"),), bad)  # type: ignore[arg-type]


def test_rule_result_accepts_only_exact_finite_float_or_none() -> None:
    assert item_result("rule", "one").score == 0.5
    assert batch_result("rule", ("one",)).score is None


@pytest.mark.parametrize(
    ("rule_id", "status", "affected"),
    (
        ("rule", RuleStatus.PASS, (ArtifactId("one"),)),
        (RuleId("rule"), "PASS", (ArtifactId("one"),)),
        (RuleId("rule"), RuleStatus.PASS, [ArtifactId("one")]),
    ),
)
def test_rule_result_requires_exact_id_status_and_tuple(
    rule_id: object, status: object, affected: object
) -> None:
    with pytest.raises(DomainError):
        RuleResult(rule_id, status, affected, None)  # type: ignore[arg-type]


def test_not_applicable_rule_must_not_have_result() -> None:
    with pytest.raises(DomainError):
        VerificationReport(
            (artifact("one"),),
            (rule("rule", applicability=StaticApplicability.NOT_APPLICABLE),),
            (item_result("rule", "one"),),
        )


def test_report_requires_nonempty_unique_artifacts_and_unique_rules() -> None:
    with pytest.raises(DomainError):
        VerificationReport((), (), ())
    with pytest.raises(DomainError):
        VerificationReport((artifact("one"), artifact("one")), (), ())
    with pytest.raises(DomainError):
        VerificationReport((artifact("one"),), (rule("same"), rule("same")), ())


def test_report_rejects_unknown_rule_or_artifact_result_reference() -> None:
    with pytest.raises(DomainError):
        VerificationReport(
            (artifact("one"),), (rule("known"),), (item_result("unknown", "one"),)
        )
    with pytest.raises(DomainError):
        VerificationReport(
            (artifact("one"),), (rule("known"),), (item_result("known", "missing"),)
        )


def test_item_rule_requires_exactly_one_result_per_artifact() -> None:
    artifacts = (artifact("one"), artifact("two"))
    item = rule("item")
    with pytest.raises(DomainError):
        VerificationReport(artifacts, (item,), (item_result("item", "one"),))
    with pytest.raises(DomainError):
        VerificationReport(
            artifacts,
            (item,),
            (
                item_result("item", "one"),
                item_result("item", "one"),
                item_result("item", "two"),
            ),
        )
    with pytest.raises(DomainError):
        VerificationReport(
            artifacts,
            (item,),
            (
                RuleResult(
                    RuleId("item"),
                    RuleStatus.PASS,
                    (ArtifactId("one"), ArtifactId("two")),
                    None,
                ),
            ),
        )


def test_batch_rule_requires_one_full_ordered_batch_result() -> None:
    artifacts = (artifact("one"), artifact("two"))
    batch = rule("batch", scope=RuleScope.BATCH)
    with pytest.raises(DomainError):
        VerificationReport(artifacts, (batch,), ())
    with pytest.raises(DomainError):
        VerificationReport(
            artifacts, (batch,), (batch_result("batch", ("two", "one")),)
        )
    with pytest.raises(DomainError):
        VerificationReport(
            artifacts,
            (batch,),
            (batch_result("batch", ("one",)), batch_result("batch", ("one", "two"))),
        )


def test_complete_item_and_batch_report_is_valid() -> None:
    artifacts = (artifact("one"), artifact("two"))
    report = VerificationReport(
        artifacts,
        (
            rule("item"),
            rule("batch", scope=RuleScope.BATCH),
            rule("na", applicability=StaticApplicability.NOT_APPLICABLE),
        ),
        (
            item_result("item", "two"),
            batch_result("batch", ("one", "two")),
            item_result("item", "one"),
        ),
    )
    assert report.artifacts == artifacts


def test_constructor_signature_errors_remain_type_error() -> None:
    with pytest.raises(TypeError):
        GatePolicy("reject", "reject")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RuleResult(
            RuleId("r"), RuleStatus.PASS, (ArtifactId("a"),), None, unexpected=True
        )  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("status", "reason"),
    (
        (ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS),
        (ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY),
        (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED),
        (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_UNVERIFIABLE),
        (ArtifactStatus.REJECTED, DecisionReason.REPAIR_EXHAUSTED),
    ),
)
def test_artifact_decision_accepts_only_the_five_legal_terminal_pairs(
    status: ArtifactStatus, reason: DecisionReason
) -> None:
    decision = ArtifactDecision(ArtifactId("one"), status, reason, None, False)
    assert (decision.artifact_status, decision.decision_reason) == (status, reason)


@pytest.mark.parametrize(
    ("status", "reason"),
    tuple(
        (status, reason)
        for status in ArtifactStatus
        for reason in DecisionReason
        if (status, reason)
        not in {
            (ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS),
            (ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY),
            (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED),
            (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_UNVERIFIABLE),
            (ArtifactStatus.REJECTED, DecisionReason.REPAIR_EXHAUSTED),
        }
    ),
)
def test_artifact_decision_rejects_illegal_terminal_status_reason_pairs(
    status: ArtifactStatus, reason: DecisionReason
) -> None:
    with pytest.raises(DomainError):
        ArtifactDecision(ArtifactId("one"), status, reason, None, False)


@pytest.mark.parametrize(
    ("status", "reason"),
    (
        (ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS),
        (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED),
        (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_UNVERIFIABLE),
        (ArtifactStatus.REJECTED, DecisionReason.REPAIR_EXHAUSTED),
    ),
)
def test_artifact_decision_override_requires_manual_review_manual_policy_pair(
    status: ArtifactStatus, reason: DecisionReason
) -> None:
    with pytest.raises(DomainError):
        ArtifactDecision(ArtifactId("one"), status, reason, None, True)
    assert ArtifactDecision(
        ArtifactId("one"),
        ArtifactStatus.MANUAL_REVIEW,
        DecisionReason.MANUAL_POLICY,
        None,
        True,
    ).accepted_with_override
