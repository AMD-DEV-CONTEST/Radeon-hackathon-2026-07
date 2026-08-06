"""i18n completeness for the refactored drill-down + time A/B design.

This test FAILS if any expected key is missing from either the zh or en i18n
dict — it does NOT rely on the silent ``T()`` fallback masking a miss. Every
key used by the session->request drill-down and the time-window A/B tab must
exist in BOTH languages.
"""
from __future__ import annotations

from screwshell.ui.app import I18N


# Drill-down keys (方向 B: session -> request cascading drill).
DRILL_KEYS = [
    "drill_empty",
    "drill_all_sessions",
    "drill_session",
    "drill_request",
    "drill_no_session",
    "drill_n_requests",
    "drill_sample_low",
    "drill_ok",
    "drill_fail",
    "drill_req_id",
    "drill_run_id",
]

# Time-only A/B keys.
AB_KEYS = [
    "ab_single_value",
    "ab_time_label",
]

EXPECTED_KEYS = DRILL_KEYS + AB_KEYS


def test_i18n_completeness_both_languages():
    """Every expected drill-down / time-A/B key must exist in BOTH zh and en."""
    for lang in ("zh", "en"):
        assert lang in I18N, f"missing language dict: {lang}"
        for key in EXPECTED_KEYS:
            assert key in I18N[lang], f"[{lang}] missing i18n key: {key}"


def test_i18n_no_flat_dim_keys_remain():
    """The flat dimension keys (run_id/entry/adapter/ok/stream/switched/route
    and the global/breakdown dim keys) were removed by the refactor."""
    removed = {
        "dash_dim", "dash_dim_global", "dash_dim_label",
        "dash_dim_unknown", "dash_dim_sample_low", "dash_dim_none",
        "dash_dim_run_id", "dash_dim_request_id",
        "dash_dim_operational_session_id", "dash_dim_entry",
        "dash_dim_adapter", "dash_dim_ok", "dash_dim_stream",
        "dash_dim_switched", "dash_dim_route",
        "ab_dim_label",
        "ab_dim_run_id", "ab_dim_request_id",
        "ab_dim_operational_session_id", "ab_dim_entry", "ab_dim_adapter",
        "ab_dim_ok", "ab_dim_stream", "ab_dim_switched", "ab_dim_route",
    }
    for lang in ("zh", "en"):
        for key in removed:
            assert key not in I18N[lang], f"[{lang}] stale key still present: {key}"
