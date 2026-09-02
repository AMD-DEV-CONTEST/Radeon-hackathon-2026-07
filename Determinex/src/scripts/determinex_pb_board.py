#!/usr/bin/env python3
"""
determinex_pb_board.py -- the honest board
=======================================
Reconciles what eval_index CLAIMS against what the locked archives PROVE, and
classifies every canonical ProgramBench task into one honest bucket. No rounding,
no "score 100 == lock", no trusting a number without its archive.

Buckets:
  VERIFIED_LOCK   -- locked AND its archived eval_report is a clean 100%
                     (passed==total, 0 failed/not_run/skipped).
  STALE_LOCK      -- claims a lock but the archived eval_report is NOT clean 100%
                     (stale/pre-lock archive) -> must re-eval + re-archive or demote.
  NEAR_LOCK       -- not locked, score >= 90% (the conversion targets).
  CEILING_CERT    -- ceiling_certified / upstream_skips (proof-backed, sk>0).
  CEILING_CONF    -- ceiling_confirmed (structural blocker; re-adjudicate).
  MID             -- 40-90% (real work, build+behavioral).
  LOW             -- < 40% (likely build/wrong-version/never-run).
  GATED           -- gated:reject.
  UNKNOWN         -- no usable status.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PBROOT = Path(__file__).resolve().parent.parent / "corpus" / "programbench"
LOCKED = PBROOT / "locked"


def _archive_clean(slug: str) -> tuple[bool, str]:
    """Does this tool's locked archive prove a clean 100%?"""
    cands = []
    if LOCKED.exists():
        for d in LOCKED.iterdir():
            if not d.is_dir():
                continue
            if (
                d.name == slug
                or d.name.split(".")[0] == slug.split(".")[0]
                or d.name.split("__")[-1].split(".")[0] == slug.split("__")[-1].split(".")[0]
            ):
                cands.append(d)
    for d in cands:
        rep = d / "eval_report.json"
        if not rep.exists():
            continue
        try:
            rr = json.loads(rep.read_text(encoding="utf-8")).get("test_results", [])
        except Exception:
            continue
        c = Counter(x.get("status", "?") for x in rr)
        p, tot = c.get("passed", 0), len(rr)
        f = c.get("failure", 0) + c.get("failed", 0)
        nr, sk = c.get("not_run", 0), c.get("skipped", 0)
        if tot > 0 and p == tot and f == 0 and nr == 0 and sk == 0:
            return True, f"{p}/{tot} clean"
        return False, f"{p}/{tot} f={f} nr={nr} sk={sk} (stale/unclean archive)"
    return False, "no archived eval_report"


def classify(e: dict) -> tuple[str, str]:
    st = e.get("status", "")
    pct = e.get("official_score_pct") or 0
    slug = (e.get("slug") or "").replace(".eval", "")
    locked_claim = e.get("official_full_suite_resolved") or st == "strict_lock"
    if locked_claim:
        ok, why = _archive_clean(slug)
        return ("VERIFIED_LOCK" if ok else "STALE_LOCK"), why
    if st in ("ceiling_certified", "upstream_skips"):
        return "CEILING_CERT", f"{pct:.1f}% (proof-backed sk>0)"
    if st == "ceiling_confirmed":
        return "CEILING_CONF", f"{pct:.1f}% (structural blocker)"
    if st == "gated:reject":
        return "GATED", f"{pct:.1f}%"
    if pct >= 90:
        return "NEAR_LOCK", f"{pct:.1f}%"
    if pct >= 40:
        return "MID", f"{pct:.1f}%"
    return "LOW", f"{pct:.1f}% ({st})"


def build_board() -> dict:
    idx = json.loads((PBROOT / "eval_index.json").read_text(encoding="utf-8"))
    ct = json.loads((PBROOT / "canonical_tasks.json").read_text(encoding="utf-8"))
    canon = {t["id"] for t in ct["tasks"]}
    # one entry per canonical tool (prefer the richest match)
    rows = {}
    for e in idx:
        s = (e.get("slug") or "").replace(".eval", "")
        key = None
        for c in canon:
            if (
                c == s
                or c.split(".")[0] == s.split(".")[0]
                or c.split("__")[-1].split(".")[0] == s.split("__")[-1].split(".")[0]
            ):
                key = c
                break
        if not key:
            continue
        bucket, why = classify(e)
        prev = rows.get(key)
        # keep the best (verified > stale; higher score)
        rank = {
            "VERIFIED_LOCK": 9,
            "CEILING_CERT": 7,
            "STALE_LOCK": 6,
            "NEAR_LOCK": 5,
            "MID": 3,
            "CEILING_CONF": 3,
            "GATED": 2,
            "LOW": 1,
            "UNKNOWN": 0,
        }
        if not prev or rank.get(bucket, 0) > rank.get(prev[0], 0):
            rows[key] = (bucket, why, e.get("official_score_pct") or 0)
    return rows


def main() -> int:
    rows = build_board()
    counts = Counter(b for b, _, _ in rows.values())
    order = [
        "VERIFIED_LOCK",
        "STALE_LOCK",
        "CEILING_CERT",
        "CEILING_CONF",
        "NEAR_LOCK",
        "MID",
        "LOW",
        "GATED",
        "UNKNOWN",
    ]
    print("=== HONEST PROGRAMBENCH BOARD ===")
    print(f"canonical tools mapped: {len(rows)}/200")
    for b in order:
        print(f"  {b:14s} {counts.get(b, 0)}")
    print(f"\n  PROVEN LOCKS (clean archive): {counts.get('VERIFIED_LOCK', 0)}")
    print(f"  CLAIMED-BUT-STALE locks (re-archive/demote): {counts.get('STALE_LOCK', 0)}")
    print(f"  NEAR-LOCKS (>=90%, conversion targets): {counts.get('NEAR_LOCK', 0)}")
    # detail the actionable buckets
    for b in ("STALE_LOCK", "NEAR_LOCK"):
        items = sorted([(s, w) for s, (bb, w, p) in rows.items() if bb == b], key=lambda x: x[0])
        print(f"\n--- {b} ({len(items)}) ---")
        for s, w in items[:60]:
            print(f"  {s:42s} {w}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
