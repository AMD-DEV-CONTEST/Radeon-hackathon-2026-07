#!/usr/bin/env python3
"""determinex_pb_whale_board.py -- live scoreboard for the whale-build campaign.

Reads each whale's freshest eval_report.json (written by determinex_pb_whale_build) +
its recipe, prints one perspective table: passed/total, %, verdict, top blocker.
Run anytime; it just reflects what's on disk.
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
OV = PB / "per_tool_overrides"


def _stat(slug: str) -> dict:
    rep = OV / slug / "eval_report.json"
    if not rep.exists():
        return {"verdict": "QUEUED", "passed": 0, "total": 0, "pct": 0.0, "blk": ""}
    try:
        d = json.loads(rep.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {"verdict": "READERR", "passed": 0, "total": 0, "pct": 0.0, "blk": ""}
    tr = d.get("test_results", [])
    c = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    p = c.get("passed", 0)
    fail = c.get("failure", 0) + c.get("failed", 0) + c.get("error", 0)
    nr = c.get("not_run", 0)
    rc127 = sum(1 for r in tr if "127" in str((r.get("extra") or {}).get("text", ""))[:160])
    pct = 100.0 * p / total if total else 0.0
    if total == 0:
        v = "NO-EVAL"
    elif p == total:
        v = "LOCK*"
    elif rc127 > 0.3 * total or p < 0.10 * total:
        v = "BUILD-FAIL"
    else:
        v = "BUILDS"
    blk = f"127x{rc127}" if rc127 else (f"nr{nr}" if nr else (f"fail{fail}" if fail else ""))
    return {"verdict": v, "passed": p, "total": total, "pct": pct, "blk": blk}


def main() -> int:
    kb = json.loads((PB / "build_knowledge.json").read_text(encoding="utf-8"))
    whales = kb.get("whale_base_toolchains_2026_06_23", {}).get("whales", {})
    rows = []
    for slug, r in whales.items():
        s = _stat(slug)
        rows.append((slug.split("__")[-1].split(".")[0], r.get("sys", ""), s))
    rows.sort(key=lambda x: (-x[2]["pct"], x[0]))
    print(f"  {'whale':16s} {'sys':12s} {'passed/total':>14s} {'%':>6s}  {'verdict':11s} blocker")
    print("  " + "-" * 72)
    for name, sysn, s in rows:
        pt = f"{s['passed']}/{s['total']}" if s["total"] else "-"
        print(f"  {name:16s} {sysn:12s} {pt:>14s} {s['pct']:5.1f}%  {s['verdict']:11s} {s['blk']}")
    builds = sum(1 for _, _, s in rows if s["verdict"] in ("BUILDS", "LOCK*"))
    print("  " + "-" * 72)
    print(
        f"  {builds}/{len(rows)} whales building; "
        f"{sum(1 for _, _, s in rows if s['verdict'] == 'LOCK*')} at 100%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
