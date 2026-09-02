#!/usr/bin/env python3
"""Ceiling analysis — where does 7b alone (with corpus) plateau?

For every task in a mass-run dir, classifies the outcome:
  T1-LOCK   : 7b locked it on its own (corpus did the architectural work)
  T2-LOCK   : 14b cracked it after 7b stalled (corpus enough for 14b)
  T3-LOCK   : DeepSeek needed (cloud + corpus required)
  SHIPPED   : compile-clean submission, eval < 100 (best effort, not locked)
  GAVE_UP   : never compiled, gave up entirely

The "corpus ceiling" thesis: T1-LOCK rate measures how much architectural
reasoning the spec injection contributes vs raw model size.

Reads from `metrics.json` per task (no restart needed; the agent records
per-attempt `model_used` already).

Usage:
  python scripts/ceiling_analysis.py                                # all PB runs
  python scripts/ceiling_analysis.py --run mass_run_v2_escalate     # one run
  python scripts/ceiling_analysis.py --watch 60                     # refresh every 60s
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PB_RUNS_BASE = Path("T:/determinex-programbench")


def _tier_of_attempt(am: dict) -> str:
    """Return 'T1'/'T2'/'T3'/'?' for an AttemptMetrics dict."""
    label = (am.get("model_used") or "").lower()
    if "deepseek" in label or "t3" in label:
        return "T3"
    if "14b" in label or "t2" in label:
        return "T2"
    if "7b" in label or "t1" in label or label.endswith("instruct"):
        return "T1"
    return "?"


def classify_task(metrics_path: Path) -> dict:
    """Read one metrics.json, return a classification record."""
    try:
        d = json.loads(metrics_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"path": str(metrics_path), "error": f"parse failed: {e}"}

    iid = d.get("instance_id", metrics_path.parent.name)
    attempts = d.get("attempts", [])
    verified = bool(d.get("verified_locked", False))
    shipped = bool(d.get("shipped", False))
    final_eval = d.get("final_eval_score", -1)

    # Determine lock tier — last attempt where eval_score reached 100
    lock_tier = ""
    if verified:
        for am in reversed(attempts):
            if am.get("eval_score", -1) >= 100:
                lock_tier = _tier_of_attempt(am)
                break

    # Highest tier ever attempted
    tiers_used = [_tier_of_attempt(am) for am in attempts]
    highest_tier = max(
        tiers_used,
        key=lambda t: ["T1", "T2", "T3", "?"].index(t) if t in ("T1", "T2", "T3") else -1,
        default="?",
    )

    # Where did 7b give out? (first attempt that's NOT T1)
    escalated_at = None
    for i, am in enumerate(attempts):
        if _tier_of_attempt(am) != "T1":
            escalated_at = i + 1  # 1-indexed attempt number
            break

    # Best score across all attempts
    best_score = -1
    for am in attempts:
        s = am.get("eval_score", -1)
        if s > best_score:
            best_score = s

    # Outcome category
    if verified and lock_tier == "T1":
        outcome = "T1_LOCK"
    elif verified and lock_tier == "T2":
        outcome = "T2_LOCK"
    elif verified and lock_tier == "T3":
        outcome = "T3_LOCK"
    elif verified:
        outcome = "LOCK_UNK"
    elif shipped and best_score > 0:
        outcome = "SHIPPED_PARTIAL"
    elif shipped:
        outcome = "SHIPPED_ZERO"
    else:
        outcome = "GAVE_UP"

    return {
        "iid": iid,
        "outcome": outcome,
        "lock_tier": lock_tier,
        "highest_tier_used": highest_tier,
        "escalated_at_attempt": escalated_at,
        "n_attempts": len(attempts),
        "final_eval_score": final_eval,
        "best_score": best_score,
        "verified_locked": verified,
        "shipped": shipped,
        "tiers_attempted": tiers_used,
    }


def find_metrics(runs_base: Path, run_filter: str | None) -> list[Path]:
    out = []
    if not runs_base.is_dir():
        return out
    for run_dir in runs_base.iterdir():
        if not run_dir.is_dir():
            continue
        if run_dir.name.startswith("_"):
            continue
        if run_filter and run_dir.name != run_filter:
            continue
        for inst_dir in run_dir.iterdir():
            if not inst_dir.is_dir():
                continue
            mp = inst_dir / "metrics.json"
            if mp.exists():
                out.append(mp)
    return out


def render(records: list[dict]) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CEILING ANALYSIS — where does 7b + corpus plateau?")
    lines.append("=" * 72)

    by_outcome = Counter(r["outcome"] for r in records if "outcome" in r)
    n_total = sum(by_outcome.values())
    n_locked = (
        by_outcome["T1_LOCK"]
        + by_outcome["T2_LOCK"]
        + by_outcome["T3_LOCK"]
        + by_outcome["LOCK_UNK"]
    )

    lines.append(f"\nTasks scored:  {n_total}")
    lines.append(f"VERIFIED LOCKS: {n_locked}  ({100 * n_locked / max(n_total, 1):.1f}%)\n")

    lines.append("Lock tier breakdown (corpus value measurement):")
    lines.append(f"  T1·7b (corpus DID the work):       {by_outcome['T1_LOCK']:>3}")
    lines.append(f"  T2·14b (corpus + bigger model):    {by_outcome['T2_LOCK']:>3}")
    lines.append(f"  T3·deepseek (cloud needed):        {by_outcome['T3_LOCK']:>3}")
    if by_outcome["LOCK_UNK"]:
        lines.append(f"  Locked, tier unknown:              {by_outcome['LOCK_UNK']:>3}")
    lines.append("")
    lines.append("Non-lock outcomes:")
    lines.append(f"  Shipped, partial eval (1-99):      {by_outcome['SHIPPED_PARTIAL']:>3}")
    lines.append(f"  Shipped, eval = 0:                 {by_outcome['SHIPPED_ZERO']:>3}")
    lines.append(f"  Gave up (never compiled):          {by_outcome['GAVE_UP']:>3}")

    # Where 7b gave out (escalation events)
    escalated = [
        r for r in records if r.get("escalated_at_attempt") and r.get("highest_tier_used") != "T1"
    ]
    if escalated:
        lines.append(f"\nEscalation events: {len(escalated)} tasks left T1")
        attempts_dist = Counter(r["escalated_at_attempt"] for r in escalated)
        for n in sorted(attempts_dist):
            lines.append(f"  Escalated at attempt {n}: {attempts_dist[n]}")

    # 7b ceiling — tools 7b alone could lock
    t1_locks = [r for r in records if r["outcome"] == "T1_LOCK"]
    if t1_locks:
        lines.append("\n7b SOLO LOCKS (with corpus injection — these are the corpus's wins):")
        for r in sorted(t1_locks, key=lambda x: x["iid"])[:25]:
            lines.append(f"  ✓ {r['iid']}")
        if len(t1_locks) > 25:
            lines.append(f"  ... +{len(t1_locks) - 25} more")

    # Tools 7b couldn't do but 14b/DeepSeek did
    t2_locks = [r for r in records if r["outcome"] == "T2_LOCK"]
    t3_locks = [r for r in records if r["outcome"] == "T3_LOCK"]
    if t2_locks:
        lines.append("\n14b RESCUES (7b stalled, 14b finished — partial corpus value):")
        for r in sorted(t2_locks, key=lambda x: x["iid"])[:15]:
            esc = r.get("escalated_at_attempt", "?")
            lines.append(f"  ↑ {r['iid']}   (escalated at attempt {esc})")
    if t3_locks:
        lines.append("\nDEEPSEEK RESCUES (7b + 14b both stalled — corpus alone insufficient):")
        for r in sorted(t3_locks, key=lambda x: x["iid"])[:15]:
            esc = r.get("escalated_at_attempt", "?")
            lines.append(f"  ⇈ {r['iid']}   (escalated at attempt {esc})")

    # Total ceiling: what 7b + corpus could NOT do
    not_done_by_7b = (
        by_outcome["T2_LOCK"]
        + by_outcome["T3_LOCK"]
        + by_outcome["SHIPPED_PARTIAL"]
        + by_outcome["SHIPPED_ZERO"]
        + by_outcome["GAVE_UP"]
    )
    if n_total:
        ceiling_pct = 100 * by_outcome["T1_LOCK"] / n_total
        lines.append("\n=== CORPUS-7B CEILING ===")
        lines.append(
            f"  7b solo (with corpus) locks:  {by_outcome['T1_LOCK']:>3}/{n_total} = {ceiling_pct:.1f}%"
        )
        lines.append(
            f"  Need bigger/cloud model:      {not_done_by_7b - by_outcome['SHIPPED_PARTIAL'] - by_outcome['SHIPPED_ZERO'] - by_outcome['GAVE_UP']:>3}"
        )
        lines.append(
            f"  Beyond all 3 tiers:           {by_outcome['SHIPPED_PARTIAL'] + by_outcome['SHIPPED_ZERO'] + by_outcome['GAVE_UP']:>3}"
        )

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="Specific run name (e.g. mass_run_v2_escalate). Default: all.")
    ap.add_argument("--watch", type=int, default=0, help="Re-render every N seconds")
    ap.add_argument("--out-json", type=Path, help="Also write per-task records to JSON")
    args = ap.parse_args()

    def once():
        paths = find_metrics(PB_RUNS_BASE, args.run)
        records = [classify_task(p) for p in paths]
        records = [r for r in records if "outcome" in r]
        out = render(records)
        if args.out_json:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(json.dumps(records, indent=2), encoding="utf-8")
        return out, records

    if args.watch:
        try:
            while True:
                out, _ = once()
                print("\033[2J\033[H" + out)
                print(f"\n[refreshing every {args.watch}s — Ctrl-C to stop]")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\nstopped.")
    else:
        out, _ = once()
        print(out)


if __name__ == "__main__":
    main()
