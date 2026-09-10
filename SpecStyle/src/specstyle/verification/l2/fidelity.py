"""Single-image L2 style fidelity against multi-reference set."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.l2.encoder import StyleFeature
from specstyle.verification.l2.metrics import robust_reference_similarity
from specstyle.verification.l2.threshold_profile import (
    MetricThreshold,
    ThresholdProfile,
)
from specstyle.verification.rule_models import RuleResult

RULE_STYLE_FIDELITY = RuleId("L2_STYLE_FIDELITY")


def _apply_threshold(score: float, threshold: MetricThreshold) -> RuleStatus:
    if threshold.operator == "gte":
        return RuleStatus.PASS if score >= threshold.value else RuleStatus.FAIL
    return RuleStatus.PASS if score <= threshold.value else RuleStatus.FAIL


def evaluate_style_fidelity(
    artifact_id: ArtifactId,
    output: StyleFeature | None,
    references: tuple[StyleFeature, ...],
    profile: ThresholdProfile,
    /,
) -> RuleResult:
    if type(artifact_id) is not ArtifactId or type(profile) is not ThresholdProfile:
        raise DomainError("invalid fidelity inputs")
    if output is None or type(references) is not tuple or not references:
        return RuleResult(
            RULE_STYLE_FIDELITY, RuleStatus.UNVERIFIABLE, (artifact_id,), None
        )
    try:
        score = robust_reference_similarity(output, references)
    except DomainError:
        return RuleResult(
            RULE_STYLE_FIDELITY, RuleStatus.UNVERIFIABLE, (artifact_id,), None
        )
    if profile.status == "REVOKED":
        return RuleResult(RULE_STYLE_FIDELITY, RuleStatus.FAIL, (artifact_id,), score)
    if profile.status == "DRAFT":
        return RuleResult(
            RULE_STYLE_FIDELITY, RuleStatus.UNVERIFIABLE, (artifact_id,), score
        )
    metric = next(
        (
            t
            for t in profile.thresholds
            if t.metric_id == "reference_style_fidelity_min"
        ),
        None,
    )
    if metric is None:
        return RuleResult(
            RULE_STYLE_FIDELITY, RuleStatus.UNVERIFIABLE, (artifact_id,), score
        )
    status = _apply_threshold(score, metric)
    return RuleResult(RULE_STYLE_FIDELITY, status, (artifact_id,), score)
