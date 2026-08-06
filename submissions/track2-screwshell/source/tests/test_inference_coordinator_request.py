"""Real-behavior tests for InferenceCoordinator.request and the relay's
X-Expert trust boundary.

Unlike tests/test_phase0_coordinator.py (which drives the relay through a
FakeCoordinator), this file exercises the REAL coord.request glue -- the
switch+generate, lock, lora-stripping, status passthrough, streaming error
handling, queue-full 429, and the startup readiness gate. It is the
"behavior gate" that the Phase 0 review flagged was missing.

No GPU / no live llama-server: httpx.AsyncClient is mocked, and
engine.activate is replaced with a recorder. OBSERV_DIR is unset, so the
observ store degrades to a no-op (no files written).
"""
from __future__ import annotations

import asyncio
import json
import types
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from screwshell.core.inference_coordinator import InferenceCoordinator
from screwshell.core.router import SkillRouter


# --------------------------------------------------------------------------
# Fake httpx.AsyncClient
# --------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {
            "choices": [{"message": {"content": "ok"}}], "usage": {}}
        self.text = text

    def json(self):
        return self._json


class _FakeStreamResp:
    def __init__(self, status=200, chunks=None):
        self.status_code = status
        self._chunks = chunks if chunks is not None else [
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n',
            b"data: [DONE]\n\n",
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_raw(self):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b"".join(self._chunks)


class _FakeAsyncClient:
    def __init__(self, post_status=200, stream_status=200):
        self.calls = []
        self.post_status = post_status
        self.stream_status = stream_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **k):
        self.calls.append(("POST", url, json))
        return _FakeResp(status=self.post_status)

    def stream(self, method, url, json=None, **k):
        self.calls.append((method, url, json))
        return _FakeStreamResp(status=self.stream_status)


def _patch_client(client):
    return patch("screwshell.core.inference_coordinator.httpx.AsyncClient",
                 lambda *a, **k: client)


def _make_coord(max_pending=4, startup_timeout_s=30.0):
    coord = InferenceCoordinator(llama_server_url="http://127.0.0.1:1",
                                 max_pending=max_pending,
                                 startup_timeout_s=startup_timeout_s)
    coord.engine.adapters = {
        "btl3": {"id": 0}, "cybersec": {"id": 1}, "rag_n7": {"id": 2}}
    coord.engine.activate = lambda name: None  # recorder injected per-test
    return coord


_PAYLOAD = {"model": "m", "messages": [{"role": "user", "content": "x"}]}


# --------------------------------------------------------------------------
# Switch timing: only switch when the expert actually changes
# --------------------------------------------------------------------------
def test_request_switches_only_on_expert_change():
    coord = _make_coord()
    switches = []
    coord.engine.activate = lambda name: switches.append(name)
    client = _FakeAsyncClient()
    with _patch_client(client):
        assert asyncio.run(coord.request("cybersec", _PAYLOAD, False)).status_code == 200
        # same expert again -> no switch
        asyncio.run(coord.request("cybersec", _PAYLOAD, False))
        # different expert -> switch
        asyncio.run(coord.request("btl3", _PAYLOAD, False))
    assert switches == ["cybersec", "btl3"], switches
    assert coord._current_expert == "btl3"


# --------------------------------------------------------------------------
# Defense in depth: never forward a per-request "lora" override (P0)
# --------------------------------------------------------------------------
def test_request_strips_lora_override():
    coord = _make_coord()
    client = _FakeAsyncClient()
    payload = dict(_PAYLOAD)
    payload["lora"] = [{"id": 1, "scale": 1.0}]
    with _patch_client(client):
        asyncio.run(coord.request("cybersec", payload, False))
    assert client.calls, "expected a POST to the upstream"
    sent = client.calls[0][2]
    assert "lora" not in sent, "per-request lora must be stripped at coordinator"


# --------------------------------------------------------------------------
# OpenAI-standard clients (opencode / pi) never send thinking controls; Qwen3.6
# defaults thinking ON and would then return empty content / no tool calls
# (verified on W7900: only chat_template_kwargs.enable_thinking is honored).
# The coordinator must default thinking OFF for them (explicit wins).
# --------------------------------------------------------------------------
def test_request_injects_thinking_disabled_for_standard_clients():
    coord = _make_coord()
    client = _FakeAsyncClient()
    with _patch_client(client):
        asyncio.run(coord.request("cybersec", dict(_PAYLOAD), False))
    sent = client.calls[0][2]
    assert sent.get("chat_template_kwargs") == {"enable_thinking": False}, sent


def test_request_respects_explicit_thinking_control():
    coord = _make_coord()
    client = _FakeAsyncClient()
    payload = dict(_PAYLOAD)
    payload["chat_template_kwargs"] = {"enable_thinking": True}  # explicitly on
    with _patch_client(client):
        asyncio.run(coord.request("cybersec", payload, False))
    sent = client.calls[0][2]
    assert sent.get("chat_template_kwargs") == {"enable_thinking": True}, sent


# --------------------------------------------------------------------------
# Activity-stream fields: the panel renders external-frontend requests from
# user_msg / tool_calls / queue_wait (no raw content is stored)
# --------------------------------------------------------------------------
def test_request_extracts_activity_fields():
    coord = _make_coord()
    client = _FakeAsyncClient()
    captured = []
    payload = {"model": "m", "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "查一下当前目录"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"function": {"name": "list_dir",
                                      "arguments": '{"path": "."}'}}]},
        {"role": "tool", "content": "['a.py', 'b.py']"},
        {"role": "user", "content": "继续"},
    ]}
    with _patch_client(client), patch(
            "screwshell.core.inference_coordinator.record_event",
            side_effect=lambda ev: captured.append(ev)):
        asyncio.run(coord.request("cybersec", payload, False))
    assert captured, "an event must have been recorded"
    ev = captured[-1]
    assert ev.user_msg == "继续"                     # last user message only
    assert ev.tool_calls[0]["name"] == "list_dir"    # assistant tool call
    assert any(t["name"] == "→tool_result" for t in ev.tool_calls)
    assert ev.queue_wait_ms is not None
    assert ev.to_dict()["entry"] == "api"


# --------------------------------------------------------------------------
# Non-stream: preserve the upstream HTTP status (do not mask 4xx/5xx as 200)
# --------------------------------------------------------------------------
def test_request_nonstream_preserves_status():
    coord = _make_coord()
    client = _FakeAsyncClient(post_status=400)
    with _patch_client(client):
        r = asyncio.run(coord.request("cybersec", _PAYLOAD, False))
    assert r.status_code == 400, r.status_code


# --------------------------------------------------------------------------
# Streaming: an upstream error must yield an SSE error event, not a broken
# (silent) raw stream
# --------------------------------------------------------------------------
def test_request_stream_error_yields_sse_error():
    coord = _make_coord()
    client = _FakeAsyncClient(stream_status=500)
    with _patch_client(client):

        async def _run():
            resp = await coord.request("cybersec", _PAYLOAD, True)
            out = b""
            async for chunk in resp.body_iterator:
                out += chunk
            return resp, out

        resp, data = asyncio.run(_run())
    assert resp is not None
    assert b"error" in data, data
    assert b"upstream 500" in data, data


# --------------------------------------------------------------------------
# P0 (2026-08-04): a failed LoRA switch must not advance _current_expert
# --------------------------------------------------------------------------
def test_request_switch_failure_does_not_advance_expert():
    """engine.activate() now raises when POST /lora-adapters fails. The
    coordinator must surface that as a 500 error and leave _current_expert
    untouched -- otherwise the next request skips the switch (switched=False)
    while the server actually runs base: the silent-fallback P0.
    """
    coord = _make_coord()
    coord.engine.activate = lambda name: (_ for _ in ()).throw(
        RuntimeError("switch failed on server"))
    client = _FakeAsyncClient()
    with _patch_client(client):
        r = asyncio.run(coord.request("cybersec", _PAYLOAD, False))
    assert r.status_code == 500, r.status_code
    assert coord._current_expert is None, \
        "failed switch must not be recorded as mounted"
    assert b"switch failed" in r.body, r.body


def test_request_stream_switch_failure_yields_sse_error():
    """Streaming path: a failed switch must emit an SSE error event so the
    client sees the failure instead of a silently truncated stream.
    """
    coord = _make_coord()
    coord.engine.activate = lambda name: (_ for _ in ()).throw(
        RuntimeError("switch failed on server"))
    client = _FakeAsyncClient()
    with _patch_client(client):

        async def _run():
            resp = await coord.request("cybersec", _PAYLOAD, True)
            out = b""
            async for chunk in resp.body_iterator:
                out += chunk
            return resp, out

        resp, data = asyncio.run(_run())
    assert b"switch failed" in data, data
    assert coord._current_expert is None


# --------------------------------------------------------------------------
# Queue full: request() returns None -> relay answers 429
# --------------------------------------------------------------------------
def test_request_queue_full_returns_none():
    coord = _make_coord(max_pending=0)
    client = _FakeAsyncClient()
    with _patch_client(client):
        r = asyncio.run(coord.request("cybersec", _PAYLOAD, False))
    assert r is None


# --------------------------------------------------------------------------
# Startup readiness gate: refuse to start silent-base when no adapter is
# reachable; succeed when the server exposes preloaded LoRAs
# --------------------------------------------------------------------------
def test_load_base_raises_when_no_adapters():
    coord = _make_coord(startup_timeout_s=0.2)
    coord.engine.adapters = {}  # simulate no preloaded LoRAs
    coord.engine.load_base = lambda: None  # no-op -> adapters stays {}
    coord.engine.activate = lambda name: None
    with pytest.raises(RuntimeError):
        coord.load_base()
    assert coord._current_expert is None


def test_load_base_ok_with_adapters():
    coord = _make_coord(startup_timeout_s=5.0)
    coord.engine.activate = lambda name: None

    def fake_load():
        coord.engine.adapters = {"btl3": {"id": 0}}
        return coord.engine

    coord.engine.load_base = fake_load
    coord.load_base()  # must not raise
    assert coord._current_expert is None
    assert "btl3" in coord.engine.adapters


# --------------------------------------------------------------------------
# Relay X-Expert trust boundary: X-Expert is honored only with a matching
# X-Relay-Token; otherwise it is ignored and SkillRouter decides.
# --------------------------------------------------------------------------
class _FakeRelayCoord:
    def __init__(self, adapters):
        self.engine = types.SimpleNamespace(adapters=adapters)
        self.router = SkillRouter()
        self._current_expert = None
        self.last = None

    def load_base(self):
        return None

    async def request(self, expert, payload, is_stream, request_id=None,
                      run_id=None, benchmark=False):
        self.last = (expert, payload, is_stream)
        return JSONResponse(
            {"choices": [{"message": {"content": "ok"}}], "usage": {}})


def _install(coord):
    import screwshell.gateway.relay as relay

    relay.coord = coord
    return relay


@pytest.fixture
def relay_token_reset():
    """Restore the module-level RELAY_TRUST_TOKEN after a token test so it
    does not leak into the legacy-mode assertions in test_phase0_*.
    """
    import screwshell.gateway.relay as relay

    saved = relay.RELAY_TRUST_TOKEN
    yield
    relay.RELAY_TRUST_TOKEN = saved


def test_relay_honors_x_expert_with_token(relay_token_reset):
    import screwshell.gateway.relay as relay

    relay.RELAY_TRUST_TOKEN = "secret"
    r = _install(_FakeRelayCoord(["btl3", "cybersec", "rag_n7"]))
    with TestClient(r.app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user", "content": "anything"}]},
            headers={"X-Expert": "btl3", "X-Relay-Token": "secret"})
    assert resp.status_code == 200
    assert r.coord.last is not None
    assert r.coord.last[0] == "btl3", "trusted X-Expert must be honored"


def test_relay_ignores_x_expert_without_token(relay_token_reset):
    import screwshell.gateway.relay as relay

    relay.RELAY_TRUST_TOKEN = "secret"
    r = _install(_FakeRelayCoord(["btl3", "cybersec", "rag_n7"]))
    query = "audit this module for SQL injection"
    with TestClient(r.app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user", "content": query}]},
            headers={"X-Expert": "btl3"})  # spoof, no token
    assert resp.status_code == 200
    assert r.coord.last is not None
    assert r.coord.last[0] != "btl3", "spoofed X-Expert must be ignored"
    expected = r.coord.router.route(query).adapter
    assert r.coord.last[0] == expected, "must re-route via SkillRouter"


def test_relay_ignores_x_expert_with_wrong_token(relay_token_reset):
    import screwshell.gateway.relay as relay

    relay.RELAY_TRUST_TOKEN = "secret"
    r = _install(_FakeRelayCoord(["btl3", "cybersec", "rag_n7"]))
    query = "audit this module for SQL injection"
    with TestClient(r.app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "m",
                  "messages": [{"role": "user", "content": query}]},
            headers={"X-Expert": "btl3", "X-Relay-Token": "wrong"})
    assert resp.status_code == 200
    assert r.coord.last is not None
    assert r.coord.last[0] != "btl3", "wrong token must not honor X-Expert"
    expected = r.coord.router.route(query).adapter
    assert r.coord.last[0] == expected
