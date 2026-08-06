"""Unit tests for the auto-tune UI panel (tune-loop plan, Todo 7).

Covers: i18n keys present in BOTH zh and en; the tune POST helper targets the
right endpoint with the right payload; and make_ui() builds the dashboard
(including the tune tab + wired buttons) without error.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import screwshell.ui.app as app


NEW_KEYS = [
    "tab_autotune", "tune_preset", "tune_preset_speed", "tune_preset_vram",
    "tune_preset_ctx", "tune_preset_balance", "tune_start", "tune_stop",
    "tune_status_idle", "tune_status_running", "tune_status_done",
    "tune_status_abort", "tune_rolling_back", "tune_converged", "tune_progress",
]


def test_i18n_keys_present_both_langs():
    for key in NEW_KEYS:
        assert key in app.I18N["zh"], f"missing zh i18n key: {key}"
        assert key in app.I18N["en"], f"missing en i18n key: {key}"


def test_tune_post_targets_start_endpoint(monkeypatch):
    captured = {}
    monkeypatch.setattr(app, "_RELAY_TOKEN", "secret")  # token set -> header sent

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"status": "running"}'

    def _fake_urlopen(req, timeout=5):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["headers"] = dict(req.headers)
        captured["method"] = req.method
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    resp = app._tune_post("/v1/tune/start", {"preset": "vram"})
    assert resp == {"status": "running"}
    assert captured["url"].endswith("/v1/tune/start")
    assert captured["method"] == "POST"
    body = json.loads(captured["data"].decode("utf-8"))
    assert body["preset"] == "vram"
    # auth header forwarded from _obs_headers (urllib lowercases header keys)
    assert any(k.lower() == "x-relay-token" for k in captured["headers"])


def test_tune_post_surfaces_http_error(monkeypatch):
    def _boom(req, timeout=5):
        raise urllib.error.HTTPError(
            req.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    resp = app._tune_post("/v1/tune/stop", {})
    assert resp.get("status_code") == 401


def test_make_ui_builds_with_tune_tab():
    # Constructing make_ui exercises the tab + button wiring; a bad .click()
    # or missing component would raise here. Use a minimal fake ctx with the
    # orchestrator attributes make_ui touches at build time.
    class _FakeOrchestrator:
        def run(self, *a, **k):
            return None
    class _FakeCtx:
        def __init__(self):
            self.orchestrator = _FakeOrchestrator()
    try:
        demo = app.make_ui(_FakeCtx())
    except Exception as e:  # noqa: BLE001 - surface any wiring/build error
        raise AssertionError(f"make_ui failed to build tune tab: {e}")
    # gradio Blocks returned something usable
    assert demo is not None
