"""ScrewShell UI — pure computation functions (gradio/pandas-free).

Wave 1 of the observatory-v3 plan: pure functions extracted from
``screwshell/ui/app.py`` so they can be unit-tested WITHOUT importing gradio
or pandas. These functions carry NO i18n and NO module-global state — they are
strictly pure (data in, data out).

Honest-output invariants (preserved from app.py):
  * never fabricate a measurement (metrics.py iron rule);
  * A/B verdicts only render above the minimum sample size (T4 discipline);
  * differences are labelled "with confounders, not causal proof".
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Optional


# Canonical dimensions for the refactored drill-down + time design.
# The business hierarchy is a STRICT parent-child:
#   operational_session_id (operation session, parent)
#     -> request_id (single call, child)
# run_id crosses sessions and is therefore NOT a clean tree, so it is excluded.
# All other flat attributes (entry/adapter/ok/stream/switched/route) are
# dropped from the canonical set. `time` is the independent continuous
# dimension (always the windowing / x-axis basis).
#
# Field mapping (internal): "session" -> "operational_session_id",
# "request" -> "request_id".
DIM_FIELDS = {"session": "operational_session_id", "request": "request_id"}
DIMENSIONS = frozenset({"session", "request", "time"})
CATEGORICAL_DIMENSIONS = frozenset(d for d in DIMENSIONS if d != "time")

# Label-less grouping key for events that lack an operational_session_id.
NO_SESSION = "(no-session)"


def slice_events(events: list[dict], dim: str) -> dict[str, list[dict]]:
    """Pure grouping of events by a categorical dimension.

    Sorts by ``ts`` first, then buckets events by the value of ``dim``.
    ``None``/empty values fall into the ``"unknown"`` bucket (never dropped).
    For ``dim == "entry"`` the bucket is DERIVED from ``run_id`` presence
    (mirror event.py:95-98: ``"ui"`` if run_id truthy else ``"api"``) — the
    stored ``entry`` field is NEVER read (dict events may lack it).

    Only called with the 9 categorical dims (never ``time``), so no time
    branch is needed. gradio/pandas-free; carries NO i18n.
    """
    evs = [e for e in (events or []) if isinstance(e, dict)]
    evs = sorted(evs, key=lambda e: e.get("ts") or 0)
    out: dict[str, list[dict]] = {}
    for e in evs:
        if dim == "entry":
            key = "ui" if e.get("run_id") else "api"
        else:
            val = e.get(dim)
            key = "unknown" if (val is None or val == "") else str(val)
        out.setdefault(key, []).append(e)
    return out


def session_request_hierarchy(events: list[dict]) -> dict[str, list[dict]]:
    """Strict parent-child drill source: operation session -> requests.

    Groups events by ``operational_session_id`` (or ``NO_SESSION`` when the
    field is absent), each bucket sorted by ``ts``. Events that carry a
    ``request_id`` belong to exactly one session; the tree is strict because
    every request_id is observed to belong to a single operational_session_id
    in real relay data. gradio/pandas-free; carries NO i18n.
    """
    evs = [e for e in (events or []) if isinstance(e, dict)]
    evs = sorted(evs, key=lambda e: e.get("ts") or 0)
    out: dict[str, list[dict]] = {}
    for e in evs:
        key = e.get("operational_session_id")
        key = NO_SESSION if (key is None or key == "") else str(key)
        out.setdefault(key, []).append(e)
    return out


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (matches numpy default). q in [0,100]."""
    if not values:
        return float("nan")
    vs = sorted(values)
    if len(vs) == 1:
        return vs[0]
    k = (len(vs) - 1) * (q / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(vs) - 1)
    frac = k - lo
    return vs[lo] + (vs[hi] - vs[lo]) * frac


def compute_percentiles(recent: list[dict]) -> dict:
    """p50/p95/p99 of TTFT from recent request events.

    Returns {"n", "p50", "p95", "p99"} with None when there is no data. Never
    fabricates a measurement (metrics.py iron rule). p99 added 2026-08-05 for
    session-scoped health judgment (§5.3); existing p50/p95 semantics unchanged.
    """
    vals = [e["ttft_ms"] for e in recent
            if isinstance(e.get("ttft_ms"), (int, float))]
    if not vals:
        return {"n": 0, "p50": None, "p95": None, "p99": None}
    return {"n": len(vals),
            "p50": percentile(vals, 50),
            "p95": percentile(vals, 95),
            "p99": percentile(vals, 99)}


def _mean(vals) -> Optional[float]:
    vals = [v for v in vals if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else None


def split_ab_windows(events: list[dict], mode: str = "half",
                      window_min: float = 10.0):
    """Split recent events into two windows A (before) / B (after).

    Return-shape rule (backward-compat): the legacy/direct-call modes
    ``"half"`` / ``"run"`` / ``"minutes"`` return the 2-tuple ``(a, b)``.
    A categorical DIMENSIONS dim returns the 3-tuple ``(a, b, split_kind)``
    where ``split_kind`` is ``"ok"`` or ``"single_value"``.

    Modes:
      * "half"   — sort by ts, first half = A, second half = B (2-tuple).
      * "run"    — split at the last run_id change boundary (2-tuple);
                    now generalized as the ``run_id`` categorical dim.
      * "minutes"— A = events in [now-2w, now-w), B = events in [now-w, now)
                    (2-tuple, honors window_min).
      * "time"   — same as "minutes" windowing semantics (honors window_min),
                    NOT a 50/50 half split (2-tuple).
      * any other categorical DIMENSIONS dim — split at the LAST boundary
                    change of that dim's value (generalizes the run mode);
                    if the dim has <2 distinct non-``unknown`` values, returns
                    ``([], [], "single_value")`` (explicit, NOT a silent
                    fallback to half).
    Pure function; tested without a server.
    """
    evs = [e for e in (events or []) if isinstance(e, dict)]
    categorical = mode in CATEGORICAL_DIMENSIONS
    if not evs:
        # empty = no distinct values -> single_value (3-tuple) for any
        # categorical/boundary mode; 2-tuple for legacy/time/half modes
        # (backward-compat).
        if mode in ("half", "run", "minutes", "time"):
            return [], []
        return [], [], "single_value"
    evs = sorted(evs, key=lambda e: e.get("ts") or 0)
    if mode == "minutes" or mode == "time":
        now = time.time()
        w = max(0.1, window_min) * 60.0
        b = [e for e in evs if (now - w) <= (e.get("ts") or 0) <= now]
        a = [e for e in evs if (now - 2 * w) <= (e.get("ts") or 0) < (now - w)]
        return a, b
    if mode == "run":
        # legacy run mode -> 2-tuple (test_ab_windows.py destructures 2 values).
        # find last index where run_id changes
        split = 0
        for i in range(1, len(evs)):
            if evs[i].get("run_id") and evs[i].get("run_id") != evs[i-1].get("run_id"):
                split = i
        if split == 0:  # no run change -> fall back to half
            mid = len(evs) // 2
            return evs[:mid], evs[mid:]
        return evs[:split], evs[split:]
    if mode == "half":
        mid = len(evs) // 2
        return evs[:mid], evs[mid:]
    # Categorical DIMENSIONS dim (incl. run_id): split at the last boundary
    # change of `mode`, returning the 3-tuple (a, b, split_kind).
    buckets = slice_events(evs, mode)
    distinct = [k for k in buckets if k != "unknown"]
    if len(distinct) < 2:
        # cannot split meaningfully
        return [], [], "single_value"
    # walk chronologically; split at the last boundary change of the value
    split = 0
    prev = _bucket_of(evs[0], mode)
    for i in range(1, len(evs)):
        cur = _bucket_of(evs[i], mode)
        if cur != prev:
            split = i
            prev = cur
    if split == 0:  # no boundary change -> fall back to half (still "ok")
        mid = len(evs) // 2
        return evs[:mid], evs[mid:], "ok"
    return evs[:split], evs[split:], "ok"


def _bucket_of(e: dict, dim: str) -> str:
    """Internal: bucket key for an event under ``dim`` (mirror slice_events)."""
    if dim == "entry":
        return "ui" if e.get("run_id") else "api"
    val = e.get(dim)
    return "unknown" if (val is None or val == "") else str(val)


def sample_count_ok(n: int, min_n: int = 16) -> bool:
    """T4 discipline: do not call a verdict below the minimum sample size."""
    return isinstance(n, int) and n >= min_n


def compare_windows(a: list[dict], b: list[dict],
                    main_metric: str = "ttft_ms", split_kind: str = "ok") -> dict:
    """Compare two windows on TTFT (primary, D4) + guardrails.

    ``split_kind`` defaults to ``"ok"`` so legacy callers passing only
    ``(a, b, main_metric=...)`` keep working. A ``"single_value"`` split
    (categorical dim with <2 distinct values) is reported honestly: it
    returns early with ``verdict="single_value"`` and ``ok=False`` (NOT a
    fabricated verdict).

    Honest output: only renders a verdict when BOTH windows meet the minimum
    sample size. Otherwise flags "sample too small". Difference is labelled
    "with confounders, not causal proof" (TTFT_BREAKDOWN_REPORT iron rule).
    """
    metrics = {
        "ttft_ms": "ab_metric_ttft",
        "avg_decode_tps": "ab_metric_tps",
        "kv_hit_rate": "ab_metric_kv",
        "ok_rate": "ab_metric_ok",
    }
    out = {"na": len(a), "nb": len(b), "main": main_metric,
           "means": {}, "verdict": None, "ok": False, "split_kind": split_kind}
    for m in metrics:
        out["means"][m] = (_mean([e.get(m) for e in a]),
                            _mean([e.get(m) for e in b]))
    if split_kind == "single_value":
        out["verdict"] = "single_value"
        return out
    if not (sample_count_ok(len(a)) and sample_count_ok(len(b))):
        out["verdict"] = "sample_low"
        return out
    out["ok"] = True
    ma, mb = out["means"][main_metric]
    if ma is None or mb is None:
        out["verdict"] = "sample_low"
        return out
    if mb < ma * 0.95:
        out["verdict"] = "b"
    elif mb > ma * 1.05:
        out["verdict"] = "a"
    else:
        out["verdict"] = "tie"
    return out


def run_ab_split(events: list[dict], dim: str,
                 window_min: float = 10.0) -> dict:
    """Module-level A/B seam — unit-testable without launching gradio.

    Branches on ``dim`` type internally:
      * categorical DIMENSIONS dim -> unpack the 3-tuple
        ``(a, b, split_kind) = split_ab_windows(...)`` and forward
        ``split_kind`` into ``compare_windows``;
      * ``"time"`` -> unpack the 2-tuple ``(a, b) = split_ab_windows(...)``
        (minutes windowing) and call ``compare_windows(a, b)`` (defaults
        ``split_kind="ok"``).

    Returns the ``_AB_RESULT`` dict (na/nb/means/verdict/ok/split_kind).
    """
    if dim == "time":
        a, b = split_ab_windows(events, mode="time", window_min=window_min)
        return compare_windows(a, b)
    a, b, split_kind = split_ab_windows(events, mode=dim, window_min=window_min)
    return compare_windows(a, b, split_kind=split_kind)


def _normalize_settings(props: dict) -> dict:
    """Extract comparable, restart-relevant settings from llama-server /props.

    /props shape varies across llama.cpp builds; we read the well-known keys
    and ignore the rest, so a missing key degrades to absent (never fabricated).
    """
    out = {}
    dgs = props.get("default_generation_settings") if isinstance(props, dict) else None
    if isinstance(dgs, dict):
        for k in ("n_ctx", "n_gpu_layers", "n_batch", "flash_attn",
                  "cache_type_k", "cache_type_v", "model", "seed"):
            if k in dgs:
                out[k] = dgs[k]
    for k in ("model_path", "n_ctx", "n_gpu_layers"):
        if k in props:
            out.setdefault(k, props[k])
    return out


# Restart-time flags: changing these requires a llama-server restart.
# Everything else (e.g. seed) is a hot-update flag.
_RESTART_FLAGS = frozenset({
    "n_ctx", "n_gpu_layers", "n_batch", "flash_attn",
    "cache_type_k", "cache_type_v", "model", "model_path",
})

# Display label for each effective mode.
_EFFECTIVE_LABELS = {"hot": "hot", "restart": "restart"}


def _effective_mode(name: str) -> str:
    """§2.9 T9/D3 — label a setting as hot-update or restart-time."""
    return "restart" if name in _RESTART_FLAGS else "hot"


def build_config_snapshot(props: dict, ts: float) -> dict:
    """Build an immutable, versioned snapshot from a /props reading.

    The version id is a stable hash of the normalized settings, so identical
    configs collapse to the same id (no version spam). Each setting is also
    annotated with whether it is a hot-update ("hot") or restart-time
    ("restart") flag (§2.9 T9). Returns a dict ready to be diffed / rolled back.
    """
    settings = _normalize_settings(props)
    vid_src = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    vid = f"v{hashlib.md5(vid_src.encode()).hexdigest()[:5]}"
    effective = {name: _effective_mode(name) for name in settings}
    return {"vid": vid, "ts": ts, "settings": settings,
            "effective": effective,
            "raw_keys": sorted(props.keys()) if isinstance(props, dict) else []}


def rollback_command(snapshot: dict) -> str:
    """§2.9 / T10 — return a copy-paste rollback command, NOT auto-execute.

    Most of these settings are restart-time flags (--flash-attn, --cache-type,
    ctx), so the command is a suggested llama-server launch with the old flags.
    NOTE: n_ctx / n_gpu_layers / flash_attn / cache_type_k / cache_type_v all
    require a llama-server restart to take effect (see _RESTART_FLAGS).
    """
    s = snapshot.get("settings", {})
    flags = []
    if "n_ctx" in s:
        flags.append(f"--ctx-size {s['n_ctx']}")
    if "n_gpu_layers" in s:
        flags.append(f"--n-gpu-layers {s['n_gpu_layers']}")
    if s.get("flash_attn"):
        flags.append("--flash-attn")
    if s.get("cache_type_k"):
        flags.append(f"--cache-type-k {s['cache_type_k']}")
    if s.get("cache_type_v"):
        flags.append(f"--cache-type-v {s['cache_type_v']}")
    model = s.get("model") or s.get("model_path") or "/path/to/model"
    flag_str = " ".join(flags) if flags else "<no restart-time flags changed>"
    return (f"# rollback to {snapshot.get('vid')}\n"
            f"python -m screwshell.gateway.relay --base {model} {flag_str}")
