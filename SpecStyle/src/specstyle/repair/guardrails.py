"""Discrete gate-level guardrail for repair reports."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus as _RuleStatus
from specstyle.domain.identifiers import ArtifactId as _ArtifactId
from specstyle.errors import DomainError as _DomainError
from specstyle.repair.conflict_resolution import _blocking_rules
from specstyle.repair.conflict_resolution import _decision
from specstyle.repair.conflict_resolution import _ordered_required
from specstyle.repair.conflict_resolution import _result_for
from specstyle.repair.conflict_resolution import _safe
from specstyle.repair.conflict_resolution import _validated_plan_report
from specstyle.repair.models import RepairDecision as _RepairDecision
from specstyle.spec.compiled_models import CompiledVerificationPlan as _Plan
from specstyle.verification.rule_models import VerificationReport as _Report


def _vector(plan: _Plan, report: _Report, target: _ArtifactId) -> tuple[int, ...]:
    return _safe(
        "invalid verification report",
        lambda: tuple(
            0
            if _result_for(report, rule.definition.rule_id, target).status
            is _RuleStatus.PASS
            else 1
            for rule in _ordered_required(plan)
        ),
    )


def required_gate_vector(
    plan: _Plan, report: _Report, target_artifact_id: _ArtifactId
) -> tuple[int, ...]:
    """Build a target PASS/non-PASS bit vector in stable required-gate order."""
    rebuilt_plan, rebuilt_report, target = _validated_plan_report(
        plan, report, target_artifact_id
    )
    if not _ordered_required(rebuilt_plan):
        raise _DomainError("plan has no applicable required gate")
    return _vector(rebuilt_plan, rebuilt_report, target)


def is_repair_improvement(
    plan: _Plan,
    parent_report: _Report,
    child_report: _Report,
    parent_target_artifact_id: _ArtifactId,
    child_target_artifact_id: _ArtifactId,
    decision: _RepairDecision,
) -> bool:
    """Accept only trigger repair with strict lexicographic gate improvement."""
    rebuilt_plan, parent, parent_target = _validated_plan_report(
        plan, parent_report, parent_target_artifact_id
    )
    child_plan, child, child_target = _validated_plan_report(
        plan, child_report, child_target_artifact_id
    )
    if not _safe("invalid repair context", lambda: child_plan == rebuilt_plan):
        raise _DomainError("child plan does not match parent plan")
    rebuilt_decision = _decision(decision)
    blocking = _blocking_rules(rebuilt_plan, parent, parent_target)
    matches_trigger = _safe(
        "invalid repair decision",
        lambda: (
            bool(blocking)
            and rebuilt_decision.trigger_rule_id == blocking[0].definition.rule_id
        ),
    )
    if not matches_trigger:
        raise _DomainError("repair decision does not match parent blocking rule")
    required = _ordered_required(rebuilt_plan)
    if not required:
        raise _DomainError("plan has no applicable required gate")
    index = _safe(
        "invalid repair decision",
        lambda: next(
            i
            for i, rule in enumerate(required)
            if rule.definition.rule_id == rebuilt_decision.trigger_rule_id
        ),
    )
    trigger_passed = _safe(
        "invalid verification report",
        lambda: (
            _result_for(child, rebuilt_decision.trigger_rule_id, child_target).status
            is _RuleStatus.PASS
        ),
    )
    if not trigger_passed:
        return False
    prefix_passed = _safe(
        "invalid verification report",
        lambda: all(
            _result_for(child, rule.definition.rule_id, child_target).status
            is _RuleStatus.PASS
            for rule in required[:index]
        ),
    )
    if not prefix_passed:
        return False
    return _safe(
        "invalid verification report",
        lambda: (
            _vector(rebuilt_plan, child, child_target)
            < _vector(rebuilt_plan, parent, parent_target)
        ),
    )
