"""Todo 1 — slice_events + generalized split_ab_windows (dimension-slicer).

Covers:
  * every categorical DIMENSIONS dim groups {key: [events]};
  * a fixture WITHOUT an `entry` key + with/without run_id -> "ui"/"api";
  * None/empty adapter/route -> "unknown" bucket (no KeyError, no drop);
  * categorical split of `entry` at last boundary-change yields A=ui, B=api;
  * all-equal categorical dim -> "single_value" outcome (NOT half);
  * split_ab_windows(evs, mode="time", window_min=10) behaves as minutes;
  * compare_windows(a, b) (no split_kind) still returns the ok-branch;
  * compare_windows(a, b, split_kind="single_value") -> verdict single_value.
"""
from __future__ import annotations

import time

from screwshell.ui.analysis import (
    DIMENSIONS,
    CATEGORICAL_DIMENSIONS,
    slice_events,
    split_ab_windows,
    compare_windows,
    run_ab_split,
)


def _mk(n, base_ts, **fields):
    e = dict(ts=0, ttft_ms=1500, avg_decode_tps=25.0,
             kv_hit_rate=0.9, ok_rate=1.0)
    e.update(fields)
    return [dict(e, ts=base_ts + i * 60) for i in range(n)]


def test_dimensions_canonical_members():
    # Refactored drill-down + time design: only session/request/time remain.
    # run_id crosses sessions (not a clean tree) and the other flat attributes
    # (entry/adapter/ok/stream/switched/route) are dropped from the canonical set.
    assert DIMENSIONS == frozenset({"session", "request", "time"})
    assert "ts" not in DIMENSIONS
    assert CATEGORICAL_DIMENSIONS == (DIMENSIONS - {"time"})


def test_slice_every_categorical_dim():
    evs = [
        {"ts": 1000, "run_id": "r1", "request_id": "q1",
         "operational_session_id": "s1", "adapter": "btl3", "ok": True,
         "stream": True, "switched": False, "route": "rag"},
        {"ts": 1001, "run_id": "r2", "request_id": "q2",
         "operational_session_id": "s2", "adapter": "cybersec", "ok": False,
         "stream": False, "switched": True, "route": "sec"},
    ]
    for dim in CATEGORICAL_DIMENSIONS:
        buckets = slice_events(evs, dim)
        assert sum(len(v) for v in buckets.values()) == 2


def test_slice_entry_derived_from_run_id():
    # No `entry` key present at all -> must be derived from run_id.
    evs = [
        {"ts": 1000, "run_id": "r1"},   # has run_id -> ui
        {"ts": 1001, "run_id": "r2"},   # has run_id -> ui
        {"ts": 1002},                   # no run_id  -> api
    ]
    buckets = slice_events(evs, "entry")
    assert set(buckets) == {"ui", "api"}
    assert len(buckets["ui"]) == 2
    assert len(buckets["api"]) == 1


def test_slice_unknown_bucket_no_drop():
    n = 5
    evs = [{"ts": 1000 + i} for i in range(n)]
    # adapter / route are absent -> all land in "unknown"
    for dim in ("adapter", "route"):
        buckets = slice_events(evs, dim)
        assert list(buckets) == ["unknown"]
        assert len(buckets["unknown"]) == n

    # explicit None / empty
    evs2 = [{"ts": 1000, dim: None}, {"ts": 1001, dim: ""}]
    buckets = slice_events(evs2, dim)
    assert buckets["unknown"] and len(buckets["unknown"]) == 2


def test_split_entry_boundary_change():
    evs = []
    evs += [{"ts": 1000 + i, "run_id": f"r{i}", "ttft_ms": 1500} for i in range(3)]
    evs += [{"ts": 2000 + i} for i in range(3)]  # no run_id -> api
    a, b, split_kind = split_ab_windows(evs, mode="entry")
    assert split_kind == "ok"
    assert all(e.get("run_id") for e in a)        # A = all ui
    assert all(not e.get("run_id") for e in b)    # B = all api


def test_split_categorical_single_value():
    evs = _mk(6, 1000, adapter="btl3")  # only one distinct adapter
    res = split_ab_windows(evs, mode="adapter")
    # 3-tuple with single_value, NOT a half split
    assert len(res) == 3
    a, b, split_kind = res
    assert split_kind == "single_value"
    assert a == [] and b == []


def test_split_categorical_three_tuple_shape():
    evs = _mk(6, 1000, route="x") + _mk(6, 2000, route="y")
    res = split_ab_windows(evs, mode="route")
    assert len(res) == 3
    a, b, split_kind = res
    assert split_kind == "ok"
    assert a and b


def test_split_run_id_is_categorical_three_tuple():
    evs = [
        {"ts": 1000 + i, "run_id": "A"} for i in range(3)
    ] + [
        {"ts": 2000 + i, "run_id": "B"} for i in range(3)
    ]
    res = split_ab_windows(evs, mode="run_id")
    assert len(res) == 3  # 3-tuple, NOT the legacy 2-tuple run mode
    a, b, split_kind = res
    assert split_kind == "ok"
    assert all(e["run_id"] == "A" for e in a)
    assert all(e["run_id"] == "B" for e in b)


def test_split_empty_categorical_returns_single_value_three_tuple():
    res = split_ab_windows([], mode="entry")
    assert len(res) == 3
    a, b, split_kind = res
    assert (a, b) == ([], [])
    assert split_kind == "single_value"


def test_run_ab_split_empty_does_not_raise():
    r = run_ab_split([], "entry", 10)
    assert isinstance(r, dict)
    assert r["verdict"] == "single_value"
    assert r["ok"] is False


def test_legacy_modes_keep_two_tuple():
    evs = _mk(10, 1000)
    for mode in ("half", "run", "minutes"):
        res = split_ab_windows(evs, mode=mode, window_min=10)
        assert len(res) == 2


def test_split_time_is_minutes_windowing():
    now = time.time()
    a_src = [{"ts": now - 15 * 60, "ttft_ms": 1500}]
    b_src = [{"ts": now - 5 * 60, "ttft_ms": 1500}]
    a, b = split_ab_windows(a_src + b_src, mode="time", window_min=10)
    assert len(a) == 1 and len(b) == 1


def test_compare_default_split_kind_ok():
    a = _mk(20, 1000, ttft_ms=9000)
    b = _mk(20, 2000, ttft_ms=1500)
    r = compare_windows(a, b, main_metric="ttft_ms")
    assert r["split_kind"] == "ok"
    assert r["ok"] is True
    assert r["verdict"] == "b"


def test_compare_single_value_branch():
    a = _mk(20, 1000, ttft_ms=9000)
    b = _mk(20, 2000, ttft_ms=1500)
    r = compare_windows(a, b, split_kind="single_value")
    assert r["verdict"] == "single_value"
    assert r["ok"] is False
