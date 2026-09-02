#!/usr/bin/env python3
"""Promote a Rule B sidecar entry into the official Rule A ledger via clean rebase.

The Rule B promotion sat in `rule_b_promotions.jsonl` because the candidate's
runnable count differed from the baseline's. The legitimate path to making
it official:

    1. Treat the Rule B candidate's eval as the NEW baseline.
       The runnable count it observed (e.g. 398) becomes the canonical surface.
    2. Repack the same source override (no code change — we are certifying
       stability, not advancing it).
    3. Run the official eval again. Two runs of the same deterministic binary
       against the same surface should produce the same passed count.
    4. Gate the second eval against the FIRST Rule B eval in explicit
       stable-certification mode. If the second run passes >= the first AND
       has 0 regressions AND runnable is stable, it accepts under Rule A and
       enters `accepted_runs.jsonl` + the lock board's `best_*` fields cleanly.

This script orchestrates that. It does NOT touch the candidate's source —
the only thing that changes between the two runs is the baseline JSON we
compare against.

Usage:
    python scripts/pb_rule_b_promote.py <slug> --new-run-root <path>

Where:
    <slug>         the same slug that was in rule_b_promotions.jsonl
    --new-run-root the run root for the SECOND eval (must be distinct from the
                   Rule B run root so packing doesn't clobber the prior result).
                   The script will pack into this dir, run the eval, then gate.

Exit codes:
    0 = promoted (Rule A accept written to official ledger)
    1 = second eval did not match (regression or runnable changed again);
        the Rule B entry stays in the sidecar, no official ledger touch
    2 = infrastructure error (missing sidecar entry, missing override, etc.)
    3 = bad arguments
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "logs" / "programbench_factory" / "rule_b_promotions.jsonl"
LOCK_BOARD = ROOT / "logs" / "programbench_lock_board.json"
SCRIPTS = ROOT / "scripts"


def _find_latest_sidecar_entry(slug: str) -> dict | None:
    """Return the most-recent Rule B entry for this slug (or None)."""
    if not SIDECAR.is_file():
        return None
    latest = None
    latest_ts = ""
    for line in SIDECAR.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("slug") != slug:
            continue
        ts = rec.get("timestamp") or rec.get("captured_at", "")
        if ts >= latest_ts:
            latest = rec
            latest_ts = ts
    return latest


def _find_candidate_eval(run_root: Path, slug: str) -> Path | None:
    inst = run_root / slug
    if not inst.is_dir():
        return None
    for p in inst.glob("*.eval.json"):
        return p
    return None


def _run(cmd: list[str]) -> int:
    print(f"[promote] $ {' '.join(str(x) for x in cmd)}")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def promote(slug: str, new_run_root: Path, py: str) -> int:
    # 1) read the Rule B entry
    entry = _find_latest_sidecar_entry(slug)
    if entry is None:
        sys.stderr.write(f"[promote] no Rule B entry for slug {slug} in {SIDECAR}\n")
        return 2
    rule_b_run_root = entry.get("candidate_run_root", "")
    if not rule_b_run_root:
        sys.stderr.write("[promote] Rule B entry missing candidate_run_root\n")
        return 2
    rule_b_eval = _find_candidate_eval(Path(rule_b_run_root), slug)
    if rule_b_eval is None:
        sys.stderr.write(f"[promote] no eval JSON in Rule B run root {rule_b_run_root}\n")
        return 2
    rule_b_passed = entry.get("candidate_passed")
    rule_b_runnable = entry.get("candidate_runnable")
    if rule_b_passed is None or rule_b_runnable is None:
        sys.stderr.write("[promote] Rule B entry missing candidate_passed/runnable\n")
        return 2

    print(f"[promote] slug={slug}")
    print(
        f"[promote] Rule B eval baseline: {rule_b_eval}  (passed={rule_b_passed} runnable={rule_b_runnable})"
    )
    print(f"[promote] second-run root: {new_run_root}")

    if new_run_root.resolve() == Path(rule_b_run_root).resolve():
        sys.stderr.write(
            "[promote] --new-run-root must differ from the Rule B run root; "
            "pick a distinct directory so the second eval has its own slot.\n"
        )
        return 3

    # 2) repack the same source override into the new run root
    rc = _run([py, str(SCRIPTS / "pb_pack_candidate.py"), slug, "--run-root", str(new_run_root)])
    if rc != 0:
        sys.stderr.write(f"[promote] pack step failed (rc={rc})\n")
        return 2

    # 3) gate the new run against the first Rule B eval as the new measurement
    # surface. Certification mode allows delta.passed == 0 while still requiring
    # runnable stability and zero regressions.
    rc = _run(
        [
            py,
            str(SCRIPTS / "pb_candidate_gate.py"),
            slug,
            str(new_run_root),
            "--baseline-eval",
            str(rule_b_eval),
            "--min-baseline-passed",
            str(rule_b_passed),
            "--allow-stable-certification",
            "--python",
            py,
        ]
    )
    if rc != 0:
        sys.stderr.write(
            f"[promote] second eval did not gate clean against the Rule B baseline "
            f"(rc={rc}). Rule B entry stays in sidecar; official ledger untouched.\n"
        )
        return 1

    # 4) read the new gate_result to confirm Rule A acceptance
    gate_path = new_run_root / "gate_result.json"
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"[promote] could not read second-run gate_result: {e}\n")
        return 2
    rule = gate.get("decision_rule")
    decision = gate.get("decision")
    if decision != "accept" or rule != "A":
        sys.stderr.write(
            f"[promote] second eval gated as decision={decision!r} rule={rule!r}; "
            "Rule B entry stays in sidecar.\n"
        )
        return 1

    # 5) apply through the official Rule A chain
    rc = _run(
        [
            py,
            str(SCRIPTS / "pb_apply_gate_decision.py"),
            slug,
            str(gate_path),
            "--run-root",
            str(new_run_root),
            "--refresh-board",
            "--python",
            py,
        ]
    )
    if rc != 0:
        sys.stderr.write(f"[promote] Rule A apply failed (rc={rc})\n")
        return 2

    print(f"[promote] ✓ promoted {slug} via clean Rule A rebase")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="slug from rule_b_promotions.jsonl")
    ap.add_argument(
        "--new-run-root",
        type=Path,
        required=True,
        help="distinct run root for the second eval (must not collide with Rule B run root)",
    )
    ap.add_argument("--python", default=sys.executable, help="Python interpreter for sub-scripts")
    args = ap.parse_args()
    return promote(args.slug, args.new_run_root.resolve(), args.python)


if __name__ == "__main__":
    raise SystemExit(main())
