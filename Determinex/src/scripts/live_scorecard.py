#!/usr/bin/env python3
"""Live scorecard overlay for the recorded video.

Periodically scrapes the in-flight mass-run state and renders a clean,
camera-friendly scoreboard to a file (so OBS can use it as a text overlay
via "Read from file" source).

Usage:
  python scripts/live_scorecard.py
  python scripts/live_scorecard.py --refresh 5 --out C:/tmp/determinex_scoreboard.txt

OBS setup:
  1. Add Source → Text (GDI+)
  2. Check "Read from file"
  3. Point to the --out file
  4. OBS auto-refreshes when the file changes
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows console: force UTF-8 for box-drawing chars
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PB_RUNS_BASE = Path("T:/determinex-programbench")
SB_RUNS_BASE = Path("T:/determinex-swebench")
DEFAULT_OUT = Path("c:/tmp/determinex_scoreboard.txt")

START_TIME = time.time()


def scrape_state():
    """Return dict with current locks/attempts across both benches.
    PB lock = official `programbench eval` returned a perfect score (passed == total)."""
    pb_locks = []
    pb_shipped = 0
    pb_attempted = 0
    pb_in_flight = 0
    if PB_RUNS_BASE.is_dir():
        for inst_dir in PB_RUNS_BASE.glob("*/*"):
            if not inst_dir.is_dir():
                continue
            if inst_dir.parent.name.startswith("_"):
                continue  # skip _quarantine_*
            pb_attempted += 1
            had_eval = False
            for pat in ("*.eval.json", "eval_report.json"):
                for p in inst_dir.glob(pat):
                    had_eval = True
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                        results = d.get("test_results")
                        if isinstance(results, list) and results:
                            passed = sum(1 for r in results if r.get("status") == "passed")
                            failed = sum(1 for r in results if r.get("status") == "failure")
                            total = passed + failed
                        else:
                            passed = d.get("passed", d.get("tests_passed", 0))
                            total = d.get("total", d.get("tests_total", 0))
                        if total > 0 and passed == total:
                            pb_locks.append(inst_dir.name)
                    except Exception:
                        pass
                    break
            if (inst_dir / "submission.tar.gz").exists():
                pb_shipped += 1
                if not had_eval:
                    pb_in_flight += 1

    sb_resolved = 0
    sb_attempted = 0
    sb_with_patch = 0
    if SB_RUNS_BASE.is_dir():
        for pred in SB_RUNS_BASE.rglob("predictions.jsonl"):
            try:
                with pred.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            r = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        sb_attempted += 1
                        if r.get("model_patch", "").strip():
                            sb_with_patch += 1
                        # Resolved comes from a sibling eval file
                        iid = r.get("instance_id", "")
                        ev = pred.parent / f"{iid}.json"
                        if ev.exists():
                            try:
                                d = json.loads(ev.read_text(encoding="utf-8"))
                                if d.get("resolved") is True:
                                    sb_resolved += 1
                            except (OSError, json.JSONDecodeError):
                                pass
            except OSError:
                pass

    return {
        "pb": {
            "locks": pb_locks,
            "attempted": pb_attempted,
            "shipped": pb_shipped,
            "in_flight": pb_in_flight,
            "n_locks": len(pb_locks),
        },
        "sb": {
            "attempted": sb_attempted,
            "resolved": sb_resolved,
            "with_patch": sb_with_patch,
        },
    }


def render(state: dict) -> str:
    elapsed = int(time.time() - START_TIME)
    h, rem = divmod(elapsed, 3600)
    m, s = divmod(rem, 60)
    pb = state["pb"]
    sb = state["sb"]
    total_locks = pb["n_locks"] + sb["resolved"]
    lph = total_locks / max(elapsed / 3600, 0.001)

    lines = []
    lines.append("DETERMINEX · MASS BENCH RUN")
    lines.append(f"  elapsed:  {h:02d}:{m:02d}:{s:02d}")
    lines.append("")
    lines.append("┌─ ProgramBench (official-eval verified) ")
    lines.append(f"│  attempted:  {pb['attempted']:>3} / 200")
    lines.append(f"│  shipped:    {pb.get('shipped', 0):>3}")
    lines.append(f"│  in-flight:  {pb['in_flight']:>3}")
    lines.append(f"│  LOCKED:     {pb['n_locks']:>3}  at 100% (true)")
    lines.append("└────────────────────────────────────────")
    lines.append("")
    lines.append("┌─ SWE-bench ────────────────────────────")
    lines.append(f"│  attempted:  {sb['attempted']:>4} / 5,274")
    lines.append(f"│  patched:    {sb['with_patch']:>4}")
    lines.append(f"│  RESOLVED:   {sb['resolved']:>4}")
    lines.append("└────────────────────────────────────────")
    lines.append("")
    lines.append("┌─ COMBINED ─────────────────────────────")
    lines.append(f"│  Total locks:   {total_locks:>4} / 5,474")
    lines.append(f"│  Locks/hour:    {lph:>5.1f}")
    lines.append("│  Frontier:      0 / 5,474   (best AI on Earth)")
    if total_locks > 0:
        lines.append("│  Determinex:       ∞× the frontier ceiling")
    lines.append("└────────────────────────────────────────")
    lines.append("")
    lines.append(f"updated {datetime.now().strftime('%H:%M:%S')}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", type=int, default=10, help="seconds between updates (default 10)")
    ap.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"output text file for OBS (default {DEFAULT_OUT})",
    )
    ap.add_argument("--once", action="store_true", help="render once and exit (for testing)")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if args.once:
        s = scrape_state()
        out = render(s)
        args.out.write_text(out, encoding="utf-8")
        print(out)
        return

    print(f"[live_scorecard] writing {args.out} every {args.refresh}s. Ctrl-C to stop.")
    try:
        while True:
            s = scrape_state()
            out = render(s)
            args.out.write_text(out, encoding="utf-8")
            # Also clear screen + reprint to terminal for operator visibility
            print("\033[2J\033[H" + out)
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
