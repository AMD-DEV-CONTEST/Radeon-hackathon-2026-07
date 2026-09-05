"""Smoke test — the V3 UI builds without a server (gradio Blocks construct
lazily, no launch). Catches wiring/attribute errors that only surface at build
time (e.g. a desynced output list or a bad component type) without needing a
model or a relay.
"""
from __future__ import annotations

import types

from screwshell.ui import app as ui_app


class _FakeAudit:
    def tail(self, n):
        return []


class _FakeEvidence:
    def context_block(self, limit=8):
        return ""


def _fake_ctx():
    orch = types.SimpleNamespace()
    return types.SimpleNamespace(
        orchestrator=orch,
        gate=types.SimpleNamespace(audit=_FakeAudit()),
        evidence=_FakeEvidence(),
    )


def test_make_ui_builds():
    ctx = _fake_ctx()
    demo = ui_app.make_ui(ctx)
    assert demo is not None
    # the orchestrator on_event was wired by make_ui
    assert callable(ctx.orchestrator.on_event)


def test_dash_names_grouped_into_four_views():
    # §4 P1 — the built UI has 4 tabs (Overview / Live / Stream / Tuning).
    # Asserting gr.Tab counts directly is fragile across gradio versions, so we
    # verify DASH_NAMES partitions into the 4 contiguous view groups that the 4
    # tabs render (matching make_ui's component map).
    names = ui_app.DASH_NAMES
    assert len(names) == 22  # 4 + 7 + 6 + 5 (Tuning gained tune_progress/tune_status)
    assert names[0:4] == ["health", "metrics", "percentiles", "causal"]
    assert names[4:11] == ["status", "gpu", "tps", "ttft", "kv",
                             "trend_anomaly", "governor"]
    assert names[11:17] == ["switch_log", "tools", "activity",
                             "evidence", "audit", "plan"]
    assert names[17:22] == ["ab_compare", "config_versions", "rollback",
                             "tune_progress", "tune_status"]
    # no gaps / overlaps
    assert len(set(names)) == len(names)
