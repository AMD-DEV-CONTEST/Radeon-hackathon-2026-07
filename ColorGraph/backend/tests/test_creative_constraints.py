from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from colorgraph.agent.creative_constraints import (
    ConstraintComparator,
    ConstraintEvaluationContext,
    ConstraintMetric,
    ConstraintObservation,
    FindingStatus,
    evaluate_constraints,
    observations_from_quality_report,
)
from colorgraph.agent.creative_contracts import (
    ExceptionApprovalSource,
    ExceptionMetric,
    IntentionalException,
    IntentionalExceptionKind,
    ProtectedAttribute,
    StrategyScope,
    TimeSpan,
)
from colorgraph.quality.models import CheckStatus, QualityCheck, QualityReport

NOW = datetime(2026, 7, 29, 10, tzinfo=UTC)
PROJECT_ID = "project:constraints"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _context(**changes) -> ConstraintEvaluationContext:
    values = {
        "project_id": PROJECT_ID,
        "source_graph_digest": _sha("source-graph"),
        "candidate_digest": _sha("candidate"),
        "render_started_at": NOW,
        "evaluated_at": NOW + timedelta(minutes=1),
        "known_evidence_ids": {"evidence:sun", "evidence:shadow", "evidence:qc"},
    }
    values.update(changes)
    return ConstraintEvaluationContext(**values)


def _scope(*, mask: str | None = None, shot: str = "shot:1") -> StrategyScope:
    return StrategyScope(
        project_id=PROJECT_ID,
        scene_id="scene:1",
        shot_id=shot,
        time_range=TimeSpan(start_seconds=1, end_seconds=2),
        mask_target=mask,
    )


def _bloom_exception(**changes) -> IntentionalException:
    values = {
        "exception_id": "exception:bloom",
        "kind": IntentionalExceptionKind.CONTROLLED_HIGHLIGHT_BLOOM,
        "reason": "Keep the small sun reflection luminous without affecting snow.",
        "evidence_ids": ["evidence:sun"],
        "scope": _scope(mask="sun-reflection"),
        "metric": ExceptionMetric.HIGHLIGHT_CLIPPING_RATIO,
        "maximum_metric_value": 0.055,
        "protected_attributes": [ProtectedAttribute.HIGHLIGHT_DETAIL],
        "approval_source": ExceptionApprovalSource.AUTOMATIC,
        "source_graph_digest": _sha("source-graph"),
        "candidate_digest": _sha("candidate"),
        "declared_at": NOW - timedelta(minutes=1),
        "invalidation_conditions": [
            "Invalidate if clipping spreads outside the sun-reflection mask."
        ],
    }
    values.update(changes)
    return IntentionalException(**values)


def _highlight_observation(
    *,
    value: float = 0.05,
    mask: str | None = "sun-reflection",
    attributes: list[ProtectedAttribute] | None = None,
) -> ConstraintObservation:
    return ConstraintObservation(
        observation_id=f"highlight:{mask or 'global'}",
        metric=ConstraintMetric.HIGHLIGHT_CLIPPING_RATIO,
        value=value,
        threshold=0.04,
        comparator=ConstraintComparator.MAXIMUM,
        scope=_scope(mask=mask),
        evidence_ids=["evidence:qc"],
        affected_protected_attributes=attributes
        or [ProtectedAttribute.HIGHLIGHT_DETAIL],
        detail="Measured highlight clipping in the rendered candidate.",
    )


def test_same_clipping_metric_distinguishes_local_bloom_global_damage_and_illegal_output() -> None:
    local = evaluate_constraints(
        [_highlight_observation()],
        [_bloom_exception()],
        context=_context(),
    )
    global_damage = evaluate_constraints(
        [_highlight_observation(mask=None)],
        [_bloom_exception()],
        context=_context(),
    )
    illegal_output = evaluate_constraints(
        [
            ConstraintObservation(
                observation_id="delivery:finite",
                metric=ConstraintMetric.FINITE_VALUES,
                value=0,
                threshold=1,
                comparator=ConstraintComparator.EQUAL,
                scope=_scope(),
                evidence_ids=["evidence:qc"],
                affected_protected_attributes=[],
                detail="Renderer output contains NaN values.",
            )
        ],
        [_bloom_exception()],
        context=_context(),
    )

    assert local.hard_checks_passed is True
    assert local.findings[0].status == FindingStatus.ALLOWED_INTENTIONAL_DEVIATION
    assert global_damage.hard_checks_passed is False
    assert global_damage.findings[0].status == FindingStatus.FAIL_UNEXPECTED_DAMAGE
    assert illegal_output.hard_checks_passed is False
    assert illegal_output.findings[0].status == FindingStatus.FAIL_DELIVERY
    assert illegal_output.findings[0].exception_id is None


def test_forged_reason_with_unknown_evidence_is_rejected() -> None:
    exception = _bloom_exception(
        reason="Trust me, this is artistic.",
        evidence_ids=["evidence:invented"],
    )

    report = evaluate_constraints(
        [_highlight_observation()],
        [exception],
        context=_context(),
    )

    assert report.hard_checks_passed is False
    assert report.rejected_exception_ids == ["exception:bloom"]
    assert report.findings[0].status == FindingStatus.FAIL_UNEXPECTED_DAMAGE


def test_post_render_exception_is_rejected() -> None:
    exception = _bloom_exception(declared_at=NOW + timedelta(seconds=1))

    report = evaluate_constraints(
        [_highlight_observation()],
        [exception],
        context=_context(),
    )

    assert report.hard_checks_passed is False
    assert report.rejected_exception_ids == ["exception:bloom"]


def test_scope_escape_and_protected_object_damage_are_rejected() -> None:
    wrong_mask = _highlight_observation(mask="snow-field")
    extra_damage = _highlight_observation(
        attributes=[
            ProtectedAttribute.HIGHLIGHT_DETAIL,
            ProtectedAttribute.SNOW_NEUTRALITY,
        ]
    )

    report = evaluate_constraints(
        [wrong_mask, extra_damage],
        [_bloom_exception()],
        context=_context(),
    )

    assert report.hard_checks_passed is False
    assert all(
        item.status == FindingStatus.FAIL_UNEXPECTED_DAMAGE for item in report.findings
    )


def test_numeric_budget_and_automatic_safety_cap_are_both_enforced() -> None:
    over_observation_budget = evaluate_constraints(
        [_highlight_observation(value=0.06)],
        [_bloom_exception()],
        context=_context(),
    )
    over_automatic_cap = evaluate_constraints(
        [_highlight_observation(value=0.06)],
        [_bloom_exception(maximum_metric_value=0.08)],
        context=_context(),
    )

    assert over_observation_budget.hard_checks_passed is False
    assert "budget" in over_observation_budget.findings[0].detail
    assert over_automatic_cap.hard_checks_passed is False
    assert over_automatic_cap.rejected_exception_ids == ["exception:bloom"]


def test_user_approval_requires_a_reference_and_never_waives_delivery() -> None:
    with pytest.raises(ValidationError, match="approval reference"):
        _bloom_exception(
            approval_source=ExceptionApprovalSource.USER,
            maximum_metric_value=0.08,
        )

    approved = _bloom_exception(
        approval_source=ExceptionApprovalSource.USER,
        approval_reference="approval:user-42",
        maximum_metric_value=0.08,
    )
    delivery = ConstraintObservation(
        observation_id="delivery:pts",
        metric=ConstraintMetric.FRAME_PTS_VALID,
        value=0,
        threshold=1,
        comparator=ConstraintComparator.EQUAL,
        scope=_scope(),
        evidence_ids=["evidence:qc"],
        affected_protected_attributes=[],
        detail="Output PTS are not monotonic.",
    )

    report = evaluate_constraints([delivery], [approved], context=_context())

    assert report.hard_checks_passed is False
    assert report.findings[0].status == FindingStatus.FAIL_DELIVERY


def test_creative_dimensions_are_recorded_but_cannot_compensate_for_a_failure() -> None:
    observations = [
        ConstraintObservation(
            observation_id="creative:emotion",
            metric=ConstraintMetric.EMOTIONAL_ALIGNMENT,
            value=1,
            threshold=0.5,
            comparator=ConstraintComparator.MINIMUM,
            scope=_scope(),
            evidence_ids=["evidence:qc"],
            affected_protected_attributes=[],
            detail="The candidate strongly expresses its own thesis.",
        ),
        _highlight_observation(mask=None),
    ]

    report = evaluate_constraints(observations, [], context=_context())

    assert report.hard_checks_passed is False
    assert report.findings[0].status == FindingStatus.PASS
    assert report.findings[1].status == FindingStatus.FAIL_UNEXPECTED_DAMAGE


def test_quality_report_adapter_keeps_global_failures_outside_local_exception_scope() -> None:
    quality = QualityReport(
        source_path="source.mp4",
        output_path="output.mp4",
        sampled_frames=10,
        score=82,
        hard_checks_passed=False,
        checks=[
            QualityCheck(
                id="highlight_clipping",
                label="Highlight clipping",
                status=CheckStatus.FAIL,
                value=0.05,
                threshold=0.04,
                unit="ratio",
                detail="Global P95 clipping ratio.",
            )
        ],
        summary="failed",
    )
    observations = observations_from_quality_report(
        quality,
        scope=_scope(mask=None),
        evidence_id="evidence:qc",
    )

    report = evaluate_constraints(
        observations,
        [_bloom_exception()],
        context=_context(),
    )

    assert observations[0].metric == ConstraintMetric.HIGHLIGHT_CLIPPING_RATIO
    assert report.findings[0].status == FindingStatus.FAIL_UNEXPECTED_DAMAGE
