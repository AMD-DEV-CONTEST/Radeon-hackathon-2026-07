"""Verifier protocol and the sole guarded verifier execution entry point."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from specstyle.domain.artifacts import ArtifactRef
from specstyle.domain.enums import StaticApplicability
from specstyle.errors import DomainError, InfrastructureError
from specstyle.verification.rule_models import (
    RuleDefinition,
    RuleResult,
    VerificationReport,
    _validate_artifacts,
    _validate_rules,
)


@runtime_checkable
class Verifier(Protocol):
    def verify(
        self,
        artifacts: tuple[ArtifactRef, ...],
        rules: tuple[RuleDefinition, ...],
        /,
    ) -> tuple[RuleResult, ...]: ...


def run_verifier(
    verifier: Verifier,
    artifacts: tuple[ArtifactRef, ...],
    rules: tuple[RuleDefinition, ...],
) -> tuple[RuleResult, ...]:
    _validate_artifacts(artifacts)
    _validate_rules(rules)
    if not rules or any(
        rule.applicability is not StaticApplicability.APPLICABLE for rule in rules
    ):
        raise DomainError("run_verifier requires nonempty applicable rules")
    try:
        results = verifier.verify(artifacts, rules)
        if type(results) is not tuple or not results:
            raise DomainError("verifier must return nonempty result tuple")
        VerificationReport(artifacts, rules, results)
    except InfrastructureError:
        raise
    except Exception as exc:
        raise InfrastructureError("verifier contract violation") from exc
    return results
