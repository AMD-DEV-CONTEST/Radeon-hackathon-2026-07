"""L2-005 calibration runner — injected encoder scores only, no data I/O."""

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
class L2CalibrationResult:
    manifest: SplitManifest
    decision: ThresholdDecision
    calibration_pairs: tuple[ScoredPair, ...]
    validation_pairs: tuple[ScoredPair, ...]
    test_held: bool


def run_l2_calibration(
    samples: tuple[SampleRef, ...],
    score_fn: ScoreFn,
    *,
    metric_id: str = "reference_style_fidelity_min",
    max_fpr: float = 0.2,
    min_tpr: float = 0.7,
    view_test: bool = False,
) -> L2CalibrationResult:
    """Select threshold on cal, freeze on val; test optional and held by default."""
    if not callable(score_fn):
        raise DomainError("invalid score function")
    manifest = build_split_manifest(samples)
    cal = _score_split(manifest.calibration, score_fn)
    val = _score_split(manifest.validation, score_fn)
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
    if view_test:
        # Explicit opt-in only after freeze; runner does not mutate decision.
        _score_split(manifest.test, score_fn)
    return L2CalibrationResult(manifest, decision, cal, val, not view_test)


def _score_split(
    samples: tuple[SampleRef, ...], score_fn: ScoreFn
) -> tuple[ScoredPair, ...]:
    out: list[ScoredPair] = []
    for sample in samples:
        if type(sample) is not SampleRef:
            raise DomainError("invalid sample")
        try:
            score = score_fn(sample)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("score function failed") from exc
        if type(score) is not float or score != score:
            raise DomainError("invalid score")
        out.append(ScoredPair(sample.sample_id, score, sample.label_positive))
    return tuple(out)
