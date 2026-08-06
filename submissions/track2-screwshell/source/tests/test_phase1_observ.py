"""Phase 1 acceptance tests — observability layer (RequestEvent + store).

OFFLINE (Layer2_Implementation_Map.md §5 Phase 1): no GPU, no live
llama-server. We exercise the store / event / fill logic directly, the relay
observ endpoints via TestClient + FakeCoordinator, and the Coordinator's event
emission with httpx patched.

Locks down:
  * RequestEvent is a clean immutable record (to_dict/from_dict roundtrip).
  * ObservStore is thread-safe, opt-in only (OBSERV_DIR), lands JSONL + SQLite,
    and summarizes (by_adapter / kv_hit_rate / ok_rate / throughput).
  * KV hit rate of 0% is a REAL measurement, never left implied-missing.
  * The relay exposes /v1/observ/summary + /v1/observ/events from the store.
  * The Coordinator emits exactly one RequestEvent per request, carrying the
    real llama.cpp timings + usage (no fabrication).
"""
from __future__ import annotations

import asyncio
import json
import types
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from screwshell.core.inference_coordinator import (
    InferenceCoordinator, _fill_from_body)
from screwshell.core.router import SkillRouter
from screwshell.observ import RequestEvent, get_store, record_event
from screwshell.observ import store as store_mod
from screwshell.observ.store import ObservStore


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _reset_store(monkeypatch, tmp_path):
    """Force get_store() to rebuild an ENABLED store under tmp_path."""
    store_mod._STORE = None
    store_mod._STORE_READY = False
    monkeypatch.setenv("OBSERV_DIR", str(tmp_path))


class _FakeCoordinator:
    """Stand-in for InferenceCoordinator so the relay can be tested offline."""

    def __init__(self, adapters):
        self.engine = types.SimpleNamespace(adapters=adapters)
        self.router = SkillRouter()
        self._current_expert = None

    def load_base(self):
        return None

    async def request(self, *a, **k):
        return JSONResponse({"choices": [{"message": {"content": "ok"}}],
                             "usage": {}})


def _install_fake(coord):
    import screwshell.gateway.relay as relay
    relay.coord = coord
    return relay


# --------------------------------------------------------------------------
# RequestEvent
# --------------------------------------------------------------------------
def test_request_event_roundtrip():
    ev = RequestEvent(route="cybersec", adapter="cybersec", switched=True,
                      prompt_tokens=23, cached_tokens=19, completion_tokens=64,
                      kv_hit_rate=0.8261, ok=True)
    d = ev.to_dict()
    assert d["route"] == "cybersec" and d["switched"] is True
    back = RequestEvent.from_dict(d)
    assert back.to_dict() == d


def test_request_event_autofills_ts_and_id():
    ev = RequestEvent()
    assert ev.ts > 0
    assert ev.request_id  # auto-generated when empty


# --------------------------------------------------------------------------
# ObservStore
# --------------------------------------------------------------------------
def test_store_record_recent_summary_and_files(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    store = get_store()
    assert store.enabled is True
    for i, (adapter, cached) in enumerate([("cybersec", 19), ("cybersec", 19),
                                            ("btl3", 0)]):
        record_event(RequestEvent(route=adapter, adapter=adapter,
                                  prompt_tokens=23, cached_tokens=cached,
                                  completion_tokens=64, ok=True))
    recent = store.recent(10)
    assert len(recent) == 3
    s = store.summarize()
    assert s["count"] == 3
    assert s["by_adapter"] == {"cybersec": 2, "btl3": 1}
    assert s["ok_rate"] == 1.0
    # cybersec events both had cached 19 / prompt 23 -> 0.8261
    assert abs(s["kv_hit_rate"] - (38 / 69)) < 1e-3
    # JSONL + SQLite files exist and have rows
    assert (tmp_path / "requests.jsonl").exists()
    assert (tmp_path / "requests.db").exists()
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "requests.db"))
    n = con.execute("SELECT count(*) FROM request_events").fetchone()[0]
    assert n == 3


def test_store_is_noop_when_observ_dir_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("OBSERV_DIR", raising=False)
    store_mod._STORE = None
    store_mod._STORE_READY = False
    store = get_store()
    assert store.enabled is False
    record_event(RequestEvent(route="x"))  # must not raise
    assert store.recent(5) == []
    assert get_store().summarize()["count"] == 0


# --------------------------------------------------------------------------
# _fill_from_body — honest mapping (0% KV hit is real)
# --------------------------------------------------------------------------
def test_fill_from_body_maps_timings_and_records_zero_kv():
    ev = RequestEvent()
    body = {
        "usage": {"prompt_tokens": 10, "completion_tokens": 20,
                  "prompt_tokens_details": {"cached_tokens": 0}},
        "timings": {"prompt_ms": 5.0, "predicted_ms": 40.0,
                    "predicted_per_second": 25.0, "cache_n": 0,
                    "prompt_n": 10},
    }
    _fill_from_body(ev, body, {"chat_template_kwargs": {"enable_thinking": True}})
    assert ev.prompt_tokens == 10 and ev.completion_tokens == 20
    assert ev.cached_tokens == 0
    assert ev.kv_hit_rate == 0.0, "0% KV hit is a real measurement, not None"
    assert ev.prefill_ms == 5.0 and ev.decode_ms == 40.0
    assert ev.decode_tps == 25.0
    assert ev.thinking is True


def test_fill_from_body_no_timings_leaves_none():
    ev = RequestEvent()
    # No usage at all -> no prompt token count -> KV hit rate is genuinely
    # unknown (None), never fabricated as 0.
    _fill_from_body(ev, {}, {})
    assert ev.prefill_ms is None and ev.decode_ms is None
    assert ev.kv_hit_rate is None


# --------------------------------------------------------------------------
# Relay observ endpoints serve the store
# --------------------------------------------------------------------------
def test_relay_observ_endpoints(tmp_path):
    from screwshell.observ import ObservStore
    store = ObservStore(str(tmp_path))
    # All read paths (relay.summarize / recent_events, record_event) resolve
    # get_store() as a global inside the *store* module, so we patch the real
    # function there -- not the re-exported screwshell.observ.get_store name.
    with patch.object(store_mod, "get_store", lambda: store):
        relay = _install_fake(_FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
        store.record(RequestEvent(route="cybersec", adapter="cybersec",
                                  prompt_tokens=23, cached_tokens=19,
                                  completion_tokens=64, ok=True))
        store.record(RequestEvent(route="btl3", adapter="btl3", ok=False,
                                  error="boom"))
        with TestClient(relay.app) as client:
            s = client.get("/v1/observ/summary").json()
            e = client.get("/v1/observ/events?n=5").json()
    assert s["count"] == 2
    assert s["ok_rate"] == 0.5
    assert e["events"][0]["adapter"] == "btl3"
    assert e["events"][0]["error"] == "boom"


def test_relay_observ_requires_token_when_set():
    """When RELAY_TRUST_TOKEN is configured, the observ read endpoints must
    reject requests without a matching X-Relay-Token (defense in depth against
    a reachable-but-unauthenticated relay exposing request history)."""
    import screwshell.gateway.relay as relay

    saved = relay.RELAY_TRUST_TOKEN
    try:
        relay.RELAY_TRUST_TOKEN = "secret"
        r = _install_fake(_FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
        with TestClient(r.app) as client:
            # no token -> 401
            assert client.get("/v1/observ/summary").status_code == 401
            assert client.get("/v1/observ/events").status_code == 401
            assert client.get("/v1/observ/gpu").status_code == 401
            # matching token -> 200
            assert client.get("/v1/observ/summary",
                              headers={"X-Relay-Token": "secret"}).status_code == 200
            assert client.get("/v1/observ/events",
                              headers={"X-Relay-Token": "secret"}).status_code == 200
            assert client.get("/v1/observ/gpu",
                              headers={"X-Relay-Token": "secret"}).status_code == 200
    finally:
        relay.RELAY_TRUST_TOKEN = saved


def test_relay_gpu_endpoint_shape():
    """/v1/observ/gpu returns rocm-smi shape (ok:False when unavailable, e.g.
    on a non-AMD dev box) and never 500s."""
    import screwshell.gateway.relay as relay
    r = _install_fake(_FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
    with TestClient(r.app) as client:
        g = client.get("/v1/observ/gpu").json()
    assert "ok" in g
    assert "used_b" in g and "total_b" in g and "use_pct" in g


def test_event_carries_activity_fields():
    """RequestEvent exposes entry/user_msg/tool_calls/queue_wait so the panel
    can render external-frontend (opencode) requests as an activity stream."""
    from screwshell.observ.event import RequestEvent
    ev = RequestEvent(run_id="r1", user_msg="hello world",
                      tool_calls=[{"name": "bash", "args": "ls"}],
                      queue_wait_ms=12.5)
    d = ev.to_dict()
    assert d["entry"] == "ui"          # run_id present -> ScrewShell UI
    assert d["user_msg"] == "hello world"
    assert d["tool_calls"] == [{"name": "bash", "args": "ls"}]
    assert d["queue_wait_ms"] == 12.5
    api = RequestEvent(user_msg="hi")
    assert api.to_dict()["entry"] == "api"   # no run_id -> opencode/pi


# --------------------------------------------------------------------------
# Coordinator emits one event per request, carrying real timings
# --------------------------------------------------------------------------
def test_coordinator_emits_event_with_timings(tmp_path):
    from screwshell.observ import ObservStore
    store = ObservStore(str(tmp_path))
    with patch.object(store_mod, "get_store", lambda: store):
        class _Resp:
            status_code = 200

            def json(self):
                return {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 12,
                              "prompt_tokens_details": {"cached_tokens": 5}},
                    "timings": {"prompt_ms": 8.0, "predicted_ms": 50.0,
                                "predicted_per_second": 22.0, "cache_n": 5},
                }

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None):
                return _Resp()

        coord = InferenceCoordinator(llama_server_url="http://127.0.0.1:1",
                                     max_pending=4)
        coord.engine.adapters = {"cybersec": {"id": 1}}
        coord.engine.activate = lambda *a, **k: None  # no real LoRA switch
        coord._current_expert = None

        with patch("httpx.AsyncClient", _Client):
            resp = asyncio.run(coord.request(
                "cybersec",
                {"model": "m",
                 "messages": [{"role": "user", "content": "hi"}]},
                False, request_id="r9"))
    assert resp.status_code == 200

    evs = store.recent(5)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["request_id"] == "r9"
    assert ev["adapter"] == "cybersec"
    assert ev["switched"] is True
    assert ev["prompt_tokens"] == 7 and ev["completion_tokens"] == 12
    assert ev["cached_tokens"] == 5
    assert abs(ev["kv_hit_rate"] - (5 / 7)) < 1e-3
    assert ev["prefill_ms"] == 8.0 and ev["decode_tps"] == 22.0
    assert ev["ok"] is True


def test_coordinator_queue_full_emits_no_event(tmp_path):
    from screwshell.observ import ObservStore
    store = ObservStore(str(tmp_path))
    with patch.object(store_mod, "get_store", lambda: store):
        coord = InferenceCoordinator(llama_server_url="http://127.0.0.1:1",
                                 max_pending=0)
        coord.engine.adapters = {"cybersec": {"id": 1}}
        coord.engine.activate = lambda *a, **k: None
        out = asyncio.run(coord.request("cybersec", {"model": "m"}, False))
    assert out is None  # relay turns this into 429; no event emitted
    assert store.recent(5) == []


# --------------------------------------------------------------------------
# Session-scoped observability (2026-08-05): boundary rule + filters
# --------------------------------------------------------------------------
def test_assign_operational_session_boundary_rules():
    """§5.2 controlled boundary signal.

    - cached_tokens==0 + valid prompt -> NEW session (no_reusable_prefix).
    - cached_tokens>0 -> continuation (same session id, reason "").
    - empty prompt (cache_signal_valid False) -> NO boundary even if 0 cached.
    """
    from screwshell.observ.event import RequestEvent
    coord = InferenceCoordinator(llama_server_url="http://127.0.0.1:1")
    coord.engine.adapters = {}
    coord._current_expert = None

    # 1) first request -> "first"
    e1 = RequestEvent(prompt_tokens=100, cached_tokens=50,
                      cache_signal_valid=True)
    coord._assign_operational_session(e1)
    assert e1.boundary_reason == "first"
    sid = e1.operational_session_id
    assert sid

    # 2) warm continuation (cached>0) -> same id, reason "" (not a boundary)
    e2 = RequestEvent(prompt_tokens=100, cached_tokens=80,
                      cache_signal_valid=True)
    coord._assign_operational_session(e2)
    assert e2.operational_session_id == sid
    assert e2.boundary_reason == ""

    # 3) no reusable prefix observed (cached==0, valid prompt) -> NEW session
    e3 = RequestEvent(prompt_tokens=100, cached_tokens=0,
                      cache_signal_valid=True)
    coord._assign_operational_session(e3)
    assert e3.boundary_reason == "no_reusable_prefix"
    assert e3.operational_session_id != sid

    # 4) guard: empty prompt must NOT trigger a boundary even with cached==0
    #    (cache_signal_valid stays False because prompt_tokens==0).
    e4 = RequestEvent(prompt_tokens=0, cached_tokens=0)
    coord._assign_operational_session(e4)
    # reason stays "" (continuation of e3's session, not a boundary)
    assert e4.boundary_reason == ""
    assert e4.operational_session_id == e3.operational_session_id


def test_summarize_session_excludes_benchmark(tmp_path):
    """The health banner must judge the CURRENT session, not global history.

    A historical benchmark outlier (cached_tokens==0, 25s TTFT, benchmark=True)
    must NOT pin the session-scoped summary red, while the warm session's p95
    stays ~2s.
    """
    store = ObservStore(str(tmp_path))
    store.record(RequestEvent(prompt_tokens=50000, cached_tokens=0,
                              ttft_ms=25541.0, benchmark=True,
                              boundary_reason="no_reusable_prefix",
                              operational_session_id="old", run_id="r1"))
    sid = "sess-warm"
    for i, tt in enumerate([2100.0, 2200.0, 2150.0, 2050.0]):
        store.record(RequestEvent(prompt_tokens=200, cached_tokens=150,
                                  ttft_ms=tt, operational_session_id=sid,
                                  run_id="r1",
                                  boundary_reason="" if i else "first"))

    # global summary still reflects the outlier (back-compat)
    g = store.summarize()
    assert g["count"] == 5
    assert g["avg_ttft_ms"] > 6000  # outlier present

    # session-scoped + exclude_benchmark isolates the 4 warm requests
    sc = store.summarize(operational_session_id=sid, exclude_benchmark=True)
    assert sc["count"] == 4
    assert sc["ttft_p95"] < 3000
    assert sc["avg_ttft_ms"] < 2500

    # relay filter path through module-level wrapper
    from screwshell.observ import summarize as summarize_fn
    store_mod._STORE = store
    store_mod._STORE_READY = True
    sc2 = summarize_fn(operational_session_id=sid, exclude_benchmark=True)
    assert sc2["count"] == 4


def test_relay_summary_query_params_filter(tmp_path):
    """/v1/observ/summary?session_id=&exclude_benchmark= honors filters."""
    from screwshell.observ import ObservStore
    store = ObservStore(str(tmp_path))
    store.record(RequestEvent(operational_session_id="s1", run_id="r1",
                              ttft_ms=2000.0, benchmark=False,
                              boundary_reason="first"))
    store.record(RequestEvent(operational_session_id="s2", run_id="r2",
                              ttft_ms=30000.0, benchmark=True,
                              boundary_reason="no_reusable_prefix"))
    with patch.object(store_mod, "get_store", lambda: store):
        relay = _install_fake(_FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
        with TestClient(relay.app) as client:
            full = client.get("/v1/observ/summary").json()
            scoped = client.get(
                "/v1/observ/summary?session_id=s1&exclude_benchmark=true").json()
            ev_scoped = client.get(
                "/v1/observ/events?session_id=s1").json()
    assert full["count"] == 2
    assert scoped["count"] == 1
    assert ev_scoped["events"][0]["operational_session_id"] == "s1"


def test_compute_percentiles_includes_p99():
    """analysis.compute_percentiles now returns p99 (§5.3)."""
    from screwshell.ui.analysis import compute_percentiles, percentile
    # numpy-style linear interpolation: q=99 -> k=2.97 -> 3 + 0.97*(4-3)=3.97
    assert abs(percentile([1, 2, 3, 4], 99) - 3.97) < 1e-9
    p = compute_percentiles([{"ttft_ms": v} for v in
                             [1000, 2000, 3000, 9000, 1500]])
    assert p["n"] == 5
    assert "p99" in p
    assert isinstance(p["p99"], float)
    assert p["p99"] >= p["p95"]  # monotonic
