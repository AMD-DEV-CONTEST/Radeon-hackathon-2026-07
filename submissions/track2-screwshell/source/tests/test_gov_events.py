"""P4 — governor events (BUILD_OBSERVATORY_V3 §2.8, D1).

Two guards:
  * D1: the orchestrator emits a unified ``governor_action`` event (plus the
    specific ones) when ``observe()`` returns a non-empty action — pure
    observation, zero behavior change.
  * The UI ``ingest_gov_event`` hook + ``fmt_governor`` render the governor
    card honestly: "disabled" when no events, actions/alerts when present.
"""
from __future__ import annotations

import types

import pytest

from screwshell.autotune.governor import GovernorAction
from screwshell.ui import app as ui_app


@pytest.fixture
def clear_gov():
    saved = ui_app._GOV_EVENTS[:]
    ui_app._GOV_EVENTS[:] = []
    yield
    ui_app._GOV_EVENTS[:] = saved


def test_ui_governor_disabled_when_no_events(clear_gov):
    out = ui_app.fmt_governor("zh")
    assert "未启用" in out
    # A concise status, not a long static "what it would do" essay: the
    # actionable hints already live on the metric cards (see feedback #3).
    assert "如果启用" not in out
    assert "\n" not in out.strip()


def test_ingest_gov_event_then_render(clear_gov):
    ui_app.ingest_gov_event("governor_action",
                            {"kind": "set_ctx", "reason": "tok/s low"})
    ui_app.ingest_gov_event("governor_alert",
                            {"reason": "swap cap exceeded"})
    out = ui_app.fmt_governor("zh")
    assert "自动调优" in out
    assert "tok/s low" in out
    assert "swap cap exceeded" in out


def test_ingest_gov_event_maps_action_kind_and_reason(clear_gov):
    # §4 P4 — drain_events routes governor_* events to ingest_gov_event. Since
    # drain_events is a closure inside make_ui (unreachable without launching the
    # UI), we test the exact hook it calls for the governor branch. A
    # governor_action event must map kind=set_ctx and carry the reason.
    ui_app.ingest_gov_event("governor_action",
                            {"kind": "set_ctx", "reason": "low tokps",
                             "payload": {}})
    assert len(ui_app._GOV_EVENTS) == 1
    ev = ui_app._GOV_EVENTS[0]
    assert ev["kind"] == "set_ctx"
    assert ev["reason"] == "low tokps"


def test_orchestrator_emits_governor_action_on_observe():
    # Build a minimal stand-in for Orchestrator and bind the real _observe.
    import screwshell.core.orchestrator as O

    captured = []

    class FakeGov:
        def observe(self, m):
            return [GovernorAction(kind="set_ctx",
                                   reason="tok/s low",
                                   payload={"ctx": 123})]

    orch = types.SimpleNamespace()
    orch.governor = FakeGov()
    orch._recent = []
    orch._recent_window = 10
    orch._ctx_tokens = 4096
    orch._thinking_on = False
    orch._vram_pct_warned = False
    orch.lifecycle = None
    orch.on_event = lambda k, d: captured.append((k, d))
    orch._vram_pct = lambda: 50.0
    orch._observe = O.Orchestrator._observe.__get__(orch)

    stats = types.SimpleNamespace(tokens_per_s=25.0)
    orch._observe(stats, "answer text")

    kinds = {k for k, _ in captured}
    # D1: unified governor_action MUST be emitted (in addition to governor_ctx)
    assert "governor_action" in kinds
    assert "governor_ctx" in kinds
    action = next(d for k, d in captured if k == "governor_action")
    assert action["kind"] == "set_ctx"
    assert action["reason"] == "tok/s low"
