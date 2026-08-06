"""Centralized observability thresholds + health-score logic for the UI.

The V3 observatory renders numbers only through this module. Every metric the
dashboard shows is *judged* here, never inline in ``app.py``. A metric may only
be rendered if its declaration carries both a ``judge`` (pass/fail lambda) and
an ``action_key`` (the i18n key of the "what to do about it" line shown under a
⚠️). That pairing is what keeps the UI honest: a warning is meaningless without
a next action, and a threshold is meaningless if it is scattered across three
functions (the V2 bug that once mis-flagged a healthy 25.9 tok/s).

Section 2.7 status semantics are enforced here:
  * ⚠️ ("需关注") MUST be paired with an ``action`` line.
  * ✓ ("健康") carries no action line.
  * Direction is documented once per metric ("higher"/"lower" better).
"""
from __future__ import annotations

# Threshold declaration. ``judge`` returns True when the metric is HEALTHY, so
# a warning fires when it returns False. ``warn_key`` / ``action_key`` are i18n
# keys looked up in ``ui/app.py``'s I18N dictionary (bilingual). ``prompt_tokens``
# has no ``judge`` — it is an informational length warning, not a pass/fail
# health metric.
#
# P0 snapshot: prompt_tokens warn_at=20000 is a placeholder. P4 (T17) upgrades
# it to "near 90% of ctx" by reading the real n_ctx; changing that value is a
# one-line edit here, never a hunt through app.py.
OBS_THRESHOLDS: dict[str, dict] = {
    "ttft_ms": {
        "judge": lambda v: v < 5000,
        "direction": "lower",
        "warn_key": "thr_ttft_warn",
        "action_key": "thr_ttft_action",
    },
    "decode_tps": {
        "judge": lambda v: v >= 20,
        "direction": "higher",
        "warn_key": "thr_tps_warn",
        "action_key": "thr_tps_action",
    },
    "kv_hit": {
        "judge": lambda v: v >= 0.8,
        "direction": "higher",
        "warn_key": "thr_kv_warn",
        "action_key": "thr_kv_action",
    },
    "ok_rate": {
        "judge": lambda v: v >= 0.95,
        "direction": "higher",
        "warn_key": "thr_ok_warn",
        "action_key": "thr_ok_action",
    },
    "switch_ms": {
        "judge": lambda v: v < 1000,
        "direction": "lower",
        "warn_key": "thr_switch_warn",
        "action_key": "thr_switch_action",
    },
    "prompt_tokens": {
        "warn_at": 20000,
        "direction": "lower",
        "warn_key": "thr_prompt_warn",
        "action_key": "thr_prompt_action",
    },
}

# Health-score inputs: the top-level 正常/需关注/异常 banner is synthesized from
# exactly these three metrics (§2.10, T15 two-tier).
HEALTH_METRICS = ["ok_rate", "ttft_ms", "kv_hit"]


def judge(metric: str, value) -> bool:
    """Return True if ``value`` is healthy for ``metric`` (warn should NOT fire).

    Missing threshold, missing value, or a thrown judge all degrade to "healthy"
    (fail-open) so the UI never fabricates a red state from a bad reading.
    """
    spec = OBS_THRESHOLDS.get(metric)
    if spec is None or "judge" not in spec or value is None:
        return True
    try:
        return bool(spec["judge"](value))
    except Exception:
        return True


def is_prompt_long(prompt_tokens) -> bool:
    """Informational length warning — not part of the health score."""
    spec = OBS_THRESHOLDS.get("prompt_tokens", {})
    warn_at = spec.get("warn_at")
    return (isinstance(prompt_tokens, (int, float))
            and warn_at is not None
            and prompt_tokens > warn_at)


def health_score(summary: dict) -> tuple[str, list[str]]:
    """Two-tier health banner: 正常(ok) / 需关注(warn, 黄) / 异常(alert, 红).

    Session-scoped (§5.3): the banner judges the TTFT **p95** of the CURRENT
    operational session (the relay returns a session-filtered summary carrying
    ``ttft_p95`` / ``ttft_p50`` / ``low_confidence``), NOT the legacy global
    arithmetic mean (``avg_ttft_ms``). A single historical outlier — e.g. an
    August-4 stress run with 50k-token, 170–220s prefill requests — can no
    longer pin the banner red, because it lives in a different (benchmark)
    session and is excluded from the interactive health aggregation.

    Small-sample discipline (T4): when ``low_confidence`` is True (the scoped
    window has too few TTFT samples, < 8) we do NOT sound the TTFT alarm — we
    leave the raw p95 visible but refrain from a red/yellow TTFT verdict, so a
    1-request session never fabricates a false p99 alert.

    Returns ``(level, which)`` where ``level`` is one of
    ``"ok"``/``"warn"``/``"alert"`` and ``which`` lists the failing metric keys
    (so the banner can tell the user "看哪个卡"). A metric is only counted as
    failing when its reading is present AND trustworthy.
    """
    which: list[str] = []
    ok_rate = summary.get("ok_rate")
    if isinstance(ok_rate, (int, float)) and not judge("ok_rate", ok_rate):
        which.append("ok_rate")

    # TTFT: prefer session p95; fall back to the legacy mean only when the
    # caller did not supply a percentiled summary (older global callers).
    low_conf = bool(summary.get("low_confidence"))
    ttft_p95 = summary.get("ttft_p95")
    has_p95 = isinstance(ttft_p95, (int, float))
    # The TTFT alarm fires only on a trustworthy (sufficient-sample) p95.
    if has_p95 and not low_conf:
        if not judge("ttft_ms", ttft_p95):
            which.append("ttft_ms")
        ttft_alarm_value = ttft_p95
        ttft_alarm_confident = True
    else:
        # No/low-confidence p95: fall back to the global mean for a red-only
        # guard (never yellow on a single sample), and do not add ttft_ms to
        # `which` so we don't cry wolf on a tiny window.
        avg = summary.get("avg_ttft_ms")
        ttft_alarm_value = avg if isinstance(avg, (int, float)) else None
        ttft_alarm_confident = False

    if not judge("kv_hit", summary.get("kv_hit_rate")):
        which.append("kv_hit")

    # Red tier is decided FIRST so a catastrophic legacy mean (no session
    # window supplied at all) still escalates to alert even when TTFT was not
    # added to `which` (we deliberately avoid a yellow "ttft_ms" verdict on a
    # low-confidence / single-sample window — but red on a 20s+ mean is safe).
    red = False
    if isinstance(ok_rate, (int, float)) and ok_rate < 0.8:
        red = True
    if ttft_alarm_value is not None and ttft_alarm_value >= 20000:
        # Escalate to red on a confident p95, OR on the legacy global mean when
        # no session window was supplied at all (full-ring, not low_conf).
        if ttft_alarm_confident or (not has_p95 and not low_conf):
            red = True

    if not which:
        # Nothing per-metric failed, but a red-tier condition (e.g. legacy mean
        # fallback) may still apply.
        return ("alert", which) if red else ("ok", [])
    if red:
        return ("alert", which)
    return ("warn", which)


def warn_key(metric: str) -> str:
    return OBS_THRESHOLDS.get(metric, {}).get("warn_key", "")


def action_key(metric: str) -> str:
    return OBS_THRESHOLDS.get(metric, {}).get("action_key", "")
