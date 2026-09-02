from colorgraph.quality.analyzer import _status, _temporal_flicker
from colorgraph.quality.models import CheckStatus


def test_quality_status_thresholds() -> None:
    assert _status(0.01, 0.02, 0.05) == CheckStatus.PASS
    assert _status(0.03, 0.02, 0.05) == CheckStatus.WARN
    assert _status(0.06, 0.02, 0.05) == CheckStatus.FAIL


def test_temporal_flicker_ignores_samples_around_hard_cut() -> None:
    metrics = [
        {"mean_luma": 0.2},
        {"mean_luma": 0.2},
        {"mean_luma": 0.8},
        {"mean_luma": 0.5},
        {"mean_luma": 0.5},
    ]
    assert _temporal_flicker(metrics, 0.2, [0.41]) == 0
