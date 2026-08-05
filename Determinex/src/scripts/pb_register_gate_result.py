#!/usr/bin/env python3
"""Register an accepted gate result into the factory's durable JSONL index.

This is a REGISTRY, not a lock archiver. It does NOT:
  - copy any submission tarball
  - touch `corpus/programbench/locked/*`
  - claim a 100/100 lock
  - rewrite `logs/programbench_lock_board.json` (unless `--refresh-board`)

It DOES:
  - verify `gate_result.json.decision == "accept"`
  - append one JSONL row to `logs/programbench_factory/accepted_runs.jsonl`
  - (optional) call `scripts/pb_score_audit.py` to refresh the board after

The JSONL row format:
{
  "slug": "...",
  "timestamp": "2026-05-19T09:00:00Z",
  "baseline_eval": "...",
  "candidate_eval": "...",
  "baseline_passed": 516,
  "candidate_passed": 519,
  "delta_passed": 3,
  "candidate_runnable": 703,
  "newly_passing": [...],
  "newly_failing": [...],
  "run_root": "...",
  "executable_hash": "...",
  "commit_sha": "..."   # if git rev-parse HEAD succeeds; else null
}

Usage:
  python scripts/pb_register_gate_result.py konradsz__igrep.aa75630 \\
      .determinex_staging/pb_igrep_c4_revert/gate_result.json

  python scripts/pb_register_gate_result.py konradsz__igrep.aa75630 \\
      .determinex_staging/pb_igrep_c4_revert/gate_result.json \\
      --promote-run-root .determinex_staging/pb_igrep_c4_revert \\
      --refresh-board
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
ACCEPTED_JSONL = FACTORY_DIR / "accepted_runs.jsonl"
REFRESH_LOG = FACTORY_DIR / "board_refresh.log"


def _git_head_sha() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or None
    except Exception:
        pass
    return None


def _load_gate(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"gate_result.json not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"could not parse gate_result.json: {e}")


def append_row(row: dict[str, Any]) -> Path:
    ACCEPTED_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with ACCEPTED_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return ACCEPTED_JSONL


def refresh_board(py: str) -> Path:
    """Invoke pb_score_audit.py and capture stdout/stderr to REFRESH_LOG."""
    REFRESH_LOG.parent.mkdir(parents=True, exist_ok=True)
    cmd = [py, str(ROOT / "scripts" / "pb_score_audit.py")]
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    proc = subprocess.run(
        cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    ended = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    payload = (
        f"[refresh started {started}]\n"
        f"$ {' '.join(cmd)}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
        f"[refresh ended {ended}, rc={proc.returncode}]\n\n"
    )
    with REFRESH_LOG.open("a", encoding="utf-8") as f:
        f.write(payload)
    return REFRESH_LOG


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slug", help="ProgramBench instance id, e.g. owner__repo.hash")
    ap.add_argument("gate_result", type=Path, help="path to gate_result.json")
    ap.add_argument(
        "--promote-run-root",
        type=Path,
        default=None,
        help="record this run_root in the registry row (does NOT copy anything)",
    )
    ap.add_argument(
        "--refresh-board",
        action="store_true",
        help="also invoke scripts/pb_score_audit.py to refresh the lock board",
    )
    ap.add_argument(
        "--python", default=sys.executable, help="Python interpreter for sub-script invocations"
    )
    args = ap.parse_args()

    gate = _load_gate(args.gate_result)
    decision = str(gate.get("decision", "")).lower()
    if decision != "accept":
        sys.stderr.write(
            f"refusing to register: decision={decision!r}. Registry only records accepted runs.\n"
        )
        return 2

    baseline = gate.get("baseline") or {}
    candidate = gate.get("candidate") or {}
    delta = gate.get("delta") or {}

    run_root = (
        str(args.promote_run_root) if args.promote_run_root else gate.get("candidate_run_root", "")
    )

    row = {
        "slug": args.slug,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "baseline_eval": baseline.get("eval_path"),
        "candidate_eval": candidate.get("eval_path"),
        "baseline_passed": baseline.get("passed"),
        "candidate_passed": candidate.get("passed"),
        "baseline_runnable": baseline.get("runnable"),
        "candidate_runnable": candidate.get("runnable"),
        "delta_passed": delta.get("passed"),
        "delta_runnable": delta.get("runnable"),
        "newly_passing": delta.get("newly_passing") or [],
        "newly_failing": delta.get("newly_failing") or [],
        "executable_hash": candidate.get("executable_hash"),
        "run_root": run_root,
        "gate_result_path": str(args.gate_result),
        "commit_sha": _git_head_sha(),
    }
    out = append_row(row)
    print(f"appended row to {out}")

    if args.refresh_board:
        log = refresh_board(args.python)
        print(f"refreshed board; log appended at {log}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
