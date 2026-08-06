"""P0 — thresholds centralized (BUILD_OBSERVATORY_V3 §2.5).

Covers: judge boundaries, action-text pairing, prompt-length warn, health
score tiers, and i18n key completeness (every threshold action must exist in
both zh/en so the UI never KeyError on a ⚠️).
"""
from __future__ import annotations

import pytest

from screwshell.ui import thresholds as thr
from screwshell.ui import app as ui_app


def test_judge_ttft_boundaries():
    assert thr.judge("ttft_ms", 4999) is True
    assert thr.judge("ttft_ms", 5000) is False
    assert thr.judge("ttft_ms", None) is True  # fail-open on missing


def test_judge_tps_boundaries():
    assert thr.judge("decode_tps", 19.9) is False
    assert thr.judge("decode_tps", 20.0) is True
    assert thr.judge("decode_tps", 25.9) is True  # the old mis-flagged value


def test_judge_kv_boundaries():
    assert thr.judge("kv_hit", 0.79) is False
    assert thr.judge("kv_hit", 0.80) is True


def test_judge_switch_boundaries():
    assert thr.judge("switch_ms", 1000) is False
    assert thr.judge("switch_ms", 999) is True


def test_prompt_long_warn_at_20000_is_p0_snapshot():
    spec = thr.OBS_THRESHOLDS["prompt_tokens"]
    assert spec["warn_at"] == 20000
    assert thr.is_prompt_long(20001) is True
    assert thr.is_prompt_long(20000) is False
    # prompt_tokens has no pass/fail judge (informational)
    assert "judge" not in spec


def test_every_threshold_has_action_key():
    for metric, spec in thr.OBS_THRESHOLDS.items():
        assert "action_key" in spec, f"{metric} missing action_key"
        assert spec["action_key"], f"{metric} empty action_key"
        assert "warn_key" in spec, f"{metric} missing warn_key"


def test_health_score_tiers():
    # all healthy -> ok (session p95 well under threshold, sufficient sample)
    ok = thr.health_score({"ok_rate": 1.0, "ttft_p95": 1000, "count": 20,
                           "avg_ttft_ms": 1000, "low_confidence": False,
                           "kv_hit_rate": 0.9})
    assert ok == ("ok", [])
    # session p95 slow (>=5s) -> warn (yellow), ttft_ms flagged
    warn = thr.health_score({"ok_rate": 1.0, "ttft_p95": 8000, "count": 20,
                             "avg_ttft_ms": 8000, "low_confidence": False,
                             "kv_hit_rate": 0.9})
    assert warn[0] == "warn" and "ttft_ms" in warn[1]
    # success critically low -> alert (red)
    alert = thr.health_score({"ok_rate": 0.7, "ttft_p95": 1000, "count": 20,
                              "avg_ttft_ms": 1000, "low_confidence": False,
                              "kv_hit_rate": 0.9})
    assert alert[0] == "alert"
    # extreme session p95 -> alert even with ok rate
    alert2 = thr.health_score({"ok_rate": 1.0, "ttft_p95": 25000, "count": 20,
                               "avg_ttft_ms": 25000, "low_confidence": False,
                               "kv_hit_rate": 0.9})
    assert alert2[0] == "alert"


def test_health_score_low_confidence_does_not_alarm_on_ttft():
    # A tiny session (low_confidence) with a single huge TTFT must NOT raise a
    # TTFT alert — we show raw values but refuse to sound the alarm (T4).
    s = {"ok_rate": 1.0, "ttft_p95": 9000, "count": 1,
         "avg_ttft_ms": 9000, "low_confidence": True, "kv_hit_rate": 0.9}
    level, which = thr.health_score(s)
    assert "ttft_ms" not in which
    assert level == "ok"  # nothing else failing


def test_health_score_legacy_mean_fallback_red_only():
    # No p95 supplied at all (older global caller): only escalate to red on a
    # catastrophically high mean, and never add ttft_ms to `which`.
    s = {"ok_rate": 1.0, "avg_ttft_ms": 25000, "kv_hit_rate": 0.9}
    level, which = thr.health_score(s)
    assert level == "alert"
    assert "ttft_ms" not in which  # don't cry wolf on a single global mean


def test_i18n_keys_present_both_langs():
    for metric, spec in thr.OBS_THRESHOLDS.items():
        for key in (spec["warn_key"], spec["action_key"]):
            assert key in ui_app.I18N["zh"], f"{key} missing in zh"
            assert key in ui_app.I18N["en"], f"{key} missing in en"
