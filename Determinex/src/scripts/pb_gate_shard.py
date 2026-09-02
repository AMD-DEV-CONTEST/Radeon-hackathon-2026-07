#!/usr/bin/env python3
"""Gate every imported result from a Hetzner shard return.

For each run_root under <shard_dir>/runs/* that has an eval.json:
  1. pb_candidate_gate against the current board baseline
  2. pb_verdict_corpus ingest
  3. If accept: pb_apply_gate_decision --refresh-board
  4. If candidate is 100% (passed == runnable, no failures): archive lock

Usage:
    python scripts/pb_gate_shard.py .determinex_staging/hetzner_returns/hetzner_native_002
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"


def load_board() -> dict[str, dict]:
    b = json.loads(BOARD.read_text(encoding="utf-8"))
    return {e["base_slug"]: e for e in b if "base_slug" in e}


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: pb_gate_shard.py <shard_dir>", file=sys.stderr)
        return 2
    shard_dir = Path(sys.argv[1])
    runs_dir = shard_dir / "runs"
    if not runs_dir.is_dir():
        print(f"no runs/ dir in {shard_dir}", file=sys.stderr)
        return 2

    accepts: list[str] = []
    rejects: list[tuple[str, str]] = []
    archived: list[str] = []
    errors: list[tuple[str, str]] = []

    for run_root in sorted(runs_dir.iterdir()):
        if not run_root.is_dir():
            continue
        # Find the slug dir + eval.json inside
        slug_dirs = [d for d in run_root.iterdir() if d.is_dir()]
        if not slug_dirs:
            continue
        slug_dir = slug_dirs[0]
        slug = slug_dir.name
        eval_path = slug_dir / f"{slug}.eval.json"
        if not eval_path.is_file():
            print(f"[skip] {slug}: no eval.json")
            continue

        base_slug = slug.split(".", 1)[0]
        board = load_board()
        e = board.get(base_slug)
        if not e:
            print(f"[skip] {slug}: not in board")
            continue
        baseline = e.get("best_eval_path")
        if not baseline or not Path(baseline).is_file():
            print(f"[skip] {slug}: no baseline_eval")
            continue

        # Run gate
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "pb_candidate_gate.py"),
            slug,
            str(run_root),
            "--baseline-eval",
            baseline,
            "--min-baseline-passed",
            "1",
            "--skip-eval",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        gate_json = run_root / "gate_result.json"
        if not gate_json.is_file():
            errors.append((slug, "gate produced no gate_result.json"))
            continue
        try:
            g = json.loads(gate_json.read_text(encoding="utf-8"))
        except Exception as ex:
            errors.append((slug, f"gate_result parse: {ex}"))
            continue

        # Always ingest verdicts
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "pb_verdict_corpus.py"), str(gate_json)],
            capture_output=True,
            text=True,
        )

        decision = g.get("decision")
        cand_passed = g.get("candidate_passed", 0)
        base_passed = g.get("baseline_passed", 0)

        if decision == "accept":
            # Apply
            apply_cmd = [
                sys.executable,
                str(ROOT / "scripts" / "pb_apply_gate_decision.py"),
                slug,
                str(gate_json),
                "--run-root",
                str(run_root),
                "--refresh-board",
            ]
            ap = subprocess.run(
                apply_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if ap.returncode != 0:
                errors.append((slug, f"apply rc={ap.returncode}: {ap.stderr[:200]}"))
                continue
            accepts.append(
                f"{slug}: +{cand_passed - base_passed} ({cand_passed}/{e.get('best_runnable_total')})"
            )

            # Check 100% archive eligibility
            ev = json.loads(eval_path.read_text(encoding="utf-8", errors="replace"))
            counts: dict[str, int] = {}
            for t in ev.get("test_results", []):
                s = t.get("status")
                counts[s] = counts.get(s, 0) + 1
            runnable = counts.get("passed", 0) + counts.get("failure", 0) + counts.get("error", 0)
            if counts.get("passed", 0) == runnable and runnable > 0:
                archive_cmd = [
                    sys.executable,
                    str(ROOT / "scripts" / "pb_lock_archiver.py"),
                    slug,
                    str(eval_path),
                    str(run_root),
                    "--confirm-100",
                    "--execute",
                ]
                ar = subprocess.run(
                    archive_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
                )
                if ar.returncode == 0:
                    archived.append(slug)
                else:
                    errors.append((slug, f"archive rc={ar.returncode}"))
        else:
            reason = g.get("reason", "?")[:90]
            rejects.append((slug, reason))

    print("\n=== shard gate summary ===")
    print(f"accepts: {len(accepts)}")
    for a in accepts:
        print(f"  ACCEPT {a}")
    print(f"archived 100%: {len(archived)}")
    for a in archived:
        print(f"  ARCHIVE {a}")
    print(f"rejects: {len(rejects)}")
    for s, r in rejects:
        print(f"  REJECT {s}: {r}")
    if errors:
        print(f"errors: {len(errors)}")
        for s, r in errors:
            print(f"  ERR {s}: {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
