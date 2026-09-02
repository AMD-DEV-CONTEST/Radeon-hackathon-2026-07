#!/usr/bin/env python3
"""determinex_pb_nr_classify.py -- the missing piece: classify a tool's not_run into the 4 causes the
corpus identified (not_run_taxonomy_2026_06_23), each with a DIFFERENT fix, so the system stops
mislabeling everything 'remove-cap' and routes each tool to the fix that actually snaps it.

  build_fully_failed         (passed==0, not_run>0)        -> COMPLETE THE BUILD (no binary -> 0 ran)
  build_partial_collection   (passed>0, not_run big chunk) -> FIX COLLECTION (test module import/data)
  literal_collection_cap     (conftest del items[N:])      -> REMOVE CAP + re-eval
  stale_drifted_report       (locked archive >> working)   -> RE-EVAL (fresh pack), zero code

Produces the ranked SNAP QUEUE: which tool, which cause, which fix, how many tests it unlocks.
Reads existing eval reports (no Docker). Composes with determinex_pb_triage (cause -> its router lane).
"""

from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path("/root/Citadel")
OVR = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOCKED = ROOT / "corpus" / "programbench" / "locked"


def _score(path: str):
    try:
        d = json.load(open(path))
        tr = d.get("test_results", d.get("results", []))
        c = collections.Counter(t.get("status") for t in tr)
        return c.get("passed", 0), c.get("not_run", 0), len(tr)
    except Exception:
        return None


def _has_cap(slug: str) -> bool:
    cs = OVR / slug / "compile.sh"
    if not cs.exists():
        return False
    txt = cs.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r"del items\[\d*:\d*\]|items\[:\d+\]|items\[\d+:\]", txt))


def _is_legit_reimpl(slug: str) -> bool:
    cs = OVR / slug / "compile.sh"
    if not cs.exists():
        return False
    t = cs.read_text(encoding="utf-8", errors="replace").lower()
    if any(
        m in t
        for m in (
            "canonical upstream",
            "from task image",
            "do not cargo",
            "do not build",
            "prebuilt binary",
            "bundled binary",
        )
    ):
        return False
    return ("reimpl" in t) or ("reverse-engineered" in t) or ("reverse engineered" in t)


def classify(slug: str) -> dict | None:
    work = glob.glob(str(OVR / slug / "*.eval.json"))
    arch = glob.glob(str(LOCKED / slug / "eval_report.json")) + glob.glob(
        str(LOCKED / f"{slug}*" / "eval_report.json")
    )
    ws = _score(max(work, key=os.path.getmtime)) if work else None
    as_ = _score(max(arch, key=os.path.getmtime)) if arch else None
    if not ws and not as_:
        return None
    legit = _is_legit_reimpl(slug)
    p, nr, tot = ws or as_
    if tot == 0:
        return None
    # stale_drifted: a locked archive scores much better than the working eval
    if as_ and ws and as_[0] - ws[0] >= max(20, int(0.05 * tot)):
        return {
            "slug": slug,
            "cause": "stale_drifted_report",
            "fix": "re-eval (fresh pack_submission)",
            "unlocks": as_[0] - ws[0],
            "passed": p,
            "not_run": nr,
            "total": tot,
            "effort": "zero-code",
            "legit": legit,
        }
    if nr == 0:
        return None
    if p == 0:
        return {
            "slug": slug,
            "cause": "build_fully_failed",
            "fix": "complete the build (no binary -> 0 ran)",
            "unlocks": nr,
            "passed": p,
            "not_run": nr,
            "total": tot,
            "effort": "build-fix",
            "legit": legit,
        }
    if _has_cap(slug):
        return {
            "slug": slug,
            "cause": "literal_collection_cap",
            "fix": "remove del items cap + re-eval",
            "unlocks": nr,
            "passed": p,
            "not_run": nr,
            "total": tot,
            "effort": "trivial",
            "legit": legit,
        }
    return {
        "slug": slug,
        "cause": "build_partial_collection",
        "fix": "fix erroring test module (import/data/feature)",
        "unlocks": nr,
        "passed": p,
        "not_run": nr,
        "total": tot,
        "effort": "per-module",
        "legit": legit,
    }


def main() -> int:
    slugs = sys.argv[1:] or sorted(
        {os.path.basename(os.path.dirname(p)) for p in glob.glob(str(OVR / "*" / "*.eval.json"))}
    )
    rows = [r for s in slugs if (r := classify(s))]
    rows.sort(key=lambda r: -r["unlocks"])
    by = collections.Counter(r["cause"] for r in rows)
    print(f"=== not_run SNAP QUEUE: {len(rows)} tools | by cause: {dict(by)} ===")
    print(f"{'unlocks':>8}  {'effort':<12} {'cause':<26} {'fix':<42} slug")
    for r in rows[:40]:
        print(
            f"{r['unlocks']:>8}  {r['effort']:<12} {r['cause']:<26} {r['fix'][:40]:<42} {r['slug']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
