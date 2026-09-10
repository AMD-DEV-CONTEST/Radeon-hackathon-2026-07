"""ProductInstance composite: geometry + features."""

from __future__ import annotations

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.verification.rule_models import RuleResult

RULE_PRODUCT_INSTANCE = RuleId("L3_PRODUCT_INSTANCE")


def combine_geometry_and_features(
    artifact_id: ArtifactId,
    geometry: RuleResult,
    features: RuleResult,
    /,
) -> RuleResult:
    """Composite: any UNVERIFIABLE → UNVERIFIABLE; any FAIL → FAIL; else PASS."""
    if (
        geometry.status is RuleStatus.UNVERIFIABLE
        or features.status is RuleStatus.UNVERIFIABLE
    ):
        return RuleResult(
            RULE_PRODUCT_INSTANCE, RuleStatus.UNVERIFIABLE, (artifact_id,), None
        )
    if geometry.status is RuleStatus.FAIL or features.status is RuleStatus.FAIL:
        score = _combine_scores(geometry.score, features.score)
        return RuleResult(RULE_PRODUCT_INSTANCE, RuleStatus.FAIL, (artifact_id,), score)
    score = _combine_scores(geometry.score, features.score)
    return RuleResult(RULE_PRODUCT_INSTANCE, RuleStatus.PASS, (artifact_id,), score)


def _combine_scores(a: float | None, b: float | None) -> float | None:
    if a is not None and b is not None:
        return min(a, b)
    if a is not None:
        return a
    if b is not None:
        return b
    return None
