#!/usr/bin/env python3
"""Gate all locally evaluated ProgramBench native queue rows.

This is the local counterpart to `pb_hetzner_pool.py --gate`: it reads
`NATIVE_EVAL_QUEUE.json`, finds rows with `status == "evaluated"`, runs the
candidate gate against the current board baseline, applies accepts, ingests
rejects into the verdict corpus, and archives 100% accepts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
QUEUE = ROOT / "logs" / "programbench_factory" / "NATIVE_EVAL_QUEUE.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def board_by_base() -> dict[str, dict[str, Any]]:
    return {r["base_slug"]: r for r in load_json(BOARD) if r.get("base_slug")}


def run(cmd: list[str], *, dry_run: bool) -> subprocess.CompletedProcess[str] | None:
    print("+", " ".join(str(x) for x in cmd), flush=True)
    if dry_run:
        return None
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def eval_counts(eval_path: Path) -> tuple[int, int]:
    ev = load_json(eval_path)
    counts: dict[str, int] = {}
    for t in ev.get("test_results", []):
        status = t.get("status")
        counts[status] = counts.get(status, 0) + 1
    runnable = counts.get("passed", 0) + counts.get("failure", 0) + counts.get("error", 0)
    return counts.get("passed", 0), runnable


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-apply", action="store_true")
    ap.add_argument("--no-ingest-rejects", action="store_true")
    args = ap.parse_args()

    rows = load_json(QUEUE)
    board = board_by_base()
    candidates = [r for r in rows if r.get("status") == "evaluated"]
    if args.limit:
        candidates = candidates[: args.limit]

    accepts: list[str] = []
    rejects: list[str] = []
    archived: list[str] = []
    skipped: list[str] = []

    for row in candidates:
        slug = row["slug"]
        base = row["base_slug"]
        run_root = Path(row["run_root"])
        if not run_root.is_absolute():
            run_root = ROOT / run_root
        eval_path = run_root / slug / f"{slug}.eval.json"
        gate_path = run_root / "gate_result.json"
        baseline = board.get(base, {}).get("best_eval_path")
        if not baseline:
            skipped.append(f"{slug}: no baseline")
            continue
        if not eval_path.is_file():
            skipped.append(f"{slug}: no eval")
            continue

        if not gate_path.is_file():
            run(
                [
                    sys.executable,
                    ROOT / "scripts" / "pb_candidate_gate.py",
                    slug,
                    run_root,
                    "--baseline-eval",
                    baseline,
                    "--min-baseline-passed",
                    "1",
                    "--skip-eval",
                ],
                dry_run=args.dry_run,
            )
        if args.dry_run:
            continue
        if not gate_path.is_file():
            skipped.append(f"{slug}: gate missing")
            continue

        gate = load_json(gate_path)
        decision = gate.get("decision")
        if decision == "accept":
            accepts.append(
                f"{slug}: +{gate.get('candidate_passed', 0) - gate.get('baseline_passed', 0)}"
            )
            if not args.no_apply:
                run(
                    [
                        sys.executable,
                        ROOT / "scripts" / "pb_apply_gate_decision.py",
                        slug,
                        gate_path,
                        "--run-root",
                        run_root,
                        "--refresh-board",
                    ],
                    dry_run=False,
                )
            passed, runnable = eval_counts(eval_path)
            if passed == runnable and runnable > 0:
                ar = run(
                    [
                        sys.executable,
                        ROOT / "scripts" / "pb_lock_archiver.py",
                        slug,
                        eval_path,
                        run_root,
                        "--confirm-100",
                        "--execute",
                    ],
                    dry_run=False,
                )
                if ar and ar.returncode == 0:
                    archived.append(slug)
        else:
            rejects.append(f"{slug}: {gate.get('reason', '?')}")
            if not args.no_ingest_rejects:
                run(
                    [sys.executable, ROOT / "scripts" / "pb_verdict_corpus.py", gate_path],
                    dry_run=False,
                )

    print("=== evaluated queue gate summary ===")
    print(f"evaluated: {len(candidates)}")
    print(f"accepts: {len(accepts)}")
    for x in accepts:
        print("  ACCEPT", x)
    print(f"archived: {len(archived)}")
    for x in archived:
        print("  ARCHIVE", x)
    print(f"rejects: {len(rejects)}")
    for x in rejects:
        print("  REJECT", x)
    print(f"skipped: {len(skipped)}")
    for x in skipped:
        print("  SKIP", x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
