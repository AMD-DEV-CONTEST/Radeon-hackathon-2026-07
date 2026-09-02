#!/usr/bin/env python3
"""Refresh the RAG corpus index after a ProgramBench accepted gate.

Invokes:
  python scripts/seed_knowledge_base.py --programbench-only --reseed-programbench

The seeder now refreshes:
  - corpus/programbench/**/*.md
  - logs/programbench_factory/**/*.md
  - logs/programbench_failure_inventory/**/*.md

`--dry-run` reports the command and scope without invoking the seeder.
"""

from __future__ import annotations

import argparse
import datetime
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "scripts" / "seed_knowledge_base.py"
FACTORY_DIR = ROOT / "logs" / "programbench_factory"
ACCEPTED_JSONL = FACTORY_DIR / "accepted_runs.jsonl"
PROGRAMBENCH_CORPUS = ROOT / "corpus" / "programbench"
INVENTORY_DIR = ROOT / "logs" / "programbench_failure_inventory"

RAG_SCOPE = """\
RAG refresh scope:
  - corpus/programbench/**/*.md
  - logs/programbench_factory/**/*.md
  - logs/programbench_failure_inventory/**/*.md
"""


def _run(cmd: list[str], dry_run: bool, label: str) -> int:
    """Run a subprocess, or print it in dry-run. Returns its exit code."""
    print(f"$ {label}: {' '.join(cmd)}")
    if dry_run:
        print("  (dry-run; not executed)")
        return 0
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT))
        return proc.returncode
    except Exception as e:
        sys.stderr.write(f"  subprocess error: {type(e).__name__}: {e}\n")
        return 99


def _count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="report commands and refresh scope without invoking the seeder",
    )
    ap.add_argument(
        "--python", default=sys.executable, help="Python interpreter for the seed subprocess"
    )
    ap.add_argument(
        "--require-accepted-run",
        action="store_true",
        help="only refresh when accepted_runs.jsonl has at least one row",
    )
    args = ap.parse_args()

    print(
        "# pb_refresh_rag_after_accept "
        f"({datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')})"
    )
    print(f"  seed script:               {SEED_SCRIPT}")
    print(f"  accepted_runs.jsonl:       {ACCEPTED_JSONL}")
    print(f"  programbench corpus root:  {PROGRAMBENCH_CORPUS}")
    print(f"  factory log root:          {FACTORY_DIR}")
    print(f"  inventory root:            {INVENTORY_DIR}")
    print()

    accepted_n = _count_jsonl(ACCEPTED_JSONL)
    print(f"accepted_runs.jsonl rows: {accepted_n}")

    if args.require_accepted_run and accepted_n == 0:
        print("no accepted runs to back the refresh; exiting.")
        return 0

    print()
    print(RAG_SCOPE)
    print()

    cmd = [args.python, str(SEED_SCRIPT), "--programbench-only", "--reseed-programbench"]
    rc = _run(cmd, dry_run=args.dry_run, label="reseed ProgramBench corpus and factory logs")
    if rc != 0:
        sys.stderr.write(f"seed script returned exit={rc}\n")
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
