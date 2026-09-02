from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from colorgraph.agent.creative_contracts import (
    ExceptionApprovalSource,
    ExceptionMetric,
    IntentionalException,
    ProtectedAttribute,
    StrategyScope,
    StrictFrozenModel,
    canonical_sha256,
)
from colorgraph.quality.models import CheckStatus, QualityReport

CONSTRAINT_POLICY_VERSION = "colorgraph.creative-constraint-policy/v1"


class ConstraintLayer(StrEnum):
    DELIVERY = "delivery"
    DEFAULT_PROTECTION = "default_protection"
    CREATIVE_SPACE = "creative_space"


class ConstraintMetric(StrEnum):
    COLOR_PIPELINE_SCHEMA = "color_pipeline_schema"
    FINITE_VALUES = "finite_values"
    INPUT_TRANSFORM_INTACT = "input_transform_intact"
    OUTPUT_TRANSFORM_INTACT = "output_transform_intact"
    LEGAL_OUTPUT_GAMUT = "legal_output_gamut"
    ASSET_INTEGRITY = "asset_integrity"
    FRAME_PTS_VALID = "frame_pts_valid"
    ENCODING_VALID = "encoding_valid"
    METADATA_VALID = "metadata_valid"
    HIGHLIGHT_CLIPPING_RATIO = "highlight_clipping_ratio"
    SHADOW_CLIPPING_RATIO = "shadow_clipping_ratio"
    SKIN_COLOR_DELTA = "skin_color_delta"
    SNOW_COLOR_DELTA = "snow_color_delta"
    OVERSATURATION_RATIO = "oversaturation_ratio"
    STRUCTURE_LOSS = "structure_loss"
    EMOTIONAL_ALIGNMENT = "emotional_alignment"
    COLOR_RELATIONSHIP = "color_relationship"
    CONTRAST_STRUCTURE = "contrast_structure"
    VISUAL_HIERARCHY = "visual_hierarchy"
    STYLE_COHERENCE = "style_coherence"


class ConstraintComparator(StrEnum):
    MAXIMUM = "maximum"
    MINIMUM = "minimum"
    EQUAL = "equal"


class FindingStatus(StrEnum):
    PASS = "pass"
    ALLOWED_INTENTIONAL_DEVIATION = "allowed_intentional_deviation"
    FAIL_UNEXPECTED_DAMAGE = "fail_unexpected_damage"
    FAIL_DELIVERY = "fail_delivery"


_DELIVERY_METRICS = frozenset(
    {
        ConstraintMetric.COLOR_PIPELINE_SCHEMA,
        ConstraintMetric.FINITE_VALUES,
        ConstraintMetric.INPUT_TRANSFORM_INTACT,
        ConstraintMetric.OUTPUT_TRANSFORM_INTACT,
        ConstraintMetric.LEGAL_OUTPUT_GAMUT,
        ConstraintMetric.ASSET_INTEGRITY,
        ConstraintMetric.FRAME_PTS_VALID,
        ConstraintMetric.ENCODING_VALID,
        ConstraintMetric.METADATA_VALID,
    }
)
_DEFAULT_PROTECTION_ATTRIBUTES = {
    ConstraintMetric.HIGHLIGHT_CLIPPING_RATIO: ProtectedAttribute.HIGHLIGHT_DETAIL,
    ConstraintMetric.SHADOW_CLIPPING_RATIO: ProtectedAttribute.SHADOW_DETAIL,
    ConstraintMetric.SKIN_COLOR_DELTA: ProtectedAttribute.SKIN_NEUTRALITY,
    ConstraintMetric.SNOW_COLOR_DELTA: ProtectedAttribute.SNOW_NEUTRALITY,
    ConstraintMetric.OVERSATURATION_RATIO: ProtectedAttribute.NATURAL_SATURATION,
    ConstraintMetric.STRUCTURE_LOSS: ProtectedAttribute.STRUCTURE,
}
_CREATIVE_METRICS = frozenset(
    {
        ConstraintMetric.EMOTIONAL_ALIGNMENT,
        ConstraintMetric.COLOR_RELATIONSHIP,
        ConstraintMetric.CONTRAST_STRUCTURE,
        ConstraintMetric.VISUAL_HIERARCHY,
        ConstraintMetric.STYLE_COHERENCE,
    }
)
_EXCEPTION_METRICS = {
    ConstraintMetric.HIGHLIGHT_CLIPPING_RATIO: ExceptionMetric.HIGHLIGHT_CLIPPING_RATIO,
    ConstraintMetric.SHADOW_CLIPPING_RATIO: ExceptionMetric.SHADOW_CLIPPING_RATIO,
    ConstraintMetric.OVERSATURATION_RATIO: ExceptionMetric.OVERSATURATION_RATIO,
    ConstraintMetric.STRUCTURE_LOSS: ExceptionMetric.STRUCTURE_LOSS,
}
_AUTO_EXCEPTION_CAPS = {
    ExceptionMetric.HIGHLIGHT_CLIPPING_RATIO: 0.055,
    ExceptionMetric.SHADOW_CLIPPING_RATIO: 0.10,
    ExceptionMetric.OVERSATURATION_RATIO: 0.10,
    ExceptionMetric.STRUCTURE_LOSS: 0.40,
}
_USER_EXCEPTION_CAPS = {
    ExceptionMetric.HIGHLIGHT_CLIPPING_RATIO: 0.10,
    ExceptionMetric.SHADOW_CLIPPING_RATIO: 0.18,
    ExceptionMetric.OVERSATURATION_RATIO: 0.18,
    ExceptionMetric.STRUCTURE_LOSS: 0.50,
}


def constraint_layer(metric: ConstraintMetric) -> ConstraintLayer:
    if metric in _DELIVERY_METRICS:
        return ConstraintLayer.DELIVERY
    if metric in _DEFAULT_PROTECTION_ATTRIBUTES:
        return ConstraintLayer.DEFAULT_PROTECTION
    if metric in _CREATIVE_METRICS:
        return ConstraintLayer.CREATIVE_SPACE
    raise AssertionError(f"unclassified constraint metric: {metric}")


class ConstraintObservation(StrictFrozenModel):
    observation_id: str = Field(min_length=1, max_length=160)
    metric: ConstraintMetric
    value: float
    threshold: float
    comparator: ConstraintComparator
    scope: StrategyScope
    evidence_ids: Annotated[list[str], Field(min_length=1)]
    affected_protected_attributes: list[ProtectedAttribute]
    detail: str = Field(min_length=1, max_length=4_096)

    @model_validator(mode="after")
    def validate_layer_shape(self) -> ConstraintObservation:
        layer = constraint_layer(self.metric)
        expected_attribute = _DEFAULT_PROTECTION_ATTRIBUTES.get(self.metric)
        if layer == ConstraintLayer.DELIVERY and self.affected_protected_attributes:
            raise ValueError("delivery observations do not accept creative protection labels")
        if (
            layer == ConstraintLayer.DEFAULT_PROTECTION
            and expected_attribute not in self.affected_protected_attributes
        ):
            raise ValueError(
                "default-protection observation must name its protected attribute"
            )
        if (
            layer == ConstraintLayer.CREATIVE_SPACE
            and self.comparator == ConstraintComparator.EQUAL
        ):
            raise ValueError("creative-space signals must remain independent scored dimensions")
        return self

    @property
    def passed(self) -> bool:
        if not math.isfinite(self.value) or not math.isfinite(self.threshold):
            return False
        if self.comparator == ConstraintComparator.MAXIMUM:
            return self.value <= self.threshold
        if self.comparator == ConstraintComparator.MINIMUM:
            return self.value >= self.threshold
        return math.isclose(self.value, self.threshold, rel_tol=0, abs_tol=1e-12)


class ConstraintEvaluationContext(StrictFrozenModel):
    project_id: str = Field(min_length=1, max_length=160)
    source_graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    render_started_at: AwareDatetime
    evaluated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    known_evidence_ids: set[str]


class ConstraintFinding(StrictFrozenModel):
    observation_id: str
    metric: ConstraintMetric
    layer: ConstraintLayer
    status: FindingStatus
    observed_value: float
    threshold: float
    exception_id: str | None = None
    detail: str


class ConstraintReport(StrictFrozenModel):
    schema_version: str = CONSTRAINT_POLICY_VERSION
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    hard_checks_passed: bool
    findings: list[ConstraintFinding]
    accepted_exception_ids: list[str]
    rejected_exception_ids: list[str]
    summary: str


def _scope_contains(exception_scope: StrategyScope, observed_scope: StrategyScope) -> bool:
    if exception_scope.project_id != observed_scope.project_id:
        return False
    if exception_scope.scene_id is not None and exception_scope.scene_id != observed_scope.scene_id:
        return False
    if exception_scope.shot_id is not None and exception_scope.shot_id != observed_scope.shot_id:
        return False
    if (
        exception_scope.mask_target is not None
        and exception_scope.mask_target != observed_scope.mask_target
    ):
        return False
    if exception_scope.time_range is not None:
        if observed_scope.time_range is None:
            return False
        if (
            observed_scope.time_range.start_seconds
            < exception_scope.time_range.start_seconds
            or observed_scope.time_range.end_seconds
            > exception_scope.time_range.end_seconds
        ):
            return False
    return True


def _exception_rejection_reason(
    exception: IntentionalException,
    context: ConstraintEvaluationContext,
) -> str | None:
    if exception.scope.project_id != context.project_id:
        return "exception targets another project"
    if exception.source_graph_digest != context.source_graph_digest:
        return "exception was declared for a different source graph"
    if exception.candidate_digest != context.candidate_digest:
        return "exception was declared for a different candidate"
    if exception.declared_at >= context.render_started_at:
        return "exception was declared after rendering began"
    if exception.expires_at is not None and context.evaluated_at >= exception.expires_at:
        return "exception has expired"
    if not set(exception.evidence_ids) <= context.known_evidence_ids:
        return "exception cites unknown evidence"
    cap_table = (
        _AUTO_EXCEPTION_CAPS
        if exception.approval_source == ExceptionApprovalSource.AUTOMATIC
        else _USER_EXCEPTION_CAPS
    )
    if exception.maximum_metric_value > cap_table[exception.metric]:
        return "exception exceeds the approval-source safety cap"
    return None


def evaluate_constraints(
    observations: list[ConstraintObservation],
    exceptions: list[IntentionalException],
    *,
    context: ConstraintEvaluationContext,
) -> ConstraintReport:
    if len({item.observation_id for item in observations}) != len(observations):
        raise ValueError("constraint observation IDs must be unique")
    exception_ids = [item.exception_id for item in exceptions]
    if len(set(exception_ids)) != len(exception_ids):
        raise ValueError("intentional exception IDs must be unique")

    rejection_reasons = {
        item.exception_id: reason
        for item in exceptions
        if (reason := _exception_rejection_reason(item, context)) is not None
    }
    valid_exceptions = [
        item for item in exceptions if item.exception_id not in rejection_reasons
    ]
    accepted: set[str] = set()
    findings: list[ConstraintFinding] = []

    for observation in observations:
        layer = constraint_layer(observation.metric)
        if observation.passed or layer == ConstraintLayer.CREATIVE_SPACE:
            findings.append(
                ConstraintFinding(
                    observation_id=observation.observation_id,
                    metric=observation.metric,
                    layer=layer,
                    status=FindingStatus.PASS,
                    observed_value=observation.value,
                    threshold=observation.threshold,
                    detail=(
                        observation.detail
                        if layer != ConstraintLayer.CREATIVE_SPACE
                        else "creative dimension recorded without acting as a safety override"
                    ),
                )
            )
            continue

        if layer == ConstraintLayer.DELIVERY:
            findings.append(
                ConstraintFinding(
                    observation_id=observation.observation_id,
                    metric=observation.metric,
                    layer=layer,
                    status=FindingStatus.FAIL_DELIVERY,
                    observed_value=observation.value,
                    threshold=observation.threshold,
                    detail="delivery constraints are non-waivable",
                )
            )
            continue

        exception_metric = _EXCEPTION_METRICS.get(observation.metric)
        expected_attribute = _DEFAULT_PROTECTION_ATTRIBUTES[observation.metric]
        candidates = sorted(
            (
                item
                for item in valid_exceptions
                if item.metric == exception_metric
                and _scope_contains(item.scope, observation.scope)
                and set(observation.affected_protected_attributes)
                <= set(item.protected_attributes)
            ),
            key=lambda item: item.exception_id,
        )
        matching = next(
            (
                item
                for item in candidates
                if observation.value <= item.maximum_metric_value
                and expected_attribute in item.protected_attributes
            ),
            None,
        )
        if matching is not None:
            accepted.add(matching.exception_id)
            findings.append(
                ConstraintFinding(
                    observation_id=observation.observation_id,
                    metric=observation.metric,
                    layer=layer,
                    status=FindingStatus.ALLOWED_INTENTIONAL_DEVIATION,
                    observed_value=observation.value,
                    threshold=observation.threshold,
                    exception_id=matching.exception_id,
                    detail="measured deviation is predeclared, in scope, and within budget",
                )
            )
        else:
            detail = "unintended damage has no valid in-scope exception"
            if candidates:
                detail = "intentional deviation exceeded its numeric budget"
            findings.append(
                ConstraintFinding(
                    observation_id=observation.observation_id,
                    metric=observation.metric,
                    layer=layer,
                    status=FindingStatus.FAIL_UNEXPECTED_DAMAGE,
                    observed_value=observation.value,
                    threshold=observation.threshold,
                    detail=detail,
                )
            )

    rejected = sorted(
        {
            *rejection_reasons,
            *(item.exception_id for item in valid_exceptions if item.exception_id not in accepted),
        }
    )
    hard_passed = all(
        item.status
        not in {FindingStatus.FAIL_DELIVERY, FindingStatus.FAIL_UNEXPECTED_DAMAGE}
        for item in findings
    )
    allowed_count = sum(
        item.status == FindingStatus.ALLOWED_INTENTIONAL_DEVIATION for item in findings
    )
    failure_count = len(findings) - sum(
        item.status
        in {FindingStatus.PASS, FindingStatus.ALLOWED_INTENTIONAL_DEVIATION}
        for item in findings
    )
    policy_digest = canonical_sha256(
        {
            "version": CONSTRAINT_POLICY_VERSION,
            "automatic_caps": {
                key.value: value for key, value in _AUTO_EXCEPTION_CAPS.items()
            },
            "user_caps": {key.value: value for key, value in _USER_EXCEPTION_CAPS.items()},
        }
    )
    return ConstraintReport(
        policy_digest=policy_digest,
        hard_checks_passed=hard_passed,
        findings=findings,
        accepted_exception_ids=sorted(accepted),
        rejected_exception_ids=rejected,
        summary=(
            f"{failure_count} blocking failures; "
            f"{allowed_count} allowed intentional deviations"
        ),
    )


def observations_from_quality_report(
    report: QualityReport,
    *,
    scope: StrategyScope,
    evidence_id: str,
) -> list[ConstraintObservation]:
    protection_mapping = {
        "highlight_clipping": (
            ConstraintMetric.HIGHLIGHT_CLIPPING_RATIO,
            ProtectedAttribute.HIGHLIGHT_DETAIL,
        ),
        "shadow_crush": (
            ConstraintMetric.SHADOW_CLIPPING_RATIO,
            ProtectedAttribute.SHADOW_DETAIL,
        ),
        "oversaturation": (
            ConstraintMetric.OVERSATURATION_RATIO,
            ProtectedAttribute.NATURAL_SATURATION,
        ),
        "structure_loss": (
            ConstraintMetric.STRUCTURE_LOSS,
            ProtectedAttribute.STRUCTURE,
        ),
    }
    delivery_mapping = {
        "finite_values": (
            ConstraintMetric.FINITE_VALUES,
            ConstraintComparator.MAXIMUM,
        ),
        "output_gamut": (
            ConstraintMetric.LEGAL_OUTPUT_GAMUT,
            ConstraintComparator.MAXIMUM,
        ),
        "asset_integrity": (
            ConstraintMetric.ASSET_INTEGRITY,
            ConstraintComparator.EQUAL,
        ),
        "color_pipeline_schema": (
            ConstraintMetric.COLOR_PIPELINE_SCHEMA,
            ConstraintComparator.EQUAL,
        ),
        "metadata": (
            ConstraintMetric.METADATA_VALID,
            ConstraintComparator.EQUAL,
        ),
        "encoding": (
            ConstraintMetric.ENCODING_VALID,
            ConstraintComparator.EQUAL,
        ),
        "frame_pts": (
            ConstraintMetric.FRAME_PTS_VALID,
            ConstraintComparator.EQUAL,
        ),
    }
    observations: list[ConstraintObservation] = []
    for check in report.checks:
        protection = protection_mapping.get(check.id)
        delivery = delivery_mapping.get(check.id)
        if protection is None and delivery is None:
            continue
        if protection is not None:
            metric, attribute = protection
            comparator = ConstraintComparator.MAXIMUM
            attributes = [attribute]
        else:
            assert delivery is not None
            metric, comparator = delivery
            attributes = []
        observations.append(
            ConstraintObservation(
                observation_id=f"quality:{check.id}",
                metric=metric,
                value=check.value,
                threshold=check.threshold,
                comparator=comparator,
                scope=scope,
                evidence_ids=[evidence_id],
                affected_protected_attributes=attributes,
                detail=(
                    check.detail
                    if check.status != CheckStatus.PASS
                    else f"{check.label} passed"
                ),
            )
        )
    return observations
