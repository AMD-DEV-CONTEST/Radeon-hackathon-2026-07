"""Unit tests for the threshold-sensitivity sweep + phase-split + A/B
benchmark tooling (the pure-math parts, so they run without GPU)."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts.sweep_thresholds import recommend, _parse_csv
from benchmarks.llm_phase_benchmark import compute_phase_metrics
from scripts.ab_split_mode import SplitModeResult


# ----- threshold sweep ------------------------------------------------------

def test_recommend_picks_highest_f1_above_precision_floor():
    points = [
        {"precision": 1.0, "recall": 0.10, "f1": 0.18, "auto_block": 0.9, "auto_allow": 0.05},
        {"precision": 0.97, "recall": 0.40, "f1": 0.56, "auto_block": 0.7, "auto_allow": 0.10},
        {"precision": 0.92, "recall": 0.60, "f1": 0.72, "auto_block": 0.6, "auto_allow": 0.01},
    ]
    best = recommend(points, min_precision=0.95)
    assert best is not None
    assert best["f1"] == 0.56  # 0.72 is excluded by precision floor


def test_recommend_none_when_no_point_meets_floor():
    points = [{"precision": 0.90, "f1": 0.5, "recall": 0.3}]
    assert recommend(points, min_precision=0.95) is None


def test_parse_csv_handles_spaces():
    assert _parse_csv("0.60, 0.70,0.80") == [0.6, 0.7, 0.8]
    assert _parse_csv("1.0") == [1.0]


# ----- phase-split math -----------------------------------------------------

def test_phase_metrics_ttft_is_prefill():
    # 50 tokens streamed: first arrives at 400ms, then one every 10ms
    events = [(str(i), 400.0 + i * 10.0) for i in range(50)]
    m = compute_phase_metrics(events, prompt_token_count=128, scenario="cache_miss", prompt="p")
    assert m.prefill_ms == 400.0
    assert m.decode_ms == 490.0  # 890 (last) - 400 (first)
    assert m.total_ms == 890.0
    assert m.output_tokens == 50


def test_phase_metrics_empty_stream_is_safe():
    m = compute_phase_metrics([], prompt_token_count=100, scenario="cache_hit", prompt="p")
    assert m.prefill_ms == 0.0 and m.output_tokens == 0 and m.decode_tok_s == 0.0


def test_phase_metrics_tokens_per_second():
    # 100 tokens, first at 500ms, one token per ms after that
    events = [(str(i), 500.0 + i * 1.0) for i in range(100)]
    m = compute_phase_metrics(events, prompt_token_count=200, scenario="cache_miss", prompt="p")
    assert abs(m.prefill_tok_s - 400.0) < 0.01     # 200 tokens / 0.5s
    assert abs(m.decode_tok_s - 1000.0) < 0.01     # 99 tokens / 0.099s


def test_phase_metrics_single_token_no_divide_by_zero():
    m = compute_phase_metrics([("x", 300.0)], prompt_token_count=10, scenario="cache_miss", prompt="p")
    assert m.decode_ms == 0.0
    assert m.decode_tok_s == 0.0


# ----- split-mode A/B helpers ----------------------------------------------

def test_split_mode_verdict_picks_faster_mode():
    row = SplitModeResult(split_mode="row", prompt="p", avg_total_ms=100.0)
    layer = SplitModeResult(split_mode="layer", prompt="p", avg_total_ms=150.0)
    faster, slower = (row, layer) if row.avg_total_ms <= layer.avg_total_ms else (layer, row)
    pct = (slower.avg_total_ms / faster.avg_total_ms - 1.0) * 100.0
    assert faster.split_mode == "row"
    assert pct == 50.0
