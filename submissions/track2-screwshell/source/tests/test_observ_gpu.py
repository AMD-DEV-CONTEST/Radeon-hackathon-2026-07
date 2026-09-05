"""Observatory GPU / slots / expert / metrics acceptance tests (BUILD_OBSERVATORY_PLAN).

OFFLINE (no GPU, no live llama-server). Covers:
  * ObservStore GPU sample persistence: record -> recent (newest-first, fields,
    order, n clamp), and silent no-op when OBSERV_DIR is unset.
  * relay /v1/observ/gpu_history (R3 backend history) + /v1/observ/slots (R1)
    + /v1/observ/expert (R4) + /v1/observ/llama_metrics (R2, optional
    --metrics). Auth 401 when RELAY_TRUST_TOKEN set; the new endpoints respect
    it too. Upstream /slots and /metrics are mocked so we never touch the box.
"""
from __future__ import annotations

import json
import types
from unittest.mock import patch

import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import screwshell.gateway.relay as relay
from screwshell.core.router import SkillRouter
from screwshell.observ import get_store, record_gpu_sample, recent_gpu
from screwshell.observ import store as store_mod


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _reset_store(monkeypatch, tmp_path):
    store_mod._STORE = None
    store_mod._STORE_READY = False
    monkeypatch.setenv("OBSERV_DIR", str(tmp_path))
    monkeypatch.setenv("RELAY_EMBEDDER", "0")


class _FakeCoordinator:
    """Offline stand-in; adds ``server_url`` so slots/metrics endpoints work."""

    def __init__(self, adapters, current_expert=None):
        self.engine = types.SimpleNamespace(
            adapters=adapters, server_url="http://127.0.0.1:8080")
        self.router = SkillRouter()
        self._current_expert = current_expert

    def load_base(self):
        return None

    async def request(self, *a, **k):
        return JSONResponse({"choices": [{"message": {"content": "ok"}}],
                             "usage": {}})


class _FakeResp:
    def __init__(self, json_data=None, text=None):
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Mocks httpx.AsyncClient so upstream /slots + /metrics are local."""

    def __init__(self, slots=None, metrics_text=""):
        self._slots = slots or []
        self._metrics = metrics_text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if url.endswith("/slots"):
            return _FakeResp(json_data=self._slots)
        if url.endswith("/metrics"):
            return _FakeResp(text=self._metrics)
        return _FakeResp(json_data={})


def _install_fake(coord):
    relay.coord = coord
    return relay


def _patch_upstream(slots=None, metrics_text=""):
    return patch.object(
        relay.httpx, "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(slots=slots, metrics_text=metrics_text))


# --------------------------------------------------------------------------
# ObservStore GPU persistence
# --------------------------------------------------------------------------
def test_store_gpu_record_recent_order_and_fields(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    store = get_store()
    assert store.enabled is True
    samples = [
        {"ts": 1.0, "card": "card0", "use_pct": 10.0,
         "vram_used_b": 1, "vram_total_b": 10, "temp_c": 50.0, "power_w": 100.0},
        {"ts": 2.0, "card": "card0", "use_pct": 20.0,
         "vram_used_b": 2, "vram_total_b": 10, "temp_c": 51.0, "power_w": 110.0},
        {"ts": 3.0, "card": "card0", "use_pct": 30.0,
         "vram_used_b": 3, "vram_total_b": 10, "temp_c": 52.0, "power_w": 120.0},
    ]
    for s in samples:
        record_gpu_sample(s)
    out = recent_gpu(10)
    assert len(out) == 3
    # newest-first
    assert out[0]["ts"] == 3.0 and out[-1]["ts"] == 1.0
    # all GPU columns present
    for row in out:
        for col in ("ts", "card", "use_pct", "vram_used_b",
                    "vram_total_b", "temp_c", "power_w"):
            assert col in row
    # persisted to SQLite too
    import sqlite3
    con = sqlite3.connect(str(tmp_path / "requests.db"))
    n = con.execute("SELECT count(*) FROM gpu_samples").fetchone()[0]
    assert n == 3


def test_store_gpu_recent_respects_n(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    for i in range(5):
        record_gpu_sample({"ts": float(i), "card": "card0"})
    assert len(recent_gpu(2)) == 2
    assert len(recent_gpu(1800)) == 5


def test_store_gpu_is_noop_when_observ_dir_unset(monkeypatch):
    monkeypatch.delenv("OBSERV_DIR", raising=False)
    monkeypatch.setenv("RELAY_EMBEDDER", "0")
    store_mod._STORE = None
    store_mod._STORE_READY = False
    store = get_store()
    assert store.enabled is False
    # must not raise even with a full sample
    record_gpu_sample({"ts": 1.0, "card": "card0", "use_pct": 1.0,
                       "vram_used_b": 1, "vram_total_b": 2,
                       "temp_c": 40.0, "power_w": 90.0})
    assert recent_gpu(10) == []


# --------------------------------------------------------------------------
# Relay GPU history endpoint (R3)
# --------------------------------------------------------------------------
def test_relay_gpu_history_serves_store(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    for i in range(3):
        record_gpu_sample({"ts": float(i), "card": "card0",
                           "use_pct": float(i), "vram_used_b": i,
                           "vram_total_b": 10, "temp_c": 50.0, "power_w": 100.0})
    r = _install_fake(_FakeCoordinator(["btl3", "cybersec"]))
    with TestClient(r.app) as client:
        body = client.get("/v1/observ/gpu_history?n=10").json()
    assert "samples" in body
    assert len(body["samples"]) == 3
    assert body["samples"][0]["ts"] == 2.0  # newest-first


def test_relay_gpu_history_clamps_n(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    r = _install_fake(_FakeCoordinator(["btl3"]))
    with TestClient(r.app) as client:
        # n > 1800 -> clamped; n < 1 -> clamped; should not 500
        assert client.get("/v1/observ/gpu_history?n=99999").status_code == 200
        assert client.get("/v1/observ/gpu_history?n=0").status_code == 200


# --------------------------------------------------------------------------
# Relay slots / expert / metrics endpoints
# --------------------------------------------------------------------------
def test_relay_slots_forwards_upstream(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    slots = [
        {"id": 0, "is_processing": True, "n_prompt_tokens_processed": 5,
         "n_prompt_tokens": 100},
        {"id": 1, "is_processing": False},
    ]
    r = _install_fake(_FakeCoordinator(["btl3", "cybersec"]))
    with _patch_upstream(slots=slots):
        with TestClient(r.app) as client:
            body = client.get("/v1/observ/slots").json()
    assert isinstance(body, list) and len(body) == 2
    assert body[0]["is_processing"] is True
    assert body[0]["n_prompt_tokens"] == 100


def test_relay_slots_502_on_upstream_failure(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("llama-server down")

    r = _install_fake(_FakeCoordinator(["btl3"]))
    with patch.object(relay.httpx, "AsyncClient", side_effect=_boom):
        with TestClient(r.app) as client:
            resp = client.get("/v1/observ/slots")
    assert resp.status_code == 502


def test_relay_expert_returns_current(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    r = _install_fake(_FakeCoordinator(
        ["btl3", "cybersec", "rag_n7"], current_expert="btl3"))
    with TestClient(r.app) as client:
        body = client.get("/v1/observ/expert").json()
    assert body["current_expert"] == "btl3"
    assert body["adapters"] == ["btl3", "cybersec", "rag_n7"]


def test_relay_llama_metrics_parses_counters(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    text = (
        "# HELP llamacpp:cache_hits_total\n"
        "llamacpp:cache_hits_total 4096\n"
        "llamacpp:prompt_tokens_total 1234\n"
        "llamacpp:tokens_predicted_total 567\n"
        "llamacpp:n_busy_slots_per_decode 0\n"
    )
    r = _install_fake(_FakeCoordinator(["btl3"]))
    with _patch_upstream(metrics_text=text):
        with TestClient(r.app) as client:
            body = client.get("/v1/observ/llama_metrics").json()
    assert body["ok"] is True
    c = body["counters"]
    assert c["cache_hits_total"] == 4096.0
    assert c["prompt_tokens_total"] == 1234.0
    assert c["tokens_predicted_total"] == 567.0
    assert c["n_busy_slots_per_decode"] == 0.0


def test_relay_llama_metrics_ok_false_on_down(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("no /metrics")

    r = _install_fake(_FakeCoordinator(["btl3"]))
    with patch.object(relay.httpx, "AsyncClient", side_effect=_boom):
        with TestClient(r.app) as client:
            body = client.get("/v1/observ/llama_metrics").json()
    assert body["ok"] is False
    assert "error" in body


# --------------------------------------------------------------------------
# Auth: new endpoints also require the token when RELAY_TRUST_TOKEN is set
# --------------------------------------------------------------------------
def test_relay_gpu_detailed_parses_rocm_json(monkeypatch):
    """Regression: _read_gpu_detailed must parse rocm-smi --json (V1 shipped a
    NameError on `json` that only surfaced on real hardware, so the GPU sampler
    silently recorded nothing). Mock subprocess so this runs offline."""
    fake = types.SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"card0": {
            "GPU use (%)": "50",
            "VRAM Total Used Memory (B)": "20000000000",
            "VRAM Total Memory (B)": "51522830336",
            "Temperature (Sensor edge) (C)": "61.0",
            "Average Graphics Package Power (W)": "120.0",
        }}),
        stderr="")
    monkeypatch.setattr(relay.subprocess, "run", lambda *a, **k: fake)
    s = relay._read_gpu_detailed()
    assert s["ok"] is True
    assert s["use_pct"] == 50.0
    assert s["vram_total_b"] == 51522830336
    assert s["power_w"] == 120.0
    assert s["temp_c"] == 61.0


def test_relay_new_observ_endpoints_require_token_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("RELAY_EMBEDDER", "0")
    saved = relay.RELAY_TRUST_TOKEN
    try:
        relay.RELAY_TRUST_TOKEN = "secret"
        r = _install_fake(_FakeCoordinator(
            ["btl3", "cybersec"], current_expert="btl3"))
        with _patch_upstream(
                slots=[{"id": 0, "is_processing": False}],
                metrics_text="llama:cache_hits_total 1\n"):
            with TestClient(r.app) as client:
                for path in ("/v1/observ/gpu_history",
                             "/v1/observ/slots",
                             "/v1/observ/expert",
                             "/v1/observ/llama_metrics"):
                    assert client.get(path).status_code == 401
                    assert client.get(
                        path,
                        headers={"X-Relay-Token": "secret"}).status_code == 200
    finally:
        relay.RELAY_TRUST_TOKEN = saved
