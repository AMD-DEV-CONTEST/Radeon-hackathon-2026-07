#!/usr/bin/env python3
"""Batch gate + apply for the prebuilt _pending_apply.json list."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
PENDING = ROOT / "logs" / "programbench_factory" / "_pending_apply.json"


def run(cmd, check=False):
    print("+", " ".join(str(x) for x in cmd))
    r = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
    )
    print(r.stdout)
    if check and r.returncode != 0:
        raise SystemExit(f"command failed: {r.returncode}")
    return r.returncode


def main():
    items = json.loads(PENDING.read_text(encoding="utf-8"))
    print(f"Processing {len(items)} candidates")
    summary = []
    for i, item in enumerate(items, 1):
        slug = item["slug"]
        base = item["base"]
        run_root = item["run_root"]
        baseline = item["baseline_eval"]
        if not os.path.isfile(baseline):
            print(f"[{i}/{len(items)}] {base}: baseline missing {baseline}, skipping")
            summary.append((base, "skip_no_baseline", item["score"]))
            continue

        print(
            f"\n=== [{i}/{len(items)}] {base} {item['score']:.2f}% ({item['passed']}/{item['runnable']}) ==="
        )
        gate_json = Path(run_root) / "gate_result.json"

        # 1. gate
        gate_cmd = [
            PY,
            ROOT / "scripts" / "pb_candidate_gate.py",
            slug,
            run_root,
            "--baseline-eval",
            baseline,
            "--min-baseline-passed",
            "1",
            "--skip-eval",
        ]
        rc = run(gate_cmd)

        if not gate_json.is_file():
            print("  gate did not produce result, skipping apply")
            summary.append((base, f"gate_failed_rc{rc}", item["score"]))
            continue

        gate = json.loads(gate_json.read_text(encoding="utf-8"))
        decision = gate.get("decision")
        print(f"  decision: {decision}")

        if decision != "accept":
            summary.append((base, f"reject:{decision}", item["score"]))
            continue

        # 2. apply
        apply_cmd = [
            PY,
            ROOT / "scripts" / "pb_apply_gate_decision.py",
            slug,
            str(gate_json),
            "--run-root",
            run_root,
            "--refresh-board",
        ]
        rc2 = run(apply_cmd)
        summary.append((base, f"apply_rc{rc2}", item["score"]))

    print("\n=== SUMMARY ===")
    for base, outcome, score in summary:
        print(f"  {score:6.2f}%  {base:40} {outcome}")


if __name__ == "__main__":
    main()
