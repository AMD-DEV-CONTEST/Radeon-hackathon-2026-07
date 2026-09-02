#!/usr/bin/env python3
"""Auto-revert regressed overrides.

Compares current eval.json scores against a baseline (v36 done.v36_final
or v34 done.v33b_final). For each tool where current < baseline by more
than --threshold, this:
  1. Deletes the override from corpus/programbench/per_tool_overrides/
  2. Re-synthesizes the scaffold via scripts/scaffold_synthesizer.py (synth-only)
  3. Marks tool for re-queue on Hetzner

Outputs:
  - logs/regressions_<timestamp>.json with per-tool deltas
  - c:/tmp/revert_list.txt with tool slugs to re-queue

Usage:
  python scripts/analysis/auto_revert_regressions.py
  python scripts/analysis/auto_revert_regressions.py --threshold 5.0  # only revert >5pp regressions
  python scripts/analysis/auto_revert_regressions.py --baseline-source hetzner  # pull done.v36_final from Hetzner

Run after a pool drain.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = Path("T:/determinex-programbench")
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def fetch_hetzner_baseline(remote_file: str = "done.v36_final") -> dict:
    """Pull baseline done.txt from Hetzner via ssh."""
    cmd = [
        "ssh",
        "-i",
        str(Path.home() / ".ssh" / "id_determinex"),
        "root@5.78.192.163",
        f"cat /root/queue/{remote_file}",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print(f"  ssh failed: {r.stderr[:200]}")
            return {}
    except Exception as e:
        print(f"  ssh error: {e}")
        return {}
    return parse_done_log(r.stdout)


def parse_done_log(text: str) -> dict:
    """Parse done.txt content into {tool_key: pct}."""
    scores = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        tk = parts[0]
        m = re.match(r"(\d+)/(\d+)=([\d.]+)%", parts[1])
        if m:
            scores[tk] = float(m.group(3))
    return scores


def current_scores() -> dict:
    """Read latest eval.json per tool."""
    scores = {}
    for ej in glob.glob(str(EVAL_ROOT / "determinex_pb_*_v*" / "*" / "*.eval.json")):
        p = Path(ej)
        tk = p.parent.name
        mt = p.stat().st_mtime
        if tk not in scores or mt > scores[tk][1]:
            try:
                with open(ej, encoding="utf-8", errors="replace") as f:
                    j = json.load(f)
                rs = j.get("test_results") or []
                passed = sum(1 for r in rs if r.get("status") == "passed")
                total = len(rs)
                if total > 0:
                    pct = 100.0 * passed / total
                    scores[tk] = (pct, mt)
            except Exception:
                pass
    return {tk: v[0] for tk, v in scores.items()}


def revert_one(tool_key: str) -> bool:
    """Delete override + re-sync scaffold from synth (best effort)."""
    ov = OVERRIDES / tool_key
    if ov.is_dir():
        shutil.rmtree(ov)
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--threshold", type=float, default=3.0, help="revert if current < baseline by this many pp"
    )
    ap.add_argument(
        "--baseline-source",
        default="hetzner",
        choices=["hetzner", "v36_final", "v33b_final", "local-v34"],
        help="where to pull baseline from",
    )
    ap.add_argument("--baseline-file", default="done.v36_final")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.baseline_source == "hetzner":
        print(f"Fetching baseline from Hetzner: /root/queue/{args.baseline_file}")
        baseline = fetch_hetzner_baseline(args.baseline_file)
    elif args.baseline_source == "local-v34":
        # Use v34 final snapshot we synced
        p = Path("c:/tmp/v34_done.txt")
        if not p.is_file():
            print("c:/tmp/v34_done.txt missing — fetch from Hetzner first")
            return
        baseline = parse_done_log(p.read_text(encoding="utf-8"))
    else:
        # Generic file lookup
        p = Path("c:/tmp") / args.baseline_file
        if not p.is_file():
            print(f"{p} missing")
            return
        baseline = parse_done_log(p.read_text(encoding="utf-8"))

    if not baseline:
        print("No baseline scores loaded")
        return

    current = current_scores()
    print(f"baseline tools: {len(baseline)}")
    print(f"current tools:  {len(current)}")
    print()

    # Identify regressions
    regressed = []
    improved = []
    same = []
    for tk, cur in current.items():
        if tk not in baseline:
            continue
        delta = cur - baseline[tk]
        if delta < -args.threshold:
            regressed.append((tk, baseline[tk], cur, delta))
        elif delta > args.threshold:
            improved.append((tk, baseline[tk], cur, delta))
        else:
            same.append((tk, baseline[tk], cur, delta))

    regressed.sort(key=lambda x: x[3])  # worst first
    improved.sort(key=lambda x: -x[3])  # best first

    print(f"=== REGRESSIONS (delta < -{args.threshold}) ===")
    print(f"{'tool':<50} {'baseline':>10} {'current':>10} {'delta':>10}")
    for tk, base, cur, d in regressed:
        print(f"  {tk:<50} {base:>9.2f}% {cur:>9.2f}% {d:>+9.2f}pp")
    print()
    print(f"=== IMPROVEMENTS (delta > {args.threshold}) ===")
    print(f"{'tool':<50} {'baseline':>10} {'current':>10} {'delta':>10}")
    for tk, base, cur, d in improved[:30]:
        print(f"  {tk:<50} {base:>9.2f}% {cur:>9.2f}% {d:>+9.2f}pp")
    if len(improved) > 30:
        print(f"  ... +{len(improved) - 30} more")
    print()
    print("=== SUMMARY ===")
    print(f"  regressed: {len(regressed)}")
    print(f"  improved:  {len(improved)}")
    print(f"  same:      {len(same)}")
    print(
        f"  net delta: {sum(d for _, _, _, d in regressed) + sum(d for _, _, _, d in improved):+.2f}pp"
    )

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return

    # Revert regressed
    print()
    print(f"=== REVERTING {len(regressed)} regressed overrides ===")
    revert_list_path = Path("c:/tmp/revert_list.txt")
    with revert_list_path.open("w", encoding="utf-8", newline="\n") as f:
        reverted = 0
        for tk, base, cur, d in regressed:
            if revert_one(tk):
                reverted += 1
                f.write(f"{tk}\n")
                print(f"  reverted {tk} (was {cur:.2f}%, baseline {base:.2f}%)")
        print(f"\n  total reverted: {reverted}")

    # Write per-tool log
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"regressions_{ts}.json"
    log_path.write_text(
        json.dumps(
            {
                "baseline_source": args.baseline_source,
                "threshold": args.threshold,
                "regressed": [
                    {"tool": t, "baseline": b, "current": c, "delta": d} for t, b, c, d in regressed
                ],
                "improved": [
                    {"tool": t, "baseline": b, "current": c, "delta": d} for t, b, c, d in improved
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n  log: {log_path}")
    print(f"  revert list: {revert_list_path}")
    print()
    print("Next: re-synth scaffolds with `python scripts/scaffold_synthesizer.py --execute`")
    print(f"      Then sync to Hetzner + re-queue the {reverted} reverted tools")


if __name__ == "__main__":
    main()
