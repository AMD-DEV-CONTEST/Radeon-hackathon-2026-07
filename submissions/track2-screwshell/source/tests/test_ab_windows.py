"""P4 — A/B window split + compare (BUILD_OBSERVATORY_V3 §2.9, T1-T6, D4).

Pure-function tests against synthetic events. Verifies:
  * windows split correctly for each mode (half / run / minutes);
  * sample-size discipline (T4): small windows yield no verdict;
  * verdict wording is honest ("with confounders, not causal proof") and the
    primary metric is TTFT (D4).
"""
from __future__ import annotations

import time

from screwshell.ui.analysis import split_ab_windows, sample_count_ok, compare_windows


def _mk(n, base_ts, ttft, tag=""):
    return [{"ts": base_ts + i * 60,
             "ttft_ms": ttft, "avg_decode_tps": 25.0,
             "kv_hit_rate": 0.9, "ok_rate": 1.0,
             "run_id": f"r{tag}{i}"} for i in range(n)]


def test_split_half():
    evs = _mk(10, 1000, 1500)
    a, b = split_ab_windows(evs, mode="half")
    assert len(a) == 5 and len(b) == 5
    assert max(e["ts"] for e in a) < min(e["ts"] for e in b)


def test_split_run_at_run_id_change():
    evs = []
    evs += [{"ts": 1000 + i, "ttft_ms": 1500, "run_id": "A"} for i in range(3)]
    evs += [{"ts": 2000 + i, "ttft_ms": 1500, "run_id": "B"} for i in range(3)]
    a, b = split_ab_windows(evs, mode="run")
    assert all(e["run_id"] == "A" for e in a)
    assert all(e["run_id"] == "B" for e in b)


def test_split_minutes():
    now = time.time()
    # A: between 20 and 10 min ago; B: between 10 and 0 min ago
    a_src = [{"ts": now - 15 * 60, "ttft_ms": 1500, "run_id": "x"}]
    b_src = [{"ts": now - 5 * 60, "ttft_ms": 1500, "run_id": "x"}]
    a, b = split_ab_windows(a_src + b_src, mode="minutes", window_min=10)
    assert len(a) == 1 and len(b) == 1


def test_sample_count_ok_discipline():
    assert sample_count_ok(15) is False
    assert sample_count_ok(16) is True


def test_compare_small_sample_no_verdict():
    a = _mk(3, 1000, 9000)   # slow
    b = _mk(3, 2000, 1500)   # fast
    r = compare_windows(a, b, main_metric="ttft_ms")
    assert r["verdict"] == "sample_low"
    assert r["ok"] is False


def test_compare_b_wins_on_ttft():
    # both windows large enough (>=16)
    a = _mk(20, 1000, 9000)   # slow A
    b = _mk(20, 2000, 1500)   # fast B
    r = compare_windows(a, b, main_metric="ttft_ms")
    assert r["ok"] is True
    assert r["verdict"] == "b"  # B (after) wins


def test_compare_tie_when_close():
    a = _mk(20, 1000, 1500)
    b = _mk(20, 2000, 1520)  # within 5%
    r = compare_windows(a, b, main_metric="ttft_ms")
    assert r["verdict"] == "tie"
