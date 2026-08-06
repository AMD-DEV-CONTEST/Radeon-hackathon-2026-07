"""Unit tests for the relay tune endpoints (tune-loop plan, Todo 6).

Uses FastAPI TestClient. We toggle RELAY_TRUST_TOKEN via monkeypatch and inject
a fake running cycle to exercise the 409 / stop paths without a real server.
"""
from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture
def relay(monkeypatch):
    monkeypatch.setenv("RELAY_TRUST_TOKEN", "")      # start in legacy mode
    import screwshell.gateway.relay as R
    importlib.reload(R)
    from fastapi.testclient import TestClient
    return R, TestClient(R.app)


def test_no_token_legacy_allows(relay):
    R, client = relay
    # legacy mode (token unset) -> start allowed
    resp = client.post("/v1/tune/start", json={"preset": "balance"})
    assert resp.status_code in (202, 409)   # 202 running or 409 if leftover


def test_token_set_rejects_missing_header(relay, monkeypatch):
    R, client = relay
    monkeypatch.setattr(R, "RELAY_TRUST_TOKEN", "secret")
    # no X-Relay-Token header -> 401
    resp = client.post("/v1/tune/start", json={"preset": "balance"})
    assert resp.status_code == 401


def test_token_set_accepts_correct_header(relay, monkeypatch):
    R, client = relay
    monkeypatch.setattr(R, "RELAY_TRUST_TOKEN", "secret")
    resp = client.post("/v1/tune/start", json={"preset": "balance"},
                       headers={"X-Relay-Token": "secret"})
    assert resp.status_code in (202, 409)


def test_start_then_start_409(relay, monkeypatch):
    R, client = relay
    monkeypatch.setattr(R, "RELAY_TRUST_TOKEN", "secret")
    # inject a fake running cycle
    class _FakeCycle:
        status = "plan"
    with R._TUNE_LOCK:
        R._tune_cycle = _FakeCycle()
    resp = client.post("/v1/tune/start", json={"preset": "balance"},
                       headers={"X-Relay-Token": "secret"})
    assert resp.status_code == 409
    # cleanup
    with R._TUNE_LOCK:
        R._tune_cycle = None


def test_stop_no_running_is_noop(relay, monkeypatch):
    R, client = relay
    monkeypatch.setattr(R, "RELAY_TRUST_TOKEN", "secret")
    with R._TUNE_LOCK:
        R._tune_cycle = None
    resp = client.post("/v1/tune/stop", headers={"X-Relay-Token": "secret"})
    assert resp.status_code == 200
    assert resp.json().get("status") == "idle"


def test_status_returns_json(relay, monkeypatch):
    R, client = relay
    monkeypatch.setattr(R, "RELAY_TRUST_TOKEN", "secret")
    resp = client.get("/v1/tune/status", headers={"X-Relay-Token": "secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "server_may_be_down" in body


def test_state_file_path_resolves(monkeypatch):
    monkeypatch.setenv("OBSERV_DIR", "/tmp/observ")
    import screwshell.gateway.relay as R
    importlib.reload(R)
    assert R._tune_state_path == os.path.join("/tmp/observ", "tune_state.json")


# ------------------------- wiring regression (flatten) -------------------------

_PROPS = {
    "model": "m",
    "default_generation_settings": {
        "n_ctx": 98304, "n_batch": 512, "n_parallel": 2,
        "n_threads": 24, "n_gpu_layers": 50, "reasoning_budget": 4096,
        "cache_type_k": "q8_0", "cache_type_v": "q8_0", "flash_attn": "on",
    },
}


def test_argv_builder_flattens_nested_props(monkeypatch):
    import screwshell.gateway.relay as R
    importlib.reload(R)
    argv = R._tune_argv_builder(_PROPS)
    # nested default_generation_settings must be honored -> --batch-size 512
    assert "--batch-size" in argv
    assert argv[argv.index("--batch-size") + 1] == "512"
    assert "--ctx-size" in argv


def test_apply_goal_change_flows_into_argv(monkeypatch):
    # Regression for the flattening precedence bug: a TuneGoal applied by the
    # cycle (flat key override) MUST NOT be clobbered by the stale nested
    # default when the argv builder re-flattens the mutated spec.
    import screwshell.gateway.relay as R
    import screwshell.autotune.cycle as C
    importlib.reload(R)
    from screwshell.autotune.mapper import TuneGoal

    cyc = C.TuneCycle.__new__(C.TuneCycle)  # bypass __init__; only _apply_goal
    cyc.applied_spec = dict(_PROPS)
    goal = TuneGoal(param="n_batch", target=1024, reason="test")
    mutated = cyc._apply_goal(dict(_PROPS), goal)   # writes flat n_batch=1024
    argv = R._tune_argv_builder(mutated)
    assert "--batch-size" in argv
    assert argv[argv.index("--batch-size") + 1] == "1024"  # override won, not 512


def test_planner_reads_flat_nested(monkeypatch):
    import screwshell.gateway.relay as R
    importlib.reload(R)
    goal = R._tune_planner("speed", _PROPS, "n-batch")
    assert goal.param == "n_batch"
    assert goal.target == max(512 * 2, 512)   # from nested n_batch=512 doubled


def test_tune_collect_wide_window(monkeypatch):
    # Regression: _tune_collect must fetch a WIDE window (n=200) so interleaved
    # non-benchmark events don't starve the benchmark count below MIN_N.
    import screwshell.gateway.relay as R
    import screwshell.observ as obs
    importlib.reload(R)
    calls = {}

    def _fake_filtered(n=20, run_id=None, operational_session_id=None,
                       time_window_s=None, exclude_benchmark=False):
        calls["n"] = n
        bench = [{"benchmark": True, "ttft_ms": 500, "decode_tps": 30,
                  "kv_hit_rate": 0.9, "ok": True}] * 16
        other = [{"benchmark": False}] * 4
        return bench + other

    monkeypatch.setattr(obs, "recent_events_filtered", _fake_filtered)
    evs = R._tune_collect()
    assert calls["n"] == 200               # wide window fetched
    assert len([e for e in evs if e.get("benchmark")]) >= R.MIN_N_SAFE
