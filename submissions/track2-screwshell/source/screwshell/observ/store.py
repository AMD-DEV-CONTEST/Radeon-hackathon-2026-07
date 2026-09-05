"""Thread-safe persistence for ``RequestEvent`` (JSONL + SQLite).

Opt-in by environment variable only:

    OBSERV_DIR=/path/to/dir   # JSONL + SQLite land here; dir is created

If ``OBSERV_DIR`` is unset (or the dir cannot be created / opened), the store
degrades to a **no-op**: ``record_event`` silently drops events, ``recent`` /
``summarize`` return empty. This keeps import side-effect-free on dev boxes
and in the offline test suite -- nothing is written unless an operator
explicitly opts in (the relay launcher sets ``OBSERV_DIR`` in production).

v1 does NOT use OpenLIT / OTel / Grafana (Layer2_Implementation_Map.md §5).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from .event import RequestEvent

log = logging.getLogger("screwshell.observ")

_COLS = [
    "ts", "request_id", "run_id", "route", "adapter", "switched", "stream",
    "model", "thinking", "prompt_tokens", "cached_tokens", "completion_tokens",
    "ttft_ms", "prefill_ms", "decode_ms", "decode_tps", "kv_hit_rate",
    "thinking_ms", "switch_ms", "queue_wait_ms", "ok", "error", "status_code",
    # session-scoped observability (2026-08-05): operational session id + boundary
    # signal. bools stored as REAL 0/1 (see _sql_val).
    "operational_session_id", "boundary_reason", "cache_signal_valid",
    "benchmark",
]
_MAX_RECENT = 200

# GPU telemetry samples (rocm-smi --json parsed) — persisted so the UI chart
# survives a relay / UI restart (R3). The relay's background sampler records
# one row every ~2s; the in-memory ring backs the hot read path and the SQLite
# table is the cold-start / restart recovery source.
_GPU_COLS = ["ts", "card", "use_pct", "vram_used_b", "vram_total_b",
             "temp_c", "power_w"]
_GPU_RING_MAX = 1800   # 1h @ 2s


class ObservStore:
    def __init__(self, directory: Optional[str] = None):
        self._lock = threading.Lock()
        self._recent: list[dict] = []
        self._gpu_recent: list[dict] = []
        self._jsonl: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        self.enabled = False
        if directory:
            self._open(Path(directory))

    # ------------------------------------------------------------------ open
    def _open(self, d: Path) -> None:
        try:
            d.mkdir(parents=True, exist_ok=True)
            self._jsonl = d / "requests.jsonl"
            self._conn = sqlite3.connect(str(d / "requests.db"),
                                         check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS request_events ("
                + ", ".join(f"{c} TEXT" if c in ("request_id", "run_id", "route",
                                                 "adapter", "model", "error",
                                                 "operational_session_id",
                                                 "boundary_reason")
                            else f"{c} REAL" for c in _COLS)
                + ")")
            self._conn.commit()
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS gpu_samples ("
                + ", ".join(f"{c} TEXT" if c == "card" else f"{c} REAL"
                            for c in _GPU_COLS)
                + ")")
            self._conn.commit()
            # ---- schema migration: older DBs lack columns added after table
            #      creation. CREATE TABLE IF NOT EXISTS never alters an existing
            #      table, so a DB built before a _COLS addition stays missing
            #      that column and every record() INSERT fails silently inside
            #      its best-effort try/except. Diff expected vs actual and add
            #      any missing columns so events persist again. Generic: any
            #      future _COLS addition is auto-migrated, no hardcoding.
            _existing = {r[1] for r in
                         self._conn.execute(
                             "PRAGMA table_info(request_events)")}
            for _c in _COLS:
                if _c not in _existing:
                    _t = ("TEXT" if _c in ("request_id", "run_id", "route",
                                           "adapter", "model", "error",
                                           "operational_session_id",
                                           "boundary_reason")
                          else "REAL")
                    try:
                        self._conn.execute(
                            f"ALTER TABLE request_events ADD COLUMN {_c} {_t}")
                    except Exception:  # noqa: BLE001 - best-effort migration
                        log.warning("schema migration failed for column %s", _c)
            self._conn.commit()
            # seed the in-memory ring from disk so a restart shows history
            try:
                cur = self._conn.execute(
                    "SELECT * FROM request_events ORDER BY ts DESC LIMIT ?",
                    (_MAX_RECENT,))
                cols = [d0[0] for d0 in cur.description]
                for row in reversed(cur.fetchall()):
                    self._recent.append(dict(zip(cols, row)))
            except Exception:  # noqa: BLE001 - empty/new table is fine
                pass
            # seed the GPU ring from disk so a restart shows history
            try:
                cur = self._conn.execute(
                    "SELECT * FROM gpu_samples ORDER BY ts DESC LIMIT ?",
                    (_GPU_RING_MAX,))
                cols = [d0[0] for d0 in cur.description]
                for row in reversed(cur.fetchall()):
                    self._gpu_recent.append(dict(zip(cols, row)))
            except Exception:  # noqa: BLE001 - empty/new table is fine
                pass
            self.enabled = True
            log.info("observ store enabled at %s (%d events loaded)",
                     d, len(self._recent))
        except Exception as e:  # noqa: BLE001 - degrade to no-op
            log.warning("observ store disabled (cannot open %s): %s", d, e)
            self.enabled = False

    # ----------------------------------------------------------------- write
    def record(self, ev: RequestEvent) -> None:
        if not self.enabled:
            return
        d = ev.to_dict()
        with self._lock:
            try:
                with open(self._jsonl, "a", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
            except Exception:  # noqa: BLE001 - JSONL is best-effort
                pass
            try:
                # Named columns (not positional) so a schema-migrated table --
                # where ALTER TABLE appended new columns at the END rather than
                # at their _COLS position -- still maps values to the right
                # column. A positional INSERT would silently misalign every
                # value after the first appended column.
                self._conn.execute(
                    "INSERT INTO request_events ("
                    + ",".join(_COLS) + ") VALUES ("
                    + ",".join("?" for _ in _COLS) + ")",
                    tuple(_sql_val(d.get(c), c) for c in _COLS))
                self._conn.commit()
            except Exception:  # noqa: BLE001 - SQLite is best-effort
                pass
            self._recent.append(d)
            if len(self._recent) > _MAX_RECENT:
                del self._recent[0]

    # ------------------------------------------------------------------ read
    def recent(self, n: int = 20) -> list[dict]:
        with self._lock:
            return list(reversed(self._recent[-n:]))

    def _filter(self, evs: list[dict], run_id=None,
                operational_session_id=None, time_window_s=None,
                exclude_benchmark=False) -> list[dict]:
        """Apply optional scope filters shared by recent_filtered/summarize.

        All filters are AND-combined; None means "no constraint" (back-compat).
        """
        if run_id is not None:
            evs = [e for e in evs if e.get("run_id") == run_id]
        if operational_session_id is not None:
            evs = [e for e in evs
                   if e.get("operational_session_id") == operational_session_id]
        if time_window_s is not None:
            cutoff = time.time() - float(time_window_s)
            evs = [e for e in evs if (e.get("ts") or 0) >= cutoff]
        if exclude_benchmark:
            evs = [e for e in evs if not (e.get("benchmark"))]
        return evs

    def recent_filtered(self, n: int = 20, run_id=None,
                        operational_session_id=None, time_window_s=None,
                        exclude_benchmark=False) -> list[dict]:
        """Like ``recent`` but scoped. No filters -> identical to recent(n)."""
        with self._lock:
            evs = list(self._recent)
        evs = self._filter(evs, run_id, operational_session_id,
                           time_window_s, exclude_benchmark)
        return list(reversed(evs[-n:]))

    # ------------------------------------------------------------ gpu samples
    def record_gpu_sample(self, s: dict) -> None:
        """Persist one GPU telemetry sample (rocm-smi --json parsed dict).

        Mirrors ``record``: SQLite + in-memory ring, both best-effort. Silently
        no-ops when the store is disabled (OBSERV_DIR unset) so the relay's
        background sampler never raises.
        """
        if not self.enabled:
            return
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO gpu_samples VALUES ("
                    + ",".join("?" for _ in _GPU_COLS) + ")",
                    tuple(s.get(c) for c in _GPU_COLS))
                self._conn.commit()
            except Exception:  # noqa: BLE001 - SQLite is best-effort
                pass
            self._gpu_recent.append({c: s.get(c) for c in _GPU_COLS})
            if len(self._gpu_recent) > _GPU_RING_MAX:
                del self._gpu_recent[0]

    def recent_gpu(self, n: int = 180) -> list[dict]:
        """GPU samples newest-first. In-memory ring first (hot path); falls back
        to the SQLite table when the ring is empty (cold start / UI restart)."""
        with self._lock:
            if self._gpu_recent:
                return list(reversed(self._gpu_recent[-n:]))
            try:
                cur = self._conn.execute(
                    "SELECT * FROM gpu_samples ORDER BY ts DESC LIMIT ?",
                    (n,))
                cols = [d0[0] for d0 in cur.description]
                return [dict(zip(cols, row)) for row in reversed(cur.fetchall())]
            except Exception:  # noqa: BLE001
                return []

    def summarize(self, run_id=None, operational_session_id=None,
                   time_window_s=None, exclude_benchmark=False) -> dict:
        with self._lock:
            evs = list(self._recent)
        # Scope filters — all optional. No args -> identical to legacy behavior
        # (full ring), so existing callers / tests keep working.
        evs = self._filter(evs, run_id, operational_session_id,
                           time_window_s, exclude_benchmark)
        n = len(evs)
        if n == 0:
            return {"enabled": self.enabled, "count": 0,
                    "by_adapter": {}, "ok_rate": None,
                    "avg_ttft_ms": None, "avg_prefill_ms": None,
                    "avg_decode_ms": None, "avg_decode_tps": None,
                    "kv_hit_rate": None, "avg_queue_wait_ms": None,
                    "avg_switch_ms": None,
                    "total_prompt_tokens": 0, "total_completion_tokens": 0,
                    "errors": [],
                    # session-scoped percentile keys (all None when no data)
                    "ttft_p50": None, "ttft_p95": None, "ttft_p99": None,
                    "boundary_count": 0, "warm_count": 0,
                    "low_confidence": True}
        ok = sum(1 for e in evs if e.get("ok"))
        by_adapter: dict[str, int] = {}
        for e in evs:
            key = e.get("adapter") or "base"
            by_adapter[key] = by_adapter.get(key, 0) + 1

        def _avg(key):
            vals = [e[key] for e in evs if isinstance(e.get(key), (int, float))]
            return round(sum(vals) / len(vals), 3) if vals else None

        tp = sum(int(e.get("prompt_tokens") or 0) for e in evs)
        tc = sum(int(e.get("completion_tokens") or 0) for e in evs)
        cached = sum(int(e.get("cached_tokens") or 0) for e in evs)
        errors = [e.get("error") for e in evs
                  if not e.get("ok") and e.get("error")][:8]
        # --- session-scoped TTFT percentiles (§5.3). Pure, dependency-free
        #     percentile here so the observ layer does not import the UI layer
        #     (the UI's ui/analysis.compute_percentiles uses the SAME algorithm,
        #     so banner + summary agree). Never fabricates: p99 stays None on a
        #     tiny sample (low_confidence flag instead of a fake number). ---
        _pct = _compute_ttft_percentiles(evs)
        boundary_count = sum(
            1 for e in evs
            if e.get("boundary_reason") in
            ("no_reusable_prefix", "explicit_reset", "model_reload", "first"))
        warm_count = n - boundary_count
        # minimum sample size for a trustworthy p95/p99 (T4 discipline)
        _MIN_PCT_SAMPLE = 8
        ttft_n = _pct.get("n") or 0
        return {
            "enabled": self.enabled,
            "count": n,
            "by_adapter": dict(sorted(by_adapter.items(),
                                      key=lambda kv: (-kv[1], kv[0]))),
            "ok_rate": round(ok / n, 4),
            "avg_ttft_ms": _avg("ttft_ms"),
            "avg_prefill_ms": _avg("prefill_ms"),
            "avg_decode_ms": _avg("decode_ms"),
            "avg_decode_tps": _avg("decode_tps"),
            "avg_queue_wait_ms": _avg("queue_wait_ms"),
            "avg_switch_ms": _avg("switch_ms"),
            "kv_hit_rate": round(cached / tp, 4) if tp else None,
            "total_prompt_tokens": tp,
            "total_completion_tokens": tc,
            "errors": errors,
            # session-scoped percentile keys
            "ttft_p50": _pct.get("p50"),
            "ttft_p95": _pct.get("p95"),
            "ttft_p99": _pct.get("p99"),
            "boundary_count": boundary_count,
            "warm_count": warm_count,
            "low_confidence": ttft_n < _MIN_PCT_SAMPLE,
        }


def _sql_val(v, col: str):
    """Normalize Python values into the column's declared SQL type."""
    if col in ("route", "adapter", "model", "error", "request_id", "run_id",
               "operational_session_id", "boundary_reason"):
        return None if v is None else str(v)
    if v is None:
        return None
    if col == "switched" or col == "stream" or col == "ok":
        return 1 if v else 0
    if col in ("cache_signal_valid", "benchmark"):
        return 1 if v else 0
    if col == "thinking":
        return None if v is None else (1 if v else 0)
    return float(v)


def _pct(vals: list[float], q: float) -> float:
    """Linear-interpolation percentile (matches numpy default). q in [0,100]."""
    if not vals:
        return float("nan")
    vs = sorted(vals)
    if len(vs) == 1:
        return vs[0]
    k = (len(vs) - 1) * (q / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(vs) - 1)
    frac = k - lo
    return vs[lo] + (vs[hi] - vs[lo]) * frac


def _compute_ttft_percentiles(evs: list[dict]) -> dict:
    """p50/p95/p99 of TTFT over a scoped event set. Returns {"n","p50","p95","p99"}
    with None when there is no data. Never fabricates a measurement."""
    vals = [e["ttft_ms"] for e in evs
            if isinstance(e.get("ttft_ms"), (int, float))]
    if not vals:
        return {"n": 0, "p50": None, "p95": None, "p99": None}
    return {"n": len(vals),
            "p50": _pct(vals, 50),
            "p95": _pct(vals, 95),
            "p99": _pct(vals, 99)}


# --------------------------------------------------------------------------
# Module-level singleton + convenience wrappers (so callers don't have to
# thread a store reference through the coordinator / relay).
# --------------------------------------------------------------------------

_STORE: Optional[ObservStore] = None
_STORE_READY = False


def get_store() -> ObservStore:
    global _STORE, _STORE_READY
    if not _STORE_READY:
        _STORE = ObservStore(os.getenv("OBSERV_DIR") or None)
        _STORE_READY = True
    return _STORE  # type: ignore[return-value]


def record_event(ev: RequestEvent) -> None:
    get_store().record(ev)


def recent_events(n: int = 20) -> list[dict]:
    return get_store().recent(n)


def recent_events_filtered(n: int = 20, run_id=None,
                           operational_session_id=None, time_window_s=None,
                           exclude_benchmark=False) -> list[dict]:
    return get_store().recent_filtered(
        n, run_id=run_id, operational_session_id=operational_session_id,
        time_window_s=time_window_s, exclude_benchmark=exclude_benchmark)


def record_gpu_sample(s: dict) -> None:
    get_store().record_gpu_sample(s)


def recent_gpu(n: int = 180) -> list[dict]:
    return get_store().recent_gpu(n)


def summarize(run_id=None, operational_session_id=None, time_window_s=None,
               exclude_benchmark=False) -> dict:
    return get_store().summarize(
        run_id=run_id, operational_session_id=operational_session_id,
        time_window_s=time_window_s, exclude_benchmark=exclude_benchmark)
