"""Verifier protocol and isolated invocation contract tests."""

from __future__ import annotations

import pytest

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import RuleLevel, RuleScope, RuleStatus, StaticApplicability
from specstyle.domain.identifiers import ArtifactId, RuleId, Sha256
from specstyle.errors import DomainError, InfrastructureError
from specstyle.verification.protocols import Verifier, run_verifier
from specstyle.verification.rule_models import GatePolicy, RuleDefinition, RuleResult


def artifact(value: str) -> ArtifactRef:
    return ArtifactRef(ArtifactId(value), Sha256("a" * 64))


def rule(value: str, scope: RuleScope = RuleScope.ITEM) -> RuleDefinition:
    return RuleDefinition(
        RuleId(value),
        RuleLevel.L1,
        scope,
        True,
        StaticApplicability.APPLICABLE,
        GatePolicy("reject", "reject", "manual_review"),
    )


class PassingVerifier:
    def verify(
        self, artifacts: tuple[ArtifactRef, ...], rules: tuple[RuleDefinition, ...], /
    ) -> tuple[RuleResult, ...]:
        return tuple(
            RuleResult(rule.rule_id, RuleStatus.PASS, (item.artifact_id,), None)
            for rule in rules
            for item in artifacts
        )


def test_verifier_is_runtime_checkable_protocol() -> None:
    assert isinstance(PassingVerifier(), Verifier)


def test_run_verifier_returns_complete_valid_results() -> None:
    results = run_verifier(
        PassingVerifier(), (artifact("one"), artifact("two")), (rule("rule"),)
    )
    assert [result.affected_artifact_ids for result in results] == [
        (ArtifactId("one"),),
        (ArtifactId("two"),),
    ]


@pytest.mark.parametrize(
    "returned",
    (
        (),
        "wrong",
        (RuleResult(RuleId("wrong"), RuleStatus.PASS, (ArtifactId("one"),), None),),
    ),
)
def test_run_verifier_wraps_empty_wrong_or_out_of_contract_output(
    returned: object,
) -> None:
    class BadVerifier:
        def verify(self, artifacts, rules, /):
            return returned

    with pytest.raises(
        InfrastructureError, match="verifier contract violation"
    ) as caught:
        run_verifier(BadVerifier(), (artifact("one"),), (rule("rule"),))
    assert caught.value.__cause__ is not None


def test_run_verifier_wraps_non_infrastructure_execution_error() -> None:
    class BrokenVerifier:
        def verify(self, artifacts, rules, /):
            raise RuntimeError("broken")

    with pytest.raises(
        InfrastructureError, match="verifier contract violation"
    ) as caught:
        run_verifier(BrokenVerifier(), (artifact("one"),), (rule("rule"),))
    assert isinstance(caught.value.__cause__, RuntimeError)


def test_run_verifier_preserves_infrastructure_error() -> None:
    failure = InfrastructureError("device unavailable")

    class FailingVerifier:
        def verify(self, artifacts, rules, /):
            raise failure

    with pytest.raises(InfrastructureError) as caught:
        run_verifier(FailingVerifier(), (artifact("one"),), (rule("rule"),))
    assert caught.value is failure


def test_run_verifier_rejects_empty_or_not_applicable_input_rules() -> None:
    with pytest.raises(DomainError):
        run_verifier(PassingVerifier(), (artifact("one"),), ())
    unavailable = RuleDefinition(
        RuleId("na"),
        RuleLevel.L1,
        RuleScope.ITEM,
        False,
        StaticApplicability.NOT_APPLICABLE,
        GatePolicy("reject", "reject", "continue"),
    )
    with pytest.raises(DomainError):
        run_verifier(PassingVerifier(), (artifact("one"),), (unavailable,))


def test_run_verifier_does_not_catch_base_exception() -> None:
    class InterruptedVerifier:
        def verify(self, artifacts, rules, /):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_verifier(InterruptedVerifier(), (artifact("one"),), (rule("rule"),))
