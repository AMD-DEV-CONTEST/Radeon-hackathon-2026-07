"""L3-004 ProductInstance calibration — geometry/feature component rates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from specstyle.calibration.splits import SampleRef, SplitManifest, build_split_manifest
from specstyle.calibration.threshold_search import (
    ScoredPair,
    ThresholdDecision,
    freeze_threshold,
    select_threshold_on_calibration,
)
from specstyle.errors import DomainError

ScoreFn = Callable[[SampleRef], float]


@dataclass(frozen=True, slots=True)
class L3ComponentResult:
    component: str
    decision: ThresholdDecision


@dataclass(frozen=True, slots=True)
class L3CalibrationResult:
    manifest: SplitManifest
    geometry: L3ComponentResult
    features: L3ComponentResult
    composite: L3ComponentResult


def run_l3_calibration(
    samples: tuple[SampleRef, ...],
    geometry_score: ScoreFn,
    feature_score: ScoreFn,
    composite_score: ScoreFn,
    *,
    max_fpr: float = 0.15,
    min_tpr: float = 0.75,
) -> L3CalibrationResult:
    if not all(callable(f) for f in (geometry_score, feature_score, composite_score)):
        raise DomainError("invalid l3 score functions")
    manifest = build_split_manifest(samples)
    return L3CalibrationResult(
        manifest,
        _component("geometry", manifest, geometry_score, max_fpr, min_tpr),
        _component("features", manifest, feature_score, max_fpr, min_tpr),
        _component("composite", manifest, composite_score, max_fpr, min_tpr),
    )


def _component(
    name: str,
    manifest: SplitManifest,
    score_fn: ScoreFn,
    max_fpr: float,
    min_tpr: float,
) -> L3ComponentResult:
    cal = _pairs(manifest.calibration, score_fn)
    val = _pairs(manifest.validation, score_fn)
    metric_id = f"l3_{name}_min"
    thr = select_threshold_on_calibration(
        cal, metric_id=metric_id, max_fpr=max_fpr, min_tpr=min_tpr
    )
    decision = freeze_threshold(
        metric_id=metric_id,
        threshold=thr,
        calibration=cal,
        validation=val,
        max_fpr=max_fpr,
        min_tpr=min_tpr,
    )
    return L3ComponentResult(name, decision)


def _pairs(samples: tuple[SampleRef, ...], score_fn: ScoreFn) -> tuple[ScoredPair, ...]:
    out: list[ScoredPair] = []
    for sample in samples:
        if type(sample) is not SampleRef:
            raise DomainError("invalid sample")
        score = score_fn(sample)
        if type(score) is not float or score != score:
            raise DomainError("invalid score")
        out.append(ScoredPair(sample.sample_id, score, sample.label_positive))
    return tuple(out)
