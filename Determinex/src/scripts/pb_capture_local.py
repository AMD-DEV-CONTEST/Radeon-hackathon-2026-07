#!/usr/bin/env python3
"""Autonomous PRIVATE score-capture: pull the box's best eval_reports into the repo and commit
LOCALLY ONLY -- never push. The eval results stay on this machine + the box (both private); nothing
goes to a remote anyone else can see (operator mandate 2026-06-29). Run by a scheduled task every
~30min so box7's results are continuously captured + the BEST per tool is kept (pb_sync.capture_scores
already does the best-eval merge). Pairs with determinex_pb_autodrive._persist_best (the box keeps its
own best) -- this brings that best down to the durable repo.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import pb_sync  # noqa: E402


def main() -> int:
    pb_sync.capture_scores()  # scp box -> repo (best-eval), git-add the changed score files
    # commit ONLY what capture_scores staged (the score .json); NEVER push (privacy mandate).
    staged = subprocess.run(["git", "-C", str(REPO), "diff", "--cached", "--quiet"]).returncode
    if staged != 0:
        msg = f"PB: auto-capture box eval scores (best-eval, LOCAL-ONLY) {time.strftime('%Y-%m-%d %H:%M')}"
        subprocess.run(["git", "-C", str(REPO), "commit", "-m", msg], check=False)
        print("committed locally (no push -- private)")
    else:
        print("nothing new to capture")
    # SYNC the absorbed + flywheel-learned knowledge DOWN to the box so box7's grounded fixer applies
    # it. scp is read-only of local (no race with the absorber); capture_scores already merged the
    # box's flywheel-learned UP, so local is the superset -> safe to push the whole file.
    try:
        kn = REPO / "corpus" / "programbench" / "build_knowledge.json"
        if kn.exists():
            subprocess.run(
                [
                    "scp",
                    "-i",
                    pb_sync.KEY,
                    str(kn),
                    f"{pb_sync.BOX}:{pb_sync.BOX_ROOT}/corpus/programbench/build_knowledge.json",
                ],
                check=False,
                timeout=90,
            )
            print("deployed build_knowledge (absorbed+learned) -> box (box7 fixer applies it)")
    except Exception as e:
        print(f"knowledge deploy skipped: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
