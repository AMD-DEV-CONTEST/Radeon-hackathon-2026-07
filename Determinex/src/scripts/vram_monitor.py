#!/usr/bin/env python3
"""VRAM monitor + model auto-select.

Three modes:
  1. --check (default) — single snapshot, exit 0 if safe / 1 if alarm
  2. --watch N — refresh every N seconds, alert on threshold breaches
  3. --recommend — print the largest model that fits the available VRAM

Used by:
  - preflight_mass_run.py (single check)
  - mass-run sidecar (--watch during the live run, alert on OOM risk)
  - OPERATOR_PLAYBOOK.md (model picker)

Thresholds (configurable):
  - VRAM_WARN_THRESHOLD_PCT = 90  → warn when used >= 90% of total
  - VRAM_OOM_THRESHOLD_PCT = 95  → alarm; recommend killing largest model
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime

# Windows console: force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Config ──────────────────────────────────────────────────────────────────
VRAM_WARN_THRESHOLD_PCT = 90
VRAM_OOM_THRESHOLD_PCT = 95

# Model size catalog (GB on disk; runtime VRAM is similar but +0.5-1GB overhead)
# Larger picks need to fit in available_vram - 1GB headroom
MODEL_CATALOG = [
    # (name, disk_gb, vram_floor_gb, quality_rank — higher is better)
    # vram_floor_gb = realistic loaded VRAM (q4_K_M + ~10% KV cache headroom for typical context).
    # Conservative: assumes 4-bit quant + 8K-16K context. Larger contexts add ~0.5-1GB.
    ("qwen2.5-coder:32b-instruct-q4_K_M", 19.9, 21.0, 100),
    ("qwen2.5-coder:14b-instruct-q4_K_M", 9.0, 9.8, 85),
    ("determinex-sentinel-v5-dsl:latest", 7.7, 8.4, 75),
    ("qwen2.5-coder:7b-instruct", 4.7, 5.1, 70),
    ("determinex-observer-v6-dsl:latest", 3.3, 3.8, 65),
    ("qwen2.5-coder:3b-instruct", 1.9, 2.3, 55),
    ("determinex-engineer-v11-dsl:latest", 1.6, 2.0, 50),
    ("qwen2.5-coder:1.5b-instruct", 1.0, 1.4, 35),
]


def query_vram() -> dict:
    """Returns {free_mb, used_mb, total_mb, free_pct, used_pct, name} or {} on failure."""
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.free,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if r.returncode != 0:
            return {}
        line = r.stdout.strip().splitlines()[0] if r.stdout else ""
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            return {}
        name, free, used, total = parts[0], int(parts[1]), int(parts[2]), int(parts[3])
        return {
            "name": name,
            "free_mb": free,
            "used_mb": used,
            "total_mb": total,
            "free_pct": 100.0 * free / total,
            "used_pct": 100.0 * used / total,
        }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}


def query_loaded_ollama() -> list[dict]:
    """Returns list of currently-loaded Ollama models with VRAM hints from /api/ps."""
    try:
        import urllib.request

        r = urllib.request.urlopen("http://localhost:11434/api/ps", timeout=5)
        data = json.loads(r.read())
        return data.get("models", [])
    except Exception:
        return []


def recommend_model(available_mb: int, *, total_mb: int | None = None) -> tuple[str, str]:
    """Pick the largest model that fits.

    Uses two budgets:
      - aggressive: total VRAM - 1GB system overhead (assumes Ollama can reclaim idle allocations)
      - conservative: currently-free VRAM - 512MB safety margin (assumes nothing budges)

    Picks the largest model that fits the AGGRESSIVE budget, but warns if it doesn't also fit
    the conservative one.
    """
    if total_mb is None:
        total_mb = available_mb + 1024  # rough fallback
    aggressive_mb = max(0, total_mb - 1024)  # ~85% of total for the model
    conservative_mb = max(0, available_mb - 512)  # only what's currently free

    for name, _disk_gb, vram_floor_gb, _quality in MODEL_CATALOG:
        floor_mb = int(vram_floor_gb * 1024)
        if floor_mb <= aggressive_mb:
            if floor_mb <= conservative_mb:
                return (
                    name,
                    f"fits comfortably ({available_mb} MiB free, model needs {floor_mb} MiB)",
                )
            return name, (
                f"fits after Ollama claims VRAM (total {total_mb} MiB; model needs {floor_mb} MiB) "
                f"— current free is {available_mb} MiB; close other GPU apps if Ollama OOMs"
            )
    return "qwen2.5-coder:1.5b-instruct", f"only {available_mb} MiB free — emergency smallest model"


def render_status(snap: dict, loaded: list[dict]) -> tuple[str, str]:
    """Returns (status, text) where status in {ok, warn, alarm}."""
    if not snap:
        return "alarm", "[VRAM] nvidia-smi unavailable — cannot check"
    used_pct = snap["used_pct"]
    if used_pct >= VRAM_OOM_THRESHOLD_PCT:
        status = "alarm"
        glyph = "[ALARM]"
    elif used_pct >= VRAM_WARN_THRESHOLD_PCT:
        status = "warn"
        glyph = "[WARN] "
    else:
        status = "ok"
        glyph = "[OK]   "

    rec_name, rec_reason = recommend_model(snap["free_mb"], total_mb=snap["total_mb"])
    lines = [
        f"{glyph} VRAM  {snap['used_mb']:>5}/{snap['total_mb']:>5} MiB used "
        f"({used_pct:5.1f}%)  free={snap['free_mb']:>5} MiB",
        f"        recommend: {rec_name}  ({rec_reason})",
    ]
    if loaded:
        lines.append("        loaded Ollama models:")
        for m in loaded:
            name = m.get("name", "?")
            sz = m.get("size", 0) / (1024**3)
            sz_vram = m.get("size_vram", 0) / (1024**3) if "size_vram" in m else None
            extra = f"  vram={sz_vram:.1f}GB" if sz_vram is not None else ""
            lines.append(f"          - {name:50s} disk={sz:.1f}GB{extra}")
    return status, "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="VRAM monitor + model auto-select")
    ap.add_argument("--check", action="store_true", help="single snapshot (default)")
    ap.add_argument("--watch", type=int, default=0, help="refresh every N seconds")
    ap.add_argument(
        "--recommend",
        action="store_true",
        help="print recommended model name only (machine-parseable)",
    )
    ap.add_argument(
        "--alert-on",
        choices=("warn", "alarm"),
        default="alarm",
        help="exit non-zero on this severity (default: alarm only)",
    )
    args = ap.parse_args()

    if args.recommend:
        snap = query_vram()
        if not snap:
            print("qwen2.5-coder:1.5b-instruct")
            sys.exit(2)
        rec, _ = recommend_model(snap["free_mb"], total_mb=snap["total_mb"])
        print(rec)
        sys.exit(0)

    if args.watch:
        prev_status = None
        try:
            while True:
                snap = query_vram()
                loaded = query_loaded_ollama()
                status, text = render_status(snap, loaded)
                ts = datetime.now().strftime("%H:%M:%S")
                # Only print if status changed OR every minute
                if status != prev_status or int(time.time()) % 60 < args.watch:
                    print(f"\n[{ts}] {text}")
                    prev_status = status
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nstopped.")
        return

    # Default: single check
    snap = query_vram()
    loaded = query_loaded_ollama()
    status, text = render_status(snap, loaded)
    print(text)
    if args.alert_on == "warn" and status in ("warn", "alarm"):
        sys.exit(1)
    if args.alert_on == "alarm" and status == "alarm":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
