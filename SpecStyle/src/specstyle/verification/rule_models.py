"""Strict immutable contracts for verification definitions, results, and reports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

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
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError


@dataclass(frozen=True, slots=True)
class GatePolicy:
    on_fail: Literal["reject"]
    on_unverifiable: Literal["reject", "manual_review"]
    on_warning: Literal["reject", "manual_review", "continue"]

    def __post_init__(self) -> None:
        if type(self.on_fail) is not str or self.on_fail != "reject":
            raise DomainError("on_fail must be 'reject'")
        if type(self.on_unverifiable) is not str or self.on_unverifiable not in {
            "reject",
            "manual_review",
        }:
            raise DomainError("invalid on_unverifiable policy")
        if type(self.on_warning) is not str or self.on_warning not in {
            "reject",
            "manual_review",
            "continue",
        }:
            raise DomainError("invalid on_warning policy")


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    rule_id: RuleId
    level: RuleLevel
    scope: RuleScope
    required: bool
    applicability: StaticApplicability
    gate_policy: GatePolicy

    def __post_init__(self) -> None:
        if type(self.rule_id) is not RuleId:
            raise DomainError("rule_id must be RuleId")
        if type(self.level) is not RuleLevel:
            raise DomainError("level must be RuleLevel")
        if type(self.scope) is not RuleScope:
            raise DomainError("scope must be RuleScope")
        if type(self.required) is not bool:
            raise DomainError("required must be bool")
        if type(self.applicability) is not StaticApplicability:
            raise DomainError("applicability must be StaticApplicability")
        if type(self.gate_policy) is not GatePolicy:
            raise DomainError("gate_policy must be GatePolicy")
        if self.required and self.gate_policy.on_warning == "continue":
            raise DomainError("required rule cannot continue on warning")


@dataclass(frozen=True, slots=True)
class RuleResult:
    rule_id: RuleId
    status: RuleStatus
    affected_artifact_ids: tuple[ArtifactId, ...]
    score: float | None

    def __post_init__(self) -> None:
        if type(self.rule_id) is not RuleId:
            raise DomainError("rule_id must be RuleId")
        if type(self.status) is not RuleStatus:
            raise DomainError("status must be RuleStatus")
        if type(self.affected_artifact_ids) is not tuple:
            raise DomainError("affected_artifact_ids must be tuple")
        if any(
            type(artifact_id) is not ArtifactId
            for artifact_id in self.affected_artifact_ids
        ):
            raise DomainError("affected_artifact_ids must contain ArtifactId")
        if self.score is not None and (
            type(self.score) is not float or not math.isfinite(self.score)
        ):
            raise DomainError("score must be finite float or None")


@dataclass(frozen=True, slots=True)
class VerificationReport:
    artifacts: tuple[ArtifactRef, ...]
    rules: tuple[RuleDefinition, ...]
    results: tuple[RuleResult, ...]

    def __post_init__(self) -> None:
        _validate_artifacts(self.artifacts)
        _validate_rules(self.rules)
        _validate_results(self.artifacts, self.rules, self.results)


@dataclass(frozen=True, slots=True)
class ArtifactDecision:
    artifact_id: ArtifactId
    artifact_status: ArtifactStatus
    decision_reason: DecisionReason
    repair_stop_reason: RepairStopReason | None
    accepted_with_override: bool

    def __post_init__(self) -> None:
        if type(self.artifact_id) is not ArtifactId:
            raise DomainError("artifact_id must be ArtifactId")
        if type(self.artifact_status) is not ArtifactStatus:
            raise DomainError("artifact_status must be ArtifactStatus")
        if type(self.decision_reason) is not DecisionReason:
            raise DomainError("decision_reason must be DecisionReason")
        if (
            self.repair_stop_reason is not None
            and type(self.repair_stop_reason) is not RepairStopReason
        ):
            raise DomainError("repair_stop_reason must be RepairStopReason or None")
        if type(self.accepted_with_override) is not bool:
            raise DomainError("accepted_with_override must be bool")
        legal_pairs = {
            (ArtifactStatus.APPROVED, DecisionReason.ALL_REQUIRED_PASS),
            (ArtifactStatus.MANUAL_REVIEW, DecisionReason.MANUAL_POLICY),
            (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_FAILED),
            (ArtifactStatus.REJECTED, DecisionReason.REQUIRED_GATE_UNVERIFIABLE),
            (ArtifactStatus.REJECTED, DecisionReason.REPAIR_EXHAUSTED),
        }
        if (self.artifact_status, self.decision_reason) not in legal_pairs:
            raise DomainError("artifact status and decision reason are incompatible")
        if self.accepted_with_override and (
            self.artifact_status is not ArtifactStatus.MANUAL_REVIEW
            or self.decision_reason is not DecisionReason.MANUAL_POLICY
        ):
            raise DomainError("override requires manual review policy decision")


def _validate_artifacts(artifacts: object) -> None:
    if type(artifacts) is not tuple or not artifacts:
        raise DomainError("artifacts must be a nonempty tuple")
    if any(type(artifact) is not ArtifactRef for artifact in artifacts):
        raise DomainError("artifacts must contain ArtifactRef")
    artifact_ids = tuple(artifact.artifact_id for artifact in artifacts)
    if len(set(artifact_ids)) != len(artifact_ids):
        raise DomainError("artifact ids must be unique")


def _validate_rules(rules: object) -> None:
    if type(rules) is not tuple:
        raise DomainError("rules must be tuple")
    if any(type(rule) is not RuleDefinition for rule in rules):
        raise DomainError("rules must contain RuleDefinition")
    rule_ids = tuple(rule.rule_id for rule in rules)
    if len(set(rule_ids)) != len(rule_ids):
        raise DomainError("rule ids must be unique")


def _validate_results(
    artifacts: tuple[ArtifactRef, ...],
    rules: tuple[RuleDefinition, ...],
    results: object,
) -> None:
    if type(results) is not tuple:
        raise DomainError("results must be tuple")
    if any(type(result) is not RuleResult for result in results):
        raise DomainError("results must contain RuleResult")
    artifact_ids = tuple(artifact.artifact_id for artifact in artifacts)
    artifact_id_set = set(artifact_ids)
    rules_by_id = {rule.rule_id: rule for rule in rules}
    by_rule: dict[RuleId, list[RuleResult]] = {rule.rule_id: [] for rule in rules}

    for result in results:
        rule = rules_by_id.get(result.rule_id)
        if rule is None:
            raise DomainError("result references unknown rule")
        if rule.applicability is StaticApplicability.NOT_APPLICABLE:
            raise DomainError("not applicable rule must not have result")
        if any(
            artifact_id not in artifact_id_set
            for artifact_id in result.affected_artifact_ids
        ):
            raise DomainError("result references unknown artifact")
        by_rule[result.rule_id].append(result)

    for rule in rules:
        rule_results = by_rule[rule.rule_id]
        if rule.applicability is StaticApplicability.NOT_APPLICABLE:
            if rule_results:
                raise DomainError("not applicable rule must not have result")
            continue
        if rule.scope is RuleScope.ITEM:
            expected = {(rule.rule_id, artifact_id) for artifact_id in artifact_ids}
            actual: set[tuple[RuleId, ArtifactId]] = set()
            for result in rule_results:
                if len(result.affected_artifact_ids) != 1:
                    raise DomainError("item result must affect exactly one artifact")
                actual.add((rule.rule_id, result.affected_artifact_ids[0]))
            if actual != expected or len(rule_results) != len(expected):
                raise DomainError(
                    "item rule results must cover each artifact exactly once"
                )
        elif (
            len(rule_results) != 1
            or rule_results[0].affected_artifact_ids != artifact_ids
        ):
            raise DomainError(
                "batch rule must have one result affecting the ordered batch"
            )
