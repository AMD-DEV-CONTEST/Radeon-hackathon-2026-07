"""Phase 0 acceptance tests — the ScrewShell relay + InferenceCoordinator.

These are OFFLINE unit/integration tests. No GPU, no live llama-server:
  * the relay app is driven through FastAPI's TestClient with a FakeCoordinator
    (so no real /lora-adapters switch happens);
  * the engine's relay_mode chat() is exercised by patching urllib.urlopen to
    capture the outgoing payload/headers.

What this locks down (Layer2_Phase0_Plan.md T0.2-T0.7):
  T0.3  P0 fix  : relay_mode chat() must NOT inject a per-request "lora"
                  override (that is the silent base-fallback bug). It MUST
                  stamp X-Expert so the relay can trust the pre-decided expert.
  T0.4  routing  : relay trusts X-Expert (no re-route); without it, the
                  in-process SkillRouter decides (RouteDecision wiring).
  T0.5  stream   : streaming requests pass through and carry is_stream=True.
  T0.6  queue    : a full pending queue makes coord.request() return None and
                  the relay answers 429 (not a silent base generation).
  T0.7  boundary : the raw /lora-adapters control endpoint is never exposed
                  (always 404) — the coordinator is the only switcher.
"""
from __future__ import annotations

import json
import types
import urllib.request
from unittest.mock import patch

import pytest
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from screwshell.core.inference_coordinator import InferenceCoordinator
from screwshell.core.mol_engine_llamacpp import MoLLlamaCpp
from screwshell.core.router import SkillRouter, is_forbidden


# --------------------------------------------------------------------------
# FakeCoordinator — stands in for the real InferenceCoordinator so the relay
# can be tested without a live llama-server. It records what the relay hands
# it and optionally simulates a full queue.
# --------------------------------------------------------------------------
class FakeCoordinator:
    def __init__(self, adapters, queue_full=False, current=None):
        self.engine = types.SimpleNamespace(adapters=adapters)
        self.router = SkillRouter()
        self._current_expert = current
        self.queue_full = queue_full
        self.last = None  # (expert, payload, is_stream)

    def load_base(self):
        return None

    async def request(self, expert, payload, is_stream, request_id=None,
                      run_id=None, benchmark=False):
        self.last = (expert, payload, is_stream)
        if self.queue_full:
            return None
        return JSONResponse(
            {"choices": [{"message": {"content": "ok"}}], "usage": {}})


def _install(coord):
    import screwshell.gateway.relay as relay

    relay.coord = coord
    return relay


# --------------------------------------------------------------------------
# T0.3 — P0 fix at the engine layer: relay_mode must strip per-request lora
# --------------------------------------------------------------------------
def test_relay_mode_chat_omits_lora_and_stamps_x_expert():
    eng = MoLLlamaCpp("Qwen3.6-27B", server_url="http://127.0.0.1:1",
                      relay_mode=True)
    eng.active_adapter = "cybersec"
    eng._caps = {}  # bypass capability probe (no server)

    captured = {}

    class _FakeResp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}],
                               "usage": {}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        captured["headers"] = dict(req.headers)
        return _FakeResp()

    with patch.object(urllib.request, "urlopen", _fake_urlopen):
        text, _stats = eng.chat(
            [{"role": "user", "content": "hi"}], max_new_tokens=8,
            enable_thinking=False, stream=False)

    assert "lora" not in captured["data"], \
        "P0 regression: relay_mode chat() must NOT inject a per-request lora override"
    # HTTP header names are case-insensitive; urllib stores them normalized.
    hdr = {k.lower(): v for k, v in captured["headers"].items()}
    assert hdr.get("x-expert") == "cybersec", \
        "relay_mode must stamp the pre-decided expert on X-Expert"
    assert text == "ok"


# --------------------------------------------------------------------------
# T0.4 — routing: X-Expert wins, else SkillRouter decides
# --------------------------------------------------------------------------
def test_relay_trusts_x_expert_header_no_reroute():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
    with TestClient(relay.app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user", "content": "anything"}]},
            headers={"X-Expert": "btl3"})
    assert r.status_code == 200
    assert relay.coord.last is not None
    assert relay.coord.last[0] == "btl3", "relay must trust the X-Expert header"


def test_relay_auto_routes_without_header():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
    with TestClient(relay.app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user",
                                "content": "audit this auth module for SQL injection"}]})
    assert r.status_code == 200
    assert relay.coord.last is not None
    assert relay.coord.last[0] == "cybersec", \
        "without X-Expert the relay must route via SkillRouter"


def test_relay_completions_legacy_prompt_routes():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
    with TestClient(relay.app) as client:
        r = client.post(
            "/v1/completions",
            json={"model": "m",
                  "prompt": "读这个 py 文件，解释为什么 benchmark 慢"})
    assert r.status_code == 200
    assert relay.coord.last is not None
    assert relay.coord.last[0] == "btl3"


# --------------------------------------------------------------------------
# T0.5 — streaming passes through with is_stream True
# --------------------------------------------------------------------------
def test_relay_streaming_passthrough():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"]))

    async def _fake_stream():
        yield b"data: hello\n\n"

    async def _stream_request(expert, payload, is_stream, request_id=None,
                              run_id=None, benchmark=False):
        relay.coord.last = (expert, payload, is_stream)
        return StreamingResponse(_fake_stream(),
                                 media_type="text/event-stream")

    relay.coord.request = _stream_request
    with TestClient(relay.app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            headers={"X-Expert": "btl3"})
    assert r.status_code == 200
    assert "hello" in r.text
    assert relay.coord.last[2] is True


# --------------------------------------------------------------------------
# T0.6 — queue full -> 429 (never a silent base generation)
# --------------------------------------------------------------------------
def test_relay_returns_429_when_queue_full():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"],
                                     queue_full=True))
    with TestClient(relay.app) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Expert": "btl3"})
    assert r.status_code == 429
    assert "retry" in r.text.lower()


# --------------------------------------------------------------------------
# T0.7 — raw LoRA control endpoint is never exposed
# --------------------------------------------------------------------------
def test_relay_blocks_lora_adapters_endpoint():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"]))
    with TestClient(relay.app) as client:
        assert client.get("/lora-adapters").status_code == 404
        assert client.post("/lora-adapters", json={"x": 1}).status_code == 404
        assert client.put("/lora-adapters", json={}).status_code == 404
        assert client.delete("/lora-adapters").status_code == 404


def test_relay_health_reports_adapters_and_current():
    relay = _install(FakeCoordinator(["btl3", "cybersec", "rag_n7"],
                                     current="cybersec"))
    with TestClient(relay.app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert set(body["adapters"]) == {"btl3", "cybersec", "rag_n7"}
    assert body["current_expert"] == "cybersec"


# --------------------------------------------------------------------------
# Coordinator unit: resolve_expert only passes preloaded, non-forbidden names
# --------------------------------------------------------------------------
def test_resolve_expert_filters_forbidden_and_unknown():
    coord = InferenceCoordinator(llama_server_url="http://127.0.0.1:1",
                                 max_pending=4)
    coord.engine.adapters = {
        "btl3": {"id": 0}, "cybersec": {"id": 1}, "rag_n7": {"id": 2}}

    assert coord.resolve_expert("cybersec") == "cybersec"
    assert coord.resolve_expert(None) is None
    assert coord.resolve_expert("fable5") is None, "forbidden must degrade to base"
    assert coord.resolve_expert("ghost") is None, "un-preloaded must degrade to base"
    # sanity: is_forbidden is the gate used
    assert is_forbidden("fable5") is True
