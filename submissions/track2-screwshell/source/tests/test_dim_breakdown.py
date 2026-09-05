"""方向 B — session->request drill-down (refactored dimension design).

Covers:
  * session_request_hierarchy groups events by operational_session_id (or the
    "(no-session)" bucket) and sorts each bucket by ts;
  * a session with many requests maps 1->N;
  * no-session grouping when the field is absent;
  * fmt_session_request_drilldown renders the parent (all sessions) /
    child (session's requests) / leaf (single request) views;
  * aggregates over <16 events show a sample-low note (no fabricated numbers);
  * session_request_hierarchy / slice_events carry NO i18n (no CJK / T());
  * fmt_session_request_drilldown([], ...) returns the empty-state line.
"""
from __future__ import annotations

import re

from screwshell.ui.analysis import (
    session_request_hierarchy,
    slice_events,
)
from screwshell.ui import app


def _ev(ts, **fields):
    e = dict(ts=ts, ok=True, ttft_ms=100.0,
             decode_tps=30.0, kv_hit_rate=0.9, run_id="r")
    e.update(fields)
    return e


def _events():
    # one session with 3 requests + a no-session request
    out = []
    for i in range(3):
        out.append(_ev(i, operational_session_id="s1",
                       request_id=f"q{i}", ttft_ms=100 + i * 10))
    out.append(_ev(10, request_id="q9", ttft_ms=200))  # no session
    return out


def test_hierarchy_groups_session_to_requests():
    evs = _events()
    h = session_request_hierarchy(evs)
    assert set(h) == {"s1", "(no-session)"}
    assert len(h["s1"]) == 3
    assert len(h["(no-session)"]) == 1
    # sorted by ts
    assert [e["ts"] for e in h["s1"]] == [0, 1, 2]


def test_hierarchy_no_session_bucket():
    evs = [_ev(0), _ev(1)]  # neither has operational_session_id
    h = session_request_hierarchy(evs)
    assert set(h) == {"(no-session)"}
    assert len(h["(no-session)"]) == 2


def test_hierarchy_empty():
    assert session_request_hierarchy([]) == {}


def test_drilldown_parent_lists_sessions():
    evs = _events()
    s = app.fmt_session_request_drilldown(evs, None, None, "zh")
    assert "(no-session)" in s
    assert "s1" in s
    # shows request counts
    assert "n 次请求=3" in s


def test_drilldown_child_lists_requests():
    evs = _events()
    s = app.fmt_session_request_drilldown(evs, "s1", None, "zh")
    for rid in ("q0", "q1", "q2"):
        assert rid in s
    assert "request_id" not in s  # leaf-only detail key absent at child level


def test_drilldown_leaf_single_request():
    evs = _events()
    s = app.fmt_session_request_drilldown(evs, "s1", "q1", "zh")
    assert "request_id: q1" in s
    assert "run_id:" in s


def test_drilldown_sample_low_note():
    # single event -> <16 -> sample note present in parent listing
    evs = [_ev(0, operational_session_id="solo")]
    s = app.fmt_session_request_drilldown(evs, None, None, "zh")
    assert "样本不足" in s


def test_drilldown_no_fabricated_numbers():
    evs = [_ev(0, operational_session_id="x", request_id="only", ttft_ms=123.0)]
    s = app.fmt_session_request_drilldown(evs, "x", "only", "zh")
    # the real ttft shows; no fake percentage or verdict
    assert "123ms" in s


def test_drilldown_empty_state():
    s = app.fmt_session_request_drilldown([], None, None, "zh")
    assert s == app.T("zh", "drill_empty")
    s_en = app.fmt_session_request_drilldown([], None, None, "en")
    assert s_en == app.T("en", "drill_empty")


def test_hierarchy_no_i18n():
    evs = _events()
    out = session_request_hierarchy(evs)
    cjk = re.compile(r"[\u4e00-\u9fff]")
    for key in out.keys():
        assert not cjk.search(str(key)), f"i18n leaked into key: {key!r}"
    src = __import__("inspect").getsource(session_request_hierarchy)
    assert "T(" not in src, "session_request_hierarchy must not call T()"
    # slice_events is still i18n-free for the breakdown path
    src2 = __import__("inspect").getsource(slice_events)
    assert not cjk.search(src2)


def test_drilldown_en_render():
    evs = _events()
    s = app.fmt_session_request_drilldown(evs, "s1", "q1", "en")
    assert "request_id: q1" in s
