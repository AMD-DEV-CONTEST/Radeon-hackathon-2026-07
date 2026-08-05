#!/usr/bin/env python3
"""
determinex_pb_triage.py -- adjudicator-as-router: don't grind the unreachable (priority D)
=======================================================================================
For every not-locked tool, decide EARLY where compute goes, from its fingerprint:

  AUTOFIX   residual is mostly MECH-class with a BUILT fixer  -> apply technique, cheap, do now
  AMPLIFY   residual is SAMPLE/SOLVE and f-evidence > 0        -> pour compute (best-of-K / decompose)
  OPUS      genuine-missing/semantic, no mechanism, p unclear  -> hand-loop: Opus context + corpus verify
  CEILING   upstream-skip / proven unprovisionable             -> certify w/ evidence, STOP grinding

The point (your insight): keeping p≈0 walls OUT of the grind is half of what keeps the curve
climbing. A tool whose residual is all upstream-skips is DONE-as-ceiling, not a target. A tool
with f=0 + only MECH residual is a cheap autofix. Only the genuine SAMPLE/SOLVE tail gets the
expensive compute. This routes effort to where p>0 and parks where p≈0.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import determinex_pb_fingerprint as FP  # noqa: E402

# techniques with a fixer BUILT today (vs mapped-but-unbuilt)
BUILT = {
    "bidir-mirror",
    "crlf-normalize",
    "build-fail-routing",
    "drop-privileges",
    "hermetic-clock",
    "hermetic-locale",
    "hermetic-path-canon",
    "hermetic-seed",
    "canonical-sort-compare",
    "hermetic-no-network",
}
CEILING_TECH = {"ceiling-cert"}


def triage_tool(report_path: Path) -> dict:
    try:
        tr = json.loads(report_path.read_text(encoding="utf-8")).get("test_results", [])
    except Exception:
        return {"route": "NODATA"}

    def _ident(n):
        return n.split("::")[-1] if "::" in n else n.split(".")[-1]

    passed = {_ident(x.get("name", "")) for x in tr if x.get("status") == "passed"}
    resid = [x for x in tr if x.get("status") != "passed"]
    if not resid:
        return {"route": "LOCK", "residual": 0}
    n_fail = sum(1 for x in resid if x.get("status") in ("failed", "error"))
    mechs = Counter()
    built = 0
    ceiling = 0
    sample = 0
    for x in resid:
        fp = FP.fingerprint_test(x, passed)
        mechs[fp.mechanism] += 1
        if fp.technique in BUILT:
            built += 1
        elif fp.technique in CEILING_TECH:
            ceiling += 1
        elif fp.p_hint in ("SAMPLE", "SOLVE"):
            sample += 1
    total = len(resid)
    # decision: dominant disposition
    if built / total >= 0.6:
        route = "AUTOFIX"  # cheap, do now
    elif ceiling / total >= 0.6:
        route = "CEILING"  # certify, stop grinding
    elif n_fail > 0 and sample / total >= 0.4:
        route = "AMPLIFY"  # real failures w/ p>0 -> pour compute
    else:
        route = "OPUS"  # genuine-missing/semantic -> hand-loop
    return {
        "route": route,
        "residual": total,
        "built": built,
        "ceiling": ceiling,
        "sample": sample,
        "failures": n_fail,
        "top_mech": mechs.most_common(3),
    }


def main() -> int:
    roots = sys.argv[1:] or ["C:/tmp/all_reports"]
    buckets = Counter()
    detail = {}
    for root in roots:
        for jf in Path(root).glob("*.eval.json"):
            if jf.name.startswith("LOCKED_"):
                continue
            t = triage_tool(jf)
            buckets[t["route"]] += 1
            detail.setdefault(t["route"], []).append(jf.stem.split("__")[-1])
    print("=== EARLY TRIAGE ROUTING (where compute goes) ===")
    order = ["AUTOFIX", "AMPLIFY", "OPUS", "CEILING", "LOCK", "NODATA"]
    for r in order:
        if buckets.get(r):
            tools = sorted(set(detail.get(r, [])))
            print(f"  {r:8s} {buckets[r]:3d} tools  e.g. {tools[:6]}")
    print("\n  -> AUTOFIX = cheap technique now | AMPLIFY = pour compute (p>0) |")
    print("     OPUS = hand-loop genuine tail | CEILING = certify, don't grind")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
