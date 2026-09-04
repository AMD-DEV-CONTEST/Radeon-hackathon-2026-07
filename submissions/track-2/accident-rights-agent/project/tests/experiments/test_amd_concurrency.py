from __future__ import annotations

from benchmarks.amd_concurrency import percentile, summarize_level


def test_percentile_interpolates_small_samples():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert round(percentile([1.0, 2.0, 3.0, 4.0], 0.95) or 0, 2) == 3.85
    assert percentile([], 0.95) is None


def test_concurrency_summary_uses_measured_tokens_and_quality():
    runs = [
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "ttft_seconds": 1.0,
            "tpot_seconds": 0.05,
            "total_latency_seconds": 2.0,
            "quality": {"verifier_pass": True, "quality_score": 100.0},
        },
        {
            "input_tokens": 100,
            "output_tokens": 30,
            "ttft_seconds": 1.5,
            "tpot_seconds": 0.06,
            "total_latency_seconds": 3.0,
            "quality": {"verifier_pass": False, "quality_score": 80.0},
        },
    ]
    result = summarize_level(
        concurrency=2,
        wall_seconds=4.0,
        runs=runs,
        gpu={"available": False, "metrics": {}},
    )
    assert result["input_tokens_mean"] == 100
    assert result["aggregate_output_tokens_per_second"] == 12.5
    assert result["verifier_pass_rate"] == 0.5
    assert result["quality_score_mean"] == 90.0
