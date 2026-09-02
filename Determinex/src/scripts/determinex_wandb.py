#!/usr/bin/env python3
"""determinex_wandb.py — Weights & Biases integration for ML experiment tracking.

Logs each eval iteration as a W&B run with:
- All scores (per-tool + aggregate)
- Scaffold version (commit SHA)
- Score deltas vs previous iteration
- Per-tool history charts

Usage:
    python determinex_wandb.py log-iteration --label v22 --scaffold-sha 48172669
    python determinex_wandb.py log-eval --instance cheat --pct 14.98 --total 307

Requires: pip install wandb
ENV: WANDB_API_KEY, WANDB_PROJECT (default: determinex-programbench)
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "logs" / "determinex.db"


def _wandb_init(run_name: str, config: dict | None = None):
    try:
        import wandb  # type: ignore[import-not-found]
    except ImportError:
        print("wandb not installed; run `pip install wandb`")
        sys.exit(1)
    project = os.environ.get("WANDB_PROJECT", "determinex-programbench")
    run = wandb.init(project=project, name=run_name, config=config or {}, reinit=True)
    return wandb, run


def cmd_log_iteration(args):
    """Log all current latest scores as one W&B iteration."""
    if not DB.exists():
        print(f"no DB at {DB}; run determinex_db.py init first")
        sys.exit(1)

    wandb, run = _wandb_init(
        args.label,
        {
            "scaffold_sha": args.scaffold_sha,
            "iteration": args.label,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )

    c = sqlite3.connect(DB)
    cur = c.cursor()
    cur.execute("""
        SELECT e.instance_id, e.pct, e.passed, e.total, e.duration_s
        FROM evals e
        WHERE e.ran_at = (SELECT MAX(ran_at) FROM evals e2 WHERE e2.instance_id = e.instance_id)
        AND e.pct IS NOT NULL
        ORDER BY e.pct DESC
    """)
    rows = cur.fetchall()
    c.close()

    # Aggregate
    n = len(rows)
    if n == 0:
        print("no scored evals")
        sys.exit(0)
    total_pass = sum(r[2] for r in rows)
    total_tests = sum(r[3] for r in rows)
    agg = 100 * total_pass / total_tests
    avg = sum(r[1] for r in rows) / n

    wandb.log(
        {
            "n_scored": n,
            "weighted_aggregate": agg,
            "per_tool_average": avg,
            "total_passed": total_pass,
            "total_tests": total_tests,
        }
    )

    # Per-tool
    bucket_counts = {"95-100": 0, "70-94": 0, "40-69": 0, "10-39": 0, "0-9": 0}
    table = wandb.Table(columns=["instance_id", "pct", "passed", "total", "duration_s"])
    for inst, pct, p, t, d in rows:
        table.add_data(inst, pct, p, t, d or 0)
        wandb.log({f"score/{inst}": pct})
        if pct >= 95:
            bucket_counts["95-100"] += 1
        elif pct >= 70:
            bucket_counts["70-94"] += 1
        elif pct >= 40:
            bucket_counts["40-69"] += 1
        elif pct >= 10:
            bucket_counts["10-39"] += 1
        else:
            bucket_counts["0-9"] += 1
    for b, n in bucket_counts.items():
        wandb.log({f"bucket/{b}": n})

    wandb.log({"scores_table": table})
    wandb.finish()
    print(f"logged {len(rows)} tool scores to W&B as run '{args.label}'")


def cmd_log_eval(args):
    """Log single eval."""
    wandb, run = _wandb_init(f"eval-{args.instance}", {"instance_id": args.instance})
    wandb.log({"pct": args.pct, "passed": args.passed, "total": args.total})
    wandb.finish()
    print(f"logged {args.instance} = {args.pct}%")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("log-iteration")
    sp.add_argument("--label", required=True)
    sp.add_argument("--scaffold-sha", default="")

    sp = sub.add_parser("log-eval")
    sp.add_argument("--instance", required=True)
    sp.add_argument("--pct", type=float, required=True)
    sp.add_argument("--passed", type=int, default=0)
    sp.add_argument("--total", type=int, default=0)

    args = ap.parse_args()
    {"log-iteration": cmd_log_iteration, "log-eval": cmd_log_eval}[args.cmd](args)


if __name__ == "__main__":
    main()
