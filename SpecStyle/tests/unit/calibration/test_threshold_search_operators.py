from __future__ import annotations

from specstyle.calibration.threshold_search import (
    ScoredPair,
    binary_rates,
    freeze_threshold,
    select_threshold_on_calibration,
)


def _pairs() -> tuple[ScoredPair, ...]:
    return (
        ScoredPair("positive-low", 0.1, True),
        ScoredPair("positive-high", 0.2, True),
        ScoredPair("negative-low", 0.8, False),
        ScoredPair("negative-high", 0.9, False),
    )


def test_lte_binary_rates_treat_lower_scores_as_positive() -> None:
    assert binary_rates(_pairs(), 0.2, "lte") == (1.0, 0.0)


def test_lte_selection_prefers_the_strictest_passing_threshold() -> None:
    threshold = select_threshold_on_calibration(
        _pairs(),
        metric_id="batch_style_consistency",
        operator="lte",
        max_fpr=0.0,
        min_tpr=1.0,
        candidates=(0.1, 0.2, 0.8),
    )

    assert threshold == 0.2


def test_lte_freeze_binds_operator_into_decision() -> None:
    decision = freeze_threshold(
        metric_id="batch_style_consistency",
        operator="lte",
        threshold=0.2,
        calibration=_pairs(),
        validation=_pairs(),
        max_fpr=0.0,
        min_tpr=1.0,
    )

    assert decision.operator == "lte"
    assert decision.status == "VALIDATION_PASSED"
