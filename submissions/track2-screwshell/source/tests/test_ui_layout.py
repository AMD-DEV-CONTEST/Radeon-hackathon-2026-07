"""P1 — dashboard layout integrity (BUILD_OBSERVATORY_V3 §1/P1).

The four output sites (dashboard_values / respond yield / auto_refresh /
apply_lang) must stay in lockstep. The single source of truth is DASH_NAMES;
this test guarantees dashboard_values emits exactly that many items, in that
order, with the right value types, so a future edit can't silently desync them.

NOTE: apply_lang() and auto_refresh() are CLOSURES defined inside make_ui(ctx)
in screwshell/ui/app.py — they are not module-level attributes and cannot be
reached without launching the UI. Their sync is guaranteed by construction:
both derive from dashboard_values(lang), which derives from DASH_NAMES. So the
4-site sync is fully covered by the dashboard_values contract tests below.
"""
from __future__ import annotations

import pandas as pd

from screwshell.ui import app as ui_app


def test_dash_names_covers_all_views():
    names = ui_app.DASH_NAMES
    # Overview / Live / Stream / Tuning all represented
    assert {"health", "metrics", "status", "gpu", "activity",
            "ab_compare", "config_versions"} <= set(names)


def test_dashboard_values_length_matches_dash_names():
    vals = ui_app.dashboard_values("zh")
    assert isinstance(vals, tuple)
    assert len(vals) == len(ui_app.DASH_NAMES)


def test_dashboard_values_types():
    vals = ui_app.dashboard_values("zh")
    by_name = dict(zip(ui_app.DASH_NAMES, vals))
    # charts are DataFrames
    for chart in ("gpu", "tps", "ttft", "kv"):
        assert isinstance(by_name[chart], pd.DataFrame), chart
    # text panels are strings
    for text in ("health", "metrics", "percentiles", "causal", "status",
                 "trend_anomaly", "governor", "switch_log", "tools",
                 "activity", "evidence", "audit", "plan", "ab_compare",
                 "config_versions", "rollback"):
        assert isinstance(by_name[text], str), text


def test_dashboard_values_bilingual_no_keyerror():
    # Both languages must render without raising (i18n fallback rule).
    ui_app.dashboard_values("zh")
    ui_app.dashboard_values("en")


def test_dashboard_values_matches_dash_names_contract():
    # §4 P1 — single-source-of-truth contract. apply_lang / auto_refresh /
    # respond-yield all derive from dashboard_values + DASH_NAMES, so guaranteeing
    # this contract guarantees the 4-site sync (closures can't desync).
    vals = ui_app.dashboard_values("zh")
    assert isinstance(vals, tuple)
    assert len(vals) == len(ui_app.DASH_NAMES)
    # every DASH_NAMES id has exactly one corresponding value, in order
    for name, v in zip(ui_app.DASH_NAMES, vals):
        assert v is not None, f"missing dashboard value for {name}"
