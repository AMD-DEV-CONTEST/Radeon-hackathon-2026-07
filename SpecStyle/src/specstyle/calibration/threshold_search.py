"""Threshold selection: choose on calibration, freeze on validation, hold test."""

from __future__ import annotations

from dataclasses import dataclass

from specstyle.domain.identifiers import Sha256
from specstyle.errors import DomainError
from specstyle.observability.hashing import hash_bytes


@dataclass(frozen=True, slots=True)
class ScoredPair:
    sample_id: str
    score: float
    label_positive: bool

    def __post_init__(self) -> None:
        if type(self.sample_id) is not str or not self.sample_id:
            raise DomainError("invalid scored pair")
        if type(self.score) is not float or self.score != self.score:
            raise DomainError("invalid score")
        if type(self.label_positive) is not bool:
            raise DomainError("invalid label")


@dataclass(frozen=True, slots=True)
class ThresholdDecision:
    metric_id: str
    operator: str
    threshold: float
    calibration_tpr: float
    calibration_fpr: float
    validation_tpr: float
    validation_fpr: float
    status: str  # DRAFT | VALIDATION_PASSED | REJECTED
    decision_hash: Sha256

    def __post_init__(self) -> None:
        if self.operator not in {"gte", "lte"}:
            raise DomainError("unsupported operator")
        if self.status not in ("DRAFT", "VALIDATION_PASSED", "REJECTED"):
            raise DomainError("invalid threshold status")


def binary_rates(
    pairs: tuple[ScoredPair, ...], threshold: float, operator: str = "gte"
) -> tuple[float, float]:
    """Return (TPR, FPR) at threshold."""
    if type(pairs) is not tuple or not pairs:
        raise DomainError("invalid pairs")
    if type(threshold) is not float or threshold != threshold:
        raise DomainError("invalid threshold")
    if operator not in {"gte", "lte"}:
        raise DomainError("unsupported operator")
    tp = fp = tn = fn = 0
    for p in pairs:
        if type(p) is not ScoredPair:
            raise DomainError("invalid pair")
        pred = p.score >= threshold if operator == "gte" else p.score <= threshold
        if p.label_positive and pred:
            tp += 1
        elif p.label_positive and not pred:
            fn += 1
        elif not p.label_positive and pred:
            fp += 1
        else:
            tn += 1
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return tpr, fpr


def select_threshold_on_calibration(
    pairs: tuple[ScoredPair, ...],
    *,
    metric_id: str,
    operator: str = "gte",
    max_fpr: float,
    min_tpr: float,
    candidates: tuple[float, ...] | None = None,
) -> float:
    """Pick highest threshold that still meets min_tpr with FPR <= max_fpr."""
    if type(pairs) is not tuple or not pairs:
        raise DomainError("invalid calibration pairs")
    if type(metric_id) is not str or not metric_id:
        raise DomainError("invalid metric")
    if type(max_fpr) is not float or not 0.0 <= max_fpr <= 1.0:
        raise DomainError("invalid max_fpr")
    if type(min_tpr) is not float or not 0.0 <= min_tpr <= 1.0:
        raise DomainError("invalid min_tpr")
    if operator not in {"gte", "lte"}:
        raise DomainError("unsupported operator")
    scores = sorted({p.score for p in pairs if type(p) is ScoredPair})
    if not scores:
        raise DomainError("invalid calibration pairs")
    grid = candidates if candidates is not None else tuple(scores)
    if type(grid) is not tuple or not grid:
        raise DomainError("invalid candidate thresholds")
    best: float | None = None
    # Higher is stricter for gte; lower is stricter for lte.
    for thr in sorted(grid, reverse=operator == "gte"):
        if type(thr) is not float or thr != thr:
            raise DomainError("invalid candidate threshold")
        tpr, fpr = binary_rates(pairs, thr, operator)
        if tpr >= min_tpr and fpr <= max_fpr:
            best = thr
            break
    if best is None:
        raise DomainError("no threshold meets calibration targets")
    return best


def freeze_threshold(
    *,
    metric_id: str,
    operator: str = "gte",
    threshold: float,
    calibration: tuple[ScoredPair, ...],
    validation: tuple[ScoredPair, ...],
    max_fpr: float,
    min_tpr: float,
) -> ThresholdDecision:
    """Validation freezes; test set must not be passed here."""
    if type(threshold) is not float or threshold != threshold:
        raise DomainError("invalid threshold")
    if operator not in {"gte", "lte"}:
        raise DomainError("unsupported operator")
    cal_tpr, cal_fpr = binary_rates(calibration, threshold, operator)
    val_tpr, val_fpr = binary_rates(validation, threshold, operator)
    if cal_tpr < min_tpr or cal_fpr > max_fpr:
        status = "REJECTED"
    elif val_tpr < min_tpr or val_fpr > max_fpr:
        status = "REJECTED"
    else:
        status = "VALIDATION_PASSED"
    material = (
        f"{metric_id}:{operator}:{threshold:.8f}:{cal_tpr:.6f}:{cal_fpr:.6f}:"
        f"{val_tpr:.6f}:{val_fpr:.6f}:{status}"
    )
    return ThresholdDecision(
        metric_id,
        operator,
        threshold,
        cal_tpr,
        cal_fpr,
        val_tpr,
        val_fpr,
        status,
        hash_bytes(material.encode()),
    )


def holdout_evaluate(
    decision: ThresholdDecision, test: tuple[ScoredPair, ...]
) -> tuple[float, float]:
    """Final test look — does not change decision status."""
    if type(decision) is not ThresholdDecision:
        raise DomainError("invalid decision")
    if decision.status != "VALIDATION_PASSED":
        raise DomainError("only VALIDATION_PASSED thresholds may view test")
    return binary_rates(test, decision.threshold, decision.operator)
