from dataclasses import replace

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import ArtifactId, DecisionId, RuleId, Sha256
from specstyle.errors import DomainError
from specstyle.repair.actions import INCREASE_STYLE_SCALE, plan_repair_action
from specstyle.repair.guardrails import is_repair_improvement, required_gate_vector
from specstyle.spec.compiled_models import CompiledVerificationPlan
from specstyle.verification.rule_models import (
    GatePolicy,
    RuleDefinition,
    RuleResult,
    VerificationReport,
)
from tests.unit.repair.test_actions import _repair_request


class SelfSafeCrossExplodingText(str):
    def __hash__(self) -> int:
        return str.__hash__(self)

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        raise RuntimeError("cross-object equality exploded")

    def __ne__(self, other: object) -> bool:
        if self is other:
            return False
        raise RuntimeError("cross-object equality exploded")


def _request_and_plan() -> tuple[object, CompiledVerificationPlan]:
    request = _repair_request()
    base_plan = request.compiled_spec.verification_plans[0]
    base_rule = next(
        rule for rule in base_plan.rules if rule.definition.rule_id == RuleId("l1")
    )
    rules = tuple(
        replace(
            base_rule,
            definition=RuleDefinition(
                RuleId(name),
                RuleLevel.L1,
                RuleScope.ITEM,
                True,
                StaticApplicability.APPLICABLE,
                GatePolicy("reject", "reject", "reject"),
            ),
            priority=index,
            affected_by_actions=(INCREASE_STYLE_SCALE,),
        )
        for index, name in enumerate(("PREFIX", "STYLE_LOW", "LATER"))
    )
    plan = replace(base_plan, rules=rules)
    return replace(
        request,
        compiled_spec=replace(request.compiled_spec, verification_plans=(plan,)),
    ), plan


def _report(
    plan: CompiledVerificationPlan,
    statuses: dict[str, RuleStatus],
    *,
    score: float = 0.0,
) -> VerificationReport:
    artifact = ArtifactRef(ArtifactId("target"), Sha256("c" * 64))
    results = tuple(
        RuleResult(
            rule.rule_id, statuses[rule.rule_id.value], (ArtifactId("target"),), score
        )
        for rule in plan.applicable_rule_definitions
    )
    return VerificationReport((artifact,), plan.applicable_rule_definitions, results)


def test_required_vector_and_improvement_use_ordered_gate_bits_not_scores() -> None:
    request, plan = _request_and_plan()
    parent = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.FAIL,
            "LATER": RuleStatus.FAIL,
        },
        score=1.0,
    )
    child = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.PASS,
            "LATER": RuleStatus.FAIL,
        },
        score=0.0,
    )
    decision = plan_repair_action(
        request, DecisionId("decision"), RuleId("STYLE_LOW"), INCREASE_STYLE_SCALE
    )

    assert required_gate_vector(plan, parent, ArtifactId("target")) == (0, 1, 1)
    assert required_gate_vector(plan, child, ArtifactId("target")) == (0, 0, 1)
    assert (
        is_repair_improvement(
            plan, parent, child, ArtifactId("target"), ArtifactId("target"), decision
        )
        is True
    )


@pytest.mark.parametrize(
    ("parent_statuses", "child_statuses", "expected"),
    (
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.FAIL,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.FAIL,
            },
            False,
        ),
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            False,
        ),
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.FAIL,
            },
            True,
        ),
    ),
)
def test_guardrail_rejects_prefix_or_non_improving_outcomes(
    parent_statuses: dict[str, RuleStatus],
    child_statuses: dict[str, RuleStatus],
    expected: bool,
) -> None:
    request, plan = _request_and_plan()
    parent = _report(plan, parent_statuses)
    child = _report(plan, child_statuses)
    decision = plan_repair_action(
        request, DecisionId("decision"), RuleId("STYLE_LOW"), INCREASE_STYLE_SCALE
    )

    assert (
        is_repair_improvement(
            plan, parent, child, ArtifactId("target"), ArtifactId("target"), decision
        )
        is expected
    )


def test_guardrail_rejects_wrong_parent_trigger_and_invalid_target() -> None:
    request, plan = _request_and_plan()
    parent = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.FAIL,
            "LATER": RuleStatus.FAIL,
        },
    )
    child = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.PASS,
            "LATER": RuleStatus.FAIL,
        },
    )
    wrong_trigger = plan_repair_action(
        request, DecisionId("decision"), RuleId("PREFIX"), INCREASE_STYLE_SCALE
    )

    with pytest.raises(DomainError):
        is_repair_improvement(
            plan,
            parent,
            child,
            ArtifactId("target"),
            ArtifactId("target"),
            wrong_trigger,
        )
    with pytest.raises(DomainError):
        required_gate_vector(plan, parent, ArtifactId("missing"))


@pytest.mark.parametrize(
    ("status", "bit"),
    (
        (RuleStatus.PASS, 0),
        (RuleStatus.FAIL, 1),
        (RuleStatus.WARNING, 1),
        (RuleStatus.UNVERIFIABLE, 1),
    ),
)
def test_required_vector_encodes_every_non_pass_status_as_one(
    status: RuleStatus, bit: int
) -> None:
    _, plan = _request_and_plan()
    report = _report(
        plan,
        {"PREFIX": status, "STYLE_LOW": status, "LATER": status},
    )

    assert required_gate_vector(plan, report, ArtifactId("target")) == (bit, bit, bit)


def test_required_vector_ignores_nonrequired_and_not_applicable_rules() -> None:
    _, plan = _request_and_plan()
    base_rule = plan.rules[0]
    ignored = (
        replace(
            base_rule,
            definition=replace(
                base_rule.definition, rule_id=RuleId("OPTIONAL"), required=False
            ),
        ),
        replace(
            base_rule,
            definition=replace(
                base_rule.definition,
                rule_id=RuleId("NOT_APPLICABLE"),
                applicability=StaticApplicability.NOT_APPLICABLE,
            ),
        ),
    )
    extended = replace(plan, rules=plan.rules + ignored)
    report = _report(
        extended,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.FAIL,
            "LATER": RuleStatus.PASS,
            "OPTIONAL": RuleStatus.FAIL,
        },
    )

    assert required_gate_vector(extended, report, ArtifactId("target")) == (0, 1, 0)


@pytest.mark.parametrize(
    ("parent_statuses", "child_statuses", "expected"),
    (
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.FAIL,
            },
            True,
        ),
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.UNVERIFIABLE,
            },
            True,
        ),
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.WARNING,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.FAIL,
            },
            True,
        ),
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.WARNING,
            },
            True,
        ),
        (
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.FAIL,
                "LATER": RuleStatus.FAIL,
            },
            {
                "PREFIX": RuleStatus.PASS,
                "STYLE_LOW": RuleStatus.PASS,
                "LATER": RuleStatus.PASS,
            },
            True,
        ),
    ),
)
def test_guardrail_accepts_trigger_pass_and_strictly_lower_required_vector(
    parent_statuses: dict[str, RuleStatus],
    child_statuses: dict[str, RuleStatus],
    expected: bool,
) -> None:
    request, plan = _request_and_plan()
    parent = _report(plan, parent_statuses, score=1.0)
    child = _report(plan, child_statuses, score=99.0)
    decision = plan_repair_action(
        request, DecisionId("decision"), RuleId("STYLE_LOW"), INCREASE_STYLE_SCALE
    )

    assert (
        is_repair_improvement(
            plan, parent, child, ArtifactId("target"), ArtifactId("target"), decision
        )
        is expected
    )


def test_guardrail_rejects_child_target_and_report_plan_mismatch() -> None:
    request, plan = _request_and_plan()
    statuses = {
        "PREFIX": RuleStatus.PASS,
        "STYLE_LOW": RuleStatus.FAIL,
        "LATER": RuleStatus.FAIL,
    }
    parent = _report(plan, statuses)
    child = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.PASS,
            "LATER": RuleStatus.FAIL,
        },
    )
    decision = plan_repair_action(
        request, DecisionId("decision"), RuleId("STYLE_LOW"), INCREASE_STYLE_SCALE
    )

    with pytest.raises(DomainError):
        is_repair_improvement(
            plan, parent, child, ArtifactId("target"), ArtifactId("missing"), decision
        )
    with pytest.raises(DomainError):
        is_repair_improvement(
            plan,
            parent,
            replace(child, rules=child.rules[::-1]),
            ArtifactId("target"),
            ArtifactId("target"),
            decision,
        )


def test_guardrail_normalizes_hostile_decision_trigger_to_exact_str() -> None:
    request, plan = _request_and_plan()
    parent = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.FAIL,
            "LATER": RuleStatus.FAIL,
        },
    )
    child = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.PASS,
            "LATER": RuleStatus.FAIL,
        },
    )
    decision = plan_repair_action(
        request, DecisionId("decision"), RuleId("STYLE_LOW"), INCREASE_STYLE_SCALE
    )
    object.__setattr__(
        decision.trigger_rule_id, "value", SelfSafeCrossExplodingText("STYLE_LOW")
    )

    assert (
        is_repair_improvement(
            plan, parent, child, ArtifactId("target"), ArtifactId("target"), decision
        )
        is True
    )


def test_guardrail_normalizes_hostile_report_rule_and_target_ids() -> None:
    request, plan = _request_and_plan()
    parent = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.FAIL,
            "LATER": RuleStatus.FAIL,
        },
    )
    child = _report(
        plan,
        {
            "PREFIX": RuleStatus.PASS,
            "STYLE_LOW": RuleStatus.PASS,
            "LATER": RuleStatus.FAIL,
        },
    )
    decision = plan_repair_action(
        request, DecisionId("decision"), RuleId("STYLE_LOW"), INCREASE_STYLE_SCALE
    )
    results = tuple(
        next(
            item
            for item in report.results
            if str.__str__(item.rule_id.value) == "STYLE_LOW"
        )
        for report in (parent, child)
    )
    for report, result in zip((parent, child), results, strict=True):
        object.__setattr__(
            result.rule_id, "value", SelfSafeCrossExplodingText("STYLE_LOW")
        )
        object.__setattr__(
            report.artifacts[0].artifact_id,
            "value",
            SelfSafeCrossExplodingText("target"),
        )
        object.__setattr__(
            result.affected_artifact_ids[0],
            "value",
            SelfSafeCrossExplodingText("target"),
        )

    assert (
        is_repair_improvement(
            plan, parent, child, ArtifactId("target"), ArtifactId("target"), decision
        )
        is True
    )
