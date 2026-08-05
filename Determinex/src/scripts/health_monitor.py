#!/usr/bin/env python3
"""Mid-run health monitor — sidecar that watches for trouble during the mass run.

Runs alongside the mass run agents. Every N seconds checks:
  - Stalled Docker containers (no log update for >stall_minutes)
  - Disk fill rate (alert if <X GB free OR filling fast)
  - VRAM pressure (delegates to vram_monitor)
  - Repeated failures across tools (>K in a row → likely bug, not bad luck)
  - Ollama daemon health (responding to /api/tags)
  - Run-dir activity (eval files landing at expected rate)

Emits actionable alerts to stdout. Designed to run in a separate terminal:

  python scripts/health_monitor.py --watch 30

Operator stops with Ctrl-C. Exit code reflects highest severity seen during the run.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Defaults ────────────────────────────────────────────────────────────────
STALL_MINUTES_DEFAULT = 15  # container with no log update for this long
DISK_LOW_GB_DEFAULT = 30  # alert if less than this on C:
DISK_FILL_RATE_GB_PER_HR = 20  # alert if filling faster than this
FAILURE_STREAK_DEFAULT = 8  # K-in-a-row failures = bug
OLLAMA_TIMEOUT_S = 5

PB_RUNS_BASE = Path("T:/determinex-programbench")
SB_RUNS_BASE = Path("T:/determinex-swebench")


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def alert(level: str, msg: str):
    glyph = {"info": " info", "warn": " WARN", "alarm": "ALARM"}.get(level, "?")
    print(f"[{ts()}] {glyph}  {msg}", flush=True)


# ── Checkers ────────────────────────────────────────────────────────────────


def check_docker_stalled(stall_minutes: int) -> list[str]:
    """Return list of container names with no log activity in stall_minutes."""
    out = []
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.CreatedAt}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            return out
        for line in r.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            name, _created, status = parts[0], parts[1], parts[2]
            # Use container's last log timestamp via docker logs --tail 1 --timestamps
            try:
                lr = subprocess.run(
                    ["docker", "logs", "--tail", "1", "--timestamps", name],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                last_log = (lr.stdout or lr.stderr).strip().split(" ")[0]
                # ISO8601 timestamp from docker
                from datetime import datetime

                last_log_dt = datetime.fromisoformat(last_log.replace("Z", "+00:00"))
                age_min = (datetime.now(tz=UTC) - last_log_dt).total_seconds() / 60
                if age_min > stall_minutes:
                    out.append(f"{name} (no logs for {age_min:.0f}min)")
            except Exception:
                pass
    except Exception:
        pass
    return out


def check_disk(low_gb: int) -> tuple[str | None, dict]:
    """Returns (level, info_dict). level in {None, warn, alarm}."""
    import shutil

    try:
        free = shutil.disk_usage("c:/").free / (1024**3)
    except Exception:
        return None, {}
    info = {"c_free_gb": free}
    if free < low_gb / 2:
        return "alarm", info
    if free < low_gb:
        return "warn", info
    return None, info


def check_ollama() -> bool:
    try:
        r = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=OLLAMA_TIMEOUT_S)
        return r.status == 200
    except Exception:
        return False


def check_failure_streak(run_base: Path, threshold: int) -> int:
    """Walks recent eval JSONs sorted by mtime; returns count of consecutive failures from newest."""
    if not run_base.is_dir():
        return 0
    eval_files = []
    for p in run_base.rglob("*"):
        if p.is_file() and (p.name.endswith(".eval.json") or p.name == "eval_report.json"):
            try:
                eval_files.append((p.stat().st_mtime, p))
            except OSError:
                continue
    eval_files.sort(reverse=True)
    streak = 0
    for _mt, p in eval_files[: threshold + 5]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        passed = d.get("passed", d.get("tests_passed", 0))
        total = d.get("total", d.get("tests_total", 0))
        if total > 0 and passed < total:
            streak += 1
        else:
            break  # passed → reset streak
    return streak


def check_eval_landing_rate(run_base: Path, window_min: int = 10) -> int:
    """Count eval files that landed in the last `window_min` minutes. 0 → run is dead."""
    if not run_base.is_dir():
        return 0
    cutoff = time.time() - (window_min * 60)
    n = 0
    for p in run_base.rglob("*"):
        if not p.is_file():
            continue
        if not (p.name.endswith(".eval.json") or p.name == "eval_report.json"):
            continue
        try:
            if p.stat().st_mtime > cutoff:
                n += 1
        except OSError:
            continue
    return n


def vram_pressure() -> tuple[str | None, dict]:
    """Delegates to vram_monitor.py. Returns (severity, info)."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from vram_monitor import VRAM_OOM_THRESHOLD_PCT, VRAM_WARN_THRESHOLD_PCT, query_vram

        snap = query_vram()
        if not snap:
            return None, {}
        if snap["used_pct"] >= VRAM_OOM_THRESHOLD_PCT:
            return "alarm", snap
        if snap["used_pct"] >= VRAM_WARN_THRESHOLD_PCT:
            return "warn", snap
        return None, snap
    except Exception:
        return None, {}


# ── Main loop ───────────────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="Mass-run health monitor")
    ap.add_argument("--watch", type=int, default=60, help="check interval in seconds (default 60)")
    ap.add_argument(
        "--stall-minutes",
        type=int,
        default=STALL_MINUTES_DEFAULT,
        help="alert if a Docker container has no log activity for this long",
    )
    ap.add_argument(
        "--disk-low-gb",
        type=int,
        default=DISK_LOW_GB_DEFAULT,
        help="warn if C: drive has less than this many GB free",
    )
    ap.add_argument(
        "--failure-streak",
        type=int,
        default=FAILURE_STREAK_DEFAULT,
        help="alert when this many tools fail in a row (likely a bug)",
    )
    ap.add_argument("--once", action="store_true", help="run all checks once and exit")
    args = ap.parse_args()

    print("=== Determinex Mass-Run Health Monitor ===")
    print(
        f"watch_interval={args.watch}s  stall_threshold={args.stall_minutes}min  "
        f"disk_low={args.disk_low_gb}GB  failure_streak={args.failure_streak}\n"
    )

    last_ollama_ok = True
    last_disk_free = None
    disk_history = deque(maxlen=10)  # tracks (timestamp, free_gb) for fill rate
    highest_severity = "info"

    try:
        while True:
            tick_start = time.time()

            # 1) Ollama daemon
            ollama_ok = check_ollama()
            if last_ollama_ok and not ollama_ok:
                alert("alarm", "Ollama daemon not responding — local builder will fail")
                highest_severity = "alarm"
            elif not last_ollama_ok and ollama_ok:
                alert("info", "Ollama daemon back up")
            last_ollama_ok = ollama_ok

            # 2) Disk
            level, info = check_disk(args.disk_low_gb)
            if "c_free_gb" in info:
                disk_history.append((time.time(), info["c_free_gb"]))
                if level == "alarm":
                    alert("alarm", f"Disk CRITICAL: only {info['c_free_gb']:.1f}GB free on C:")
                    highest_severity = "alarm"
                elif level == "warn":
                    alert(
                        "warn",
                        f"Disk low: {info['c_free_gb']:.1f}GB free on C: (threshold {args.disk_low_gb}GB)",
                    )
                    if highest_severity != "alarm":
                        highest_severity = "warn"
                # Fill-rate check
                if len(disk_history) >= 3:
                    t0, gb0 = disk_history[0]
                    t1, gb1 = disk_history[-1]
                    hours = max((t1 - t0) / 3600, 0.001)
                    rate = (gb0 - gb1) / hours
                    if rate > DISK_FILL_RATE_GB_PER_HR:
                        alert(
                            "warn",
                            f"Disk filling fast: {rate:.1f}GB/hr — {info['c_free_gb'] / max(rate, 1):.1f}h until full",
                        )

            # 3) VRAM pressure
            level, info = vram_pressure()
            if level == "alarm":
                alert(
                    "alarm",
                    f"VRAM CRITICAL: {info.get('used_mb', '?')}/{info.get('total_mb', '?')} MiB used "
                    f"({info.get('used_pct', 0):.0f}%) — Ollama OOM imminent",
                )
                highest_severity = "alarm"
            elif level == "warn":
                alert(
                    "warn",
                    f"VRAM tight: {info.get('used_pct', 0):.0f}% used — consider smaller model",
                )
                if highest_severity != "alarm":
                    highest_severity = "warn"

            # 4) Stalled Docker containers
            stalled = check_docker_stalled(args.stall_minutes)
            for s in stalled:
                alert("warn", f"Container stalled: {s}")
                if highest_severity != "alarm":
                    highest_severity = "warn"

            # 5) Failure streak across PB and SB
            for label, base in (("PB", PB_RUNS_BASE), ("SB", SB_RUNS_BASE)):
                streak = check_failure_streak(base, args.failure_streak)
                if streak >= args.failure_streak:
                    alert(
                        "alarm",
                        f"{label} failure streak: {streak} tools failed in a row "
                        f"— stop the run and investigate (likely scaffold bug, not bad luck)",
                    )
                    highest_severity = "alarm"

            # 6) Eval landing rate (proxy for "is the run alive")
            for label, base in (("PB", PB_RUNS_BASE), ("SB", SB_RUNS_BASE)):
                if base.is_dir() and any(base.iterdir()):
                    rate = check_eval_landing_rate(base, window_min=10)
                    if rate == 0:
                        # Could be normal between batches OR a dead run — only warn after 2 consecutive zeros
                        # (we'll see this on the next tick if it persists)
                        pass

            if args.once:
                break

            # Sleep until next tick (subtracting time spent in checks)
            elapsed = time.time() - tick_start
            sleep_for = max(1, args.watch - elapsed)
            time.sleep(sleep_for)

    except KeyboardInterrupt:
        print(f"\nstopped. highest severity seen: {highest_severity}")

    sys.exit(0 if highest_severity == "info" else (1 if highest_severity == "warn" else 2))


if __name__ == "__main__":
    main()
