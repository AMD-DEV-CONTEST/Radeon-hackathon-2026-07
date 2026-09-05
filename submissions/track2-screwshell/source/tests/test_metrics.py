"""Tests for the T2 measurement primitives: GenStats new fields + RunMetrics.

Covers the three honesty / contract rules from blueprint §6.2:
  * GenStats new fields all default (and the original 4 positional fields keep
    working untouched);
  * RunMetrics.summary() aggregates per-phase and per-adapter;
  * when a backend reports NO timings, coverage.timings < 1.0 and the prefill/
    decode split is left at zero -- never fabricated from wall time.
"""
from screwshell.core.metrics import RunMetrics
from screwshell.core.mol_types import GenStats


def test_genstats_new_fields_default():
    # original 4 positional args only; every appended field must default
    g = GenStats("adapter-x", 10, 20, 1.0)
    assert g.prefill_ms is None
    assert g.decode_ms is None
    assert g.prefill_tps is None
    assert g.decode_tps is None
    assert g.cached_tokens == 0
    assert g.ttft_ms is None
    assert g.finish_reason is None
    assert g.constrained is False
    assert g.ok is True
    assert g.error is None


def test_genstats_derived_properties():
    g = GenStats("a", 100, 20, 1.0)
    assert g.kv_hit_rate == 0.0           # no cache hits yet
    assert g.prefilled_tokens == 100
    assert g.has_timings is False

    with_t = GenStats("a", 100, 20, 1.0, cached_tokens=40,
                      prefill_ms=10.0, decode_ms=20.0)
    assert with_t.prefilled_tokens == 60  # 100 - 40
    assert with_t.has_timings is True
    # kv_hit_rate clamps to [0,1] and reflects real cache ratio
    assert abs(with_t.kv_hit_rate - 0.4) < 1e-9


def test_runmetrics_summary_by_phase_and_adapter():
    rm = RunMetrics()
    rm.record(GenStats("a", 100, 20, 1.0), phase="plan", step_idx=0)
    rm.record(GenStats("a", 50, 10, 0.5), phase="plan")
    rm.record(GenStats("b", 80, 15, 0.8), phase="final")

    s = rm.summary()
    assert s["calls"] == 3
    assert s["by_phase"]["plan"]["calls"] == 2
    assert s["by_phase"]["final"]["calls"] == 1
    assert "a" in s["by_adapter"]
    assert "b" in s["by_adapter"]
    assert s["by_adapter"]["a"]["calls"] == 2
    assert s["by_adapter"]["b"]["calls"] == 1
    # prompt/new token totals rolled up globally
    assert s["prompt_tokens"] == 230
    assert s["new_tokens"] == 45


def test_runmetrics_no_fabricated_timings():
    rm = RunMetrics()
    rm.record(GenStats("a", 10, 5, 0.5))   # no timings at all
    s = rm.summary()
    # coverage reflects that NOTHING carried a real prefill/decode split
    assert s["coverage"]["timings"] < 1.0
    assert s["coverage"]["timings"] == 0.0
    # and the split is genuinely zero -- never backfilled from wall time
    assert s["prefill_s"] == 0.0
    assert s["decode_s"] == 0.0
    # prefill_tps/decode_tps are None when unmeasured
    assert s["prefill_tps"] is None
    assert s["decode_tps"] is None


def test_runmetrics_timings_coverage_full():
    rm = RunMetrics()
    rm.record(GenStats("a", 10, 5, 0.5, prefill_ms=8.0, decode_ms=12.0))
    assert rm.summary()["coverage"]["timings"] == 1.0
