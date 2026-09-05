"""Stage-1 (switch_ms) + Stage-2 (vacuum status) acceptance tests.

OFFLINE. Covers:
  * RequestEvent gains ``switch_ms`` and stays whitelist-compatible with old
    records (from_dict ignores unknown / missing keys).
  * ObservStore persists switch_ms and ``summarize()`` returns avg_switch_ms
    (aggregated + None on empty table).
  * InferenceCoordinator records switch_ms (~ms) when a global LoRA switch
    happens, and None when the same expert is reused (both stream + non-stream
    paths). Pure timing measurement -- never fabricated.
  * UI status block surfaces the vacuum hint (switch cost) in degraded mode.
"""
from __future__ import annotations

import asyncio
import time
import types
from unittest.mock import patch

import pytest

import screwshell.core.inference_coordinator as coord_mod
from screwshell.observ import RequestEvent, get_store, summarize
from screwshell.observ import store as store_mod
from screwshell.ui import app as ui_app


# --------------------------------------------------------------------------
# RequestEvent
# --------------------------------------------------------------------------
def test_event_switch_ms_field_and_whitelist():
    ev = RequestEvent()
    assert ev.switch_ms is None
    ev.switch_ms = 12.3
    d = ev.to_dict()
    assert "switch_ms" in d and d["switch_ms"] == 12.3
    # old record missing switch_ms must round-trip without error
    old = {"ts": 1.0, "route": "btl3", "switched": True, "status_code": 200}
    ev2 = RequestEvent.from_dict(old)
    assert ev2.switch_ms is None


# --------------------------------------------------------------------------
# ObservStore aggregation
# --------------------------------------------------------------------------
def _reset_store(monkeypatch, tmp_path):
    store_mod._STORE = None
    store_mod._STORE_READY = False
    monkeypatch.setenv("OBSERV_DIR", str(tmp_path))
    monkeypatch.setenv("RELAY_EMBEDDER", "0")


def test_store_summarize_avg_switch_ms(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    store = get_store()
    for v in (10.0, 20.0, 30.0):
        store.record(RequestEvent(switch_ms=v, switched=True,
                                  route="btl3", adapter="btl3"))
    s = summarize()
    assert s["avg_switch_ms"] == 20.0
    # no switch -> switch_ms None must not poison the average
    store.record(RequestEvent(switch_ms=None, switched=False, route="base"))
    s = summarize()
    assert s["avg_switch_ms"] == 20.0


def test_store_summarize_switch_ms_none_when_empty(monkeypatch, tmp_path):
    _reset_store(monkeypatch, tmp_path)
    s = summarize()
    assert s["count"] == 0
    assert s["avg_switch_ms"] is None


# --------------------------------------------------------------------------
# InferenceCoordinator: real timing at both activate calls
# --------------------------------------------------------------------------
class _FakeEngine:
    def __init__(self, adapters, sleep_s=0.01):
        self.adapters = adapters
        self.server_url = "http://127.0.0.1:8080"
        self._sleep = sleep_s
        self.calls = 0

    def activate(self, target):
        self.calls += 1
        time.sleep(self._sleep)   # simulate a real (slow) LoRA switch

    def load_base(self):
        return None


class _FakeResp:
    def __init__(self, json_data=None, text="{}"):
        self._json = json_data or {}
        self.text = text
        self.status_code = 200

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Non-stream: returns a body with usage+timings so _fill_from_body works."""
    def __init__(self, body=None):
        self._body = body or {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 10,
                      "prompt_tokens_details": {"cached_tokens": 0}},
            "timings": {"prompt_ms": 1, "predicted_ms": 2,
                        "predicted_per_second": 18.0},
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return _FakeResp(json_data=self._body)


class _FakeStreamResp:
    def __init__(self, chunks):
        self._chunks = chunks
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_raw(self):
        for c in self._chunks:
            yield c


class _FakeStreamClient:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    # httpx.AsyncClient.stream is a *sync* method returning an async-CM
    def stream(self, *a, **k):
        return _FakeStreamResp(self._chunks)


def _make_coord(adapters):
    coord = coord_mod.InferenceCoordinator(startup_timeout_s=0.1)
    coord.engine = _FakeEngine(adapters)
    coord.router = coord_mod.SkillRouter()
    return coord


def test_coordinator_nonstream_records_switch_ms_and_none_on_reuse():
    captured = []
    coord = _make_coord(["btl3", "cybersec"])
    payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}

    async def run():
        with patch.object(coord_mod, "record_event",
                          side_effect=lambda ev: captured.append(ev)):
            with patch.object(coord_mod.httpx, "AsyncClient",
                              lambda *a, **k: _FakeAsyncClient()):
                await coord.request("btl3", payload, is_stream=False)
                # same expert -> no switch
                await coord.request("btl3", payload, is_stream=False)

    asyncio.run(run())
    assert len(captured) == 2
    ev1, ev2 = captured
    assert ev1.switched is True
    assert ev1.switch_ms is not None and 1 < ev1.switch_ms < 2000
    assert ev2.switched is False
    assert ev2.switch_ms is None


def test_coordinator_stream_records_switch_ms():
    captured = []
    coord = _make_coord(["btl3", "cybersec"])
    payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    async def run():
        with patch.object(coord_mod, "record_event",
                          side_effect=lambda ev: captured.append(ev)):
            with patch.object(coord_mod.httpx, "AsyncClient",
                              lambda *a, **k: _FakeStreamClient(chunks)):
                resp = await coord.request("btl3", payload, is_stream=True)
                async for _ in resp.body_iterator:
                    pass

    asyncio.run(run())
    assert len(captured) == 1
    ev = captured[0]
    assert ev.switched is True
    assert ev.switch_ms is not None and 1 < ev.switch_ms < 2000


# --------------------------------------------------------------------------
# Stage-2 (degraded): status block surfaces vacuum hint with switch cost
# --------------------------------------------------------------------------
def test_status_block_shows_switch_hint_in_vacuum(monkeypatch):
    monkeypatch.setattr(ui_app, "_UI_STATE", {
        "plan": "", "lora": [], "tools": [], "gens": [],
        "phase": "thinking", "phase_i": 0, "phase_n": 0,
        "start_ts": time.time() - 5, "thinking": "",
    })
    monkeypatch.setattr(ui_app, "_obs_state", {
        "summary": {"avg_switch_ms": 42.0},
        "slots": None, "expert": None, "llama_metrics": None,
        "gpu": None, "health": None, "recent": [],
    })
    block = ui_app._status_block("zh")
    # phase text is the primary line and is not overridden by a generic
    # "connecting/switching" message; the switch cost is a secondary note.
    assert "调查中…" in block
    assert "切换约 42ms" in block
    assert "连接/切换专家中" not in block


def test_status_block_quick_shows_total_time_not_in_progress(monkeypatch):
    monkeypatch.setattr(ui_app, "_UI_STATE", {
        "plan": "", "lora": [], "tools": [], "gens": [],
        "phase": "quick", "phase_i": 0, "phase_n": 0,
        "start_ts": time.time() - 123, "thinking": "",
    })
    monkeypatch.setattr(ui_app, "_obs_state", {
        "summary": {"avg_switch_ms": 1.0},
        "slots": None, "expert": None, "llama_metrics": None,
        "gpu": None, "health": None, "recent": [],
    })
    block = ui_app._status_block("zh")
    assert "正在快速回复…" in block
    assert "本次回答耗时" in block
    assert "进行中" not in block
    assert "连接/切换专家中" not in block
