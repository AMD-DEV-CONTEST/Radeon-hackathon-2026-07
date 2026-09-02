#!/usr/bin/env python3
"""determinex_pb_climb_audit.py -- the full corpus-driven climb map: see every tool's real score
(from eval_index = all official evals), gate each by PROVENANCE (legit native reimpl vs the
forbidden shortcut), classify what each non-100 tool still needs, and rank the LEGIT ones by
closeness to 100. So the grind machine knows the honest legit-lock count + exactly what's close
+ what each needs to climb -- and never grinds a fake.

Composes: eval_index.json (scores) + determinex_pb_nr_classify._is_legit_reimpl (provenance) +
the not_run-cause / failure split (what-it-needs). Read-only; no Docker.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path("/root/Citadel")
PB = ROOT / "corpus" / "programbench"
OVR = PB / "per_tool_overrides"
LOCKED = PB / "locked"
sys.path.insert(0, str(ROOT / "scripts"))


def _canon_short(name: str) -> str:
    """Canonical short tool name from any dir/slug form."""
    n = str(name).strip().split("\t")[-1].strip()
    n = re.sub(r"\.(tar\.gz|eval|json)$", "", n)
    n = re.sub(r"_(native|model|cleanroom\w*)$", "", n)
    n = n.split("__")[-1]  # owner__repo -> repo[.hash]
    n = re.sub(r"[.\-][0-9a-f]{6,}$", "", n)  # drop trailing .hash / -hash
    return n.lower()


def _build_short2dir():
    m = {}
    for base in (OVR, LOCKED):
        if not base.is_dir():
            continue
        for d in base.iterdir():
            if d.is_dir():
                m.setdefault(_canon_short(d.name), d.name)
    return m


_SHORT2DIR = _build_short2dir()


def _full_slug(row: dict) -> str | None:
    """eval_index slug -> canonical owner__repo.hash (or short) dir, folding alias artifacts."""
    erp = row.get("eval_report_path") or ""
    if erp:
        b = os.path.basename(os.path.dirname(erp.replace("\\", "/")))
        if b and (OVR / b).exists() or (LOCKED / b).exists():
            return b
    sl = row.get("slug", "")
    return _SHORT2DIR.get(_canon_short(sl))


def _compile_text(full: str) -> str:
    for cand in (
        OVR / full / "compile.sh",
        LOCKED / full / "compile.sh",
        LOCKED / full / "source" / "compile.sh",
    ):
        if cand.exists():
            return cand.read_text(encoding="utf-8", errors="replace").lower()
    return ""


def _legit(full: str | None) -> bool | None:
    if not full:
        return None
    t = _compile_text(full)
    if not t:
        return None
    if any(
        m in t
        for m in (
            "canonical upstream",
            "from task image",
            "do not cargo",
            "do not build",
            "prebuilt binary",
            "bundled binary",
            "answer-key",
        )
    ):
        return False
    return (
        ("reimpl" in t)
        or ("reverse-engineered" in t)
        or ("reverse engineered" in t)
        or (
            "native rebuild" not in t
            and any(b in t for b in ("cargo build", "go build", "rustc", "gcc ", "g++ ", "make "))
        )
    )


def _score(row: dict):
    p = row.get("official_passed", row.get("passed", 0)) or 0
    tot = row.get("official_total", row.get("total", 0)) or 0
    nr = row.get("official_not_run", row.get("not_run", 0)) or 0
    fa = row.get("official_failed", 0) or 0
    return p, tot, nr, fa


def needs(p, tot, nr, fa) -> str:
    if tot == 0:
        return "no-eval"
    if p == tot:
        return "LOCK"
    if nr >= fa and nr > 0:
        return ("build-complete" if p == 0 else "fix-collection") + f"(nr={nr})"
    if fa > 0:
        return f"behavioral byte-match(fail={fa})"
    return f"gap={tot - p}"


def main() -> None:
    rows = json.load(open(PB / "eval_index.json", encoding="utf-8"))
    seen = set()
    tools = []
    for r in rows:
        full = _full_slug(r)
        key = full or r.get("slug")
        if key in seen:
            continue
        seen.add(key)
        p, tot, nr, fa = _score(r)
        if tot == 0:
            continue
        pct = 100 * p / tot
        tools.append(
            {
                "slug": full or r.get("slug"),
                "legit": _legit(full),
                "p": p,
                "tot": tot,
                "nr": nr,
                "fa": fa,
                "pct": pct,
                "needs": needs(p, tot, nr, fa),
            }
        )

    legit = [t for t in tools if t["legit"] is True]
    fake = [t for t in tools if t["legit"] is False]
    unk = [t for t in tools if t["legit"] is None]
    locks_all = [t for t in tools if t["pct"] >= 100]
    legit_locks = [t for t in legit if t["pct"] >= 100]
    legit_near = sorted([t for t in legit if 90 <= t["pct"] < 100], key=lambda t: -t["pct"])
    legit_climb = sorted([t for t in legit if t["pct"] < 90], key=lambda t: -t["pct"])

    print("=" * 78)
    print(f"PB CLIMB AUDIT  |  {len(tools)} tools w/ evals")
    print(f"  claimed 100% (all):     {len(locks_all)}")
    print(
        f"  LEGIT reimpl tools:     {len(legit)}   fakes(upstream/shipped): {len(fake)}   unknown: {len(unk)}"
    )
    print(f"  >> LEGIT @100% (real locks): {len(legit_locks)}")
    print(f"  >> LEGIT near-lock 90-99%:   {len(legit_near)}  <- closest climb targets")
    print(f"  >> LEGIT climbing  <90%:     {len(legit_climb)}")
    print("=" * 78)
    print("\nLEGIT NEAR-LOCKS (climb these first -- ranked by closeness):")
    print(f"  {'pct':>6} {'passed/total':>14}  {'needs':<34} slug")
    for t in legit_near[:25]:
        print(
            f"  {t['pct']:5.1f}% {str(t['p']) + '/' + str(t['tot']):>14}  {t['needs'][:33]:<34} {t['slug']}"
        )
    if not legit_near:
        print("  (none in 90-99% -- legit tools are either locked or <90%)")
    print(f"\nLEGIT CLIMBING <90% (top {min(10, len(legit_climb))} by score):")
    for t in legit_climb[:10]:
        print(
            f"  {t['pct']:5.1f}% {str(t['p']) + '/' + str(t['tot']):>14}  {t['needs'][:33]:<34} {t['slug']}"
        )


if __name__ == "__main__":
    main()
