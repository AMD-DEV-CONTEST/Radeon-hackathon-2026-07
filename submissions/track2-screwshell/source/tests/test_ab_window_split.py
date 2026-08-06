"""Todo 2 seam test (part of Todo 1 foundation) — run_ab_split seam.

Module-level `run_ab_split(events, dim, window_min)` is the single unit-testable
A/B decision point that the gradio closures delegate to. It must:
  * forward split_kind for categorical dims (so single_value is honest);
  * map `time` to minutes windowing;
  * return the _AB_RESULT dict with na/nb/verdict/ok/split_kind.
"""
from __future__ import annotations

import time

from screwshell.ui.analysis import run_ab_split, split_ab_windows, compare_windows


def _mk(n, base_ts, **fields):
    return [dict(ts=base_ts + i * 60, ttft_ms=1500,
                 avg_decode_tps=25.0, kv_hit_rate=0.9, ok_rate=1.0,
                 **fields) for i in range(n)]


def test_run_ab_split_categorical_ok():
    evs = _mk(20, 1000, route="x") + _mk(20, 2000, route="y")
    r = run_ab_split(evs, "route", 10)
    assert isinstance(r, dict)
    assert r["na"] >= 16 and r["nb"] >= 16
    assert r["ok"] is True
    assert r["split_kind"] == "ok"
    assert r["verdict"] in ("a", "b", "tie")


def test_run_ab_split_single_value():
    evs = _mk(20, 1000, adapter="btl3")
    r = run_ab_split(evs, "adapter", 10)
    assert r["split_kind"] == "single_value"
    assert r["verdict"] == "single_value"
    assert r["ok"] is False


def test_run_ab_split_run_id_categorical():
    evs = [
        {"ts": 1000 + i, "run_id": "A"} for i in range(3)
    ] + [
        {"ts": 2000 + i, "run_id": "B"} for i in range(3)
    ]
    r = run_ab_split(evs, "run_id", 10)
    assert isinstance(r, dict)
    assert r["split_kind"] == "ok"
    assert r["verdict"] in ("a", "b", "tie", "sample_low")


def test_run_ab_split_time_is_minutes():
    now = time.time()
    evs = [
        {"ts": now - 15 * 60, "ttft_ms": 9000},
        {"ts": now - 5 * 60, "ttft_ms": 1500},
    ]
    r = run_ab_split(evs, "time", 10)
    assert r["split_kind"] == "ok"
    assert r["na"] == 1 and r["nb"] == 1


def test_run_ab_split_entry_derived():
    evs = _mk(20, 1000, run_id="r") + _mk(20, 100000)  # ui then api, no overlap
    r = run_ab_split(evs, "entry", 10)
    assert r["split_kind"] == "ok"
    assert r["na"] == 20 and r["nb"] == 20
