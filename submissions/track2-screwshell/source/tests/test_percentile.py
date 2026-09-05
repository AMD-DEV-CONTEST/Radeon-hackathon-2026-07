"""P3 — percentiles (BUILD_OBSERVATORY_V3 §2.4) + causal hint (§2.6).

Pure-function tests: no server, no Gradio. Verifies p50/p95 match the known
TTFT distribution shape and that the "never fabricate" rule holds when the
sample is too small.
"""
from __future__ import annotations

from screwshell.ui import app as ui_app
from screwshell.ui.analysis import percentile, compute_percentiles


def test_percentile_linear_interp():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10, 20, 30], 0) == 10
    assert percentile([10, 20, 30], 100) == 30
    assert percentile([5], 50) == 5


def test_compute_percentiles_empty():
    p = compute_percentiles([])
    assert p["n"] == 0 and p["p50"] is None and p["p95"] is None


def test_compute_percentiles_known_shape():
    # median ~1.66s, p90 ~88.8s (TTFT_BREAKDOWN_REPORT) sanity shape:
    # build a sample whose median sits well under its p95 (long tail).
    vals = [1660, 1700, 1620, 1800, 1500,
            88800, 172000, 5000, 2200, 1900]
    events = [{"ttft_ms": v} for v in vals]
    p = compute_percentiles(events)
    assert p["n"] == 10
    # p50 should be in the ~1.5-2.2s band, p95 near the long tail
    assert 1500 <= p["p50"] <= 2200
    assert p["p95"] >= 80000


def test_causal_hint_healthy_is_empty():
    s = {"avg_ttft_ms": 1000}
    assert ui_app.causal_hint(s, [], [], "zh") == ""


def test_causal_hint_session_too_long_priority():
    s = {"avg_ttft_ms": 9000}
    recent = [{"prompt_tokens": 25000, "switched": True},
              {"prompt_tokens": 1000, "switched": True}]
    out = ui_app.causal_hint(s, [], recent, "zh")
    assert "会话过长" in out and "建议" in out


def test_causal_hint_long_context_via_slot():
    s = {"avg_ttft_ms": 9000}
    slots = [{"is_processing": True, "n_prompt_tokens": 35000,
              "n_prompt_tokens_processed": 100}]
    out = ui_app.causal_hint(s, slots, [], "zh")
    assert "资料过长" in out


def test_causal_hint_frequent_switch():
    s = {"avg_ttft_ms": 9000}
    recent = [{"switched": True} for _ in range(4)]
    out = ui_app.causal_hint(s, [], recent, "zh")
    assert "频繁切换" in out
