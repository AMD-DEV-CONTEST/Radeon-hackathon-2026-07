"""Batch L2 style consistency and outlier attribution."""

from __future__ import annotations

import math

from specstyle.domain.enums import RuleStatus
from specstyle.domain.identifiers import ArtifactId, RuleId
from specstyle.errors import DomainError
from specstyle.verification.l2.encoder import StyleFeature
from specstyle.verification.l2.threshold_profile import ThresholdProfile
from specstyle.verification.rule_models import RuleResult

RULE_BATCH_CONSISTENCY = RuleId("L2_BATCH_STYLE_CONSISTENCY")


def _centroid(features: tuple[StyleFeature, ...]) -> tuple[float, ...]:
    pin0 = features[0].pin
    dim = len(features[0].vector)
    acc = [0.0] * dim
    for feat in features:
        if feat.pin != pin0:
            raise DomainError("feature pin mismatch")
        if len(feat.vector) != dim:
            raise DomainError("feature dimension mismatch")
        for i, v in enumerate(feat.vector):
            acc[i] += v
    n = float(len(features))
    return tuple(x / n for x in acc)


def _distance(vec: tuple[float, ...], center: tuple[float, ...]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(vec, center, strict=True)))


def evaluate_batch_consistency(
    items: tuple[tuple[ArtifactId, StyleFeature], ...],
    profile: ThresholdProfile,
    /,
) -> RuleResult:
    """Return batch gate result.

    Contract: ``affected_artifact_ids`` is always the full ordered cohort so the
    result is valid in ``VerificationReport`` and routing blocks the whole batch.
    Outlier IDs are recoverable via recompute; dispersion is the score.
    """
    if type(items) is not tuple or not items or type(profile) is not ThresholdProfile:
        raise DomainError("invalid batch consistency inputs")
    ids = tuple(i[0] for i in items)
    features = tuple(i[1] for i in items)
    if any(type(i) is not ArtifactId for i in ids):
        raise DomainError("invalid artifact ids")
    if any(type(f) is not StyleFeature for f in features):
        raise DomainError("invalid features")
    if profile.status == "REVOKED":
        return RuleResult(RULE_BATCH_CONSISTENCY, RuleStatus.FAIL, ids, None)
    if profile.status != "VALIDATED":
        # DRAFT etc. must not gate as PASS for required profiles.
        return RuleResult(RULE_BATCH_CONSISTENCY, RuleStatus.UNVERIFIABLE, ids, None)
    try:
        center = _centroid(features)
    except DomainError:
        return RuleResult(RULE_BATCH_CONSISTENCY, RuleStatus.UNVERIFIABLE, ids, None)
    distances = [_distance(f.vector, center) for f in features]
    if len(distances) == 1:
        dispersion = 0.0
    else:
        mean_d = sum(distances) / len(distances)
        dispersion = math.sqrt(
            sum((d - mean_d) ** 2 for d in distances) / len(distances)
        )
    metric = next(
        (t for t in profile.thresholds if t.metric_id == "batch_style_dispersion_max"),
        None,
    )
    if metric is None:
        return RuleResult(
            RULE_BATCH_CONSISTENCY, RuleStatus.UNVERIFIABLE, ids, dispersion
        )
    if not math.isfinite(metric.value):
        raise DomainError("invalid metric value")
    if dispersion > metric.value:
        # Full cohort affected for report/routing invariant.
        return RuleResult(RULE_BATCH_CONSISTENCY, RuleStatus.FAIL, ids, dispersion)
    return RuleResult(RULE_BATCH_CONSISTENCY, RuleStatus.PASS, ids, dispersion)


def batch_outlier_ids(
    items: tuple[tuple[ArtifactId, StyleFeature], ...],
    profile: ThresholdProfile,
    /,
) -> tuple[ArtifactId, ...]:
    """Explainability helper: per-item outliers (not used as gate affected set)."""
    if type(items) is not tuple or not items:
        raise DomainError("invalid batch consistency inputs")
    ids = tuple(i[0] for i in items)
    features = tuple(i[1] for i in items)
    center = _centroid(features)
    distances = [_distance(f.vector, center) for f in features]
    ordered = sorted(distances)
    median = ordered[len(ordered) // 2]
    metric = next(
        (t for t in profile.thresholds if t.metric_id == "batch_style_dispersion_max"),
        None,
    )
    cutoff = median + 1e-6 if metric is None else max(metric.value, median + 1e-6)
    return tuple(aid for aid, dist in zip(ids, distances, strict=True) if dist > cutoff)
