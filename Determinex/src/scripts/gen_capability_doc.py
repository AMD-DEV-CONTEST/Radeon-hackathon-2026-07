#!/usr/bin/env python3
"""
gen_capability_doc.py -- render the human-readable capability doc from the map.
Reads corpus/programbench/capability_map.json + verified_locks.json,
writes corpus/programbench/CAPABILITY.md. Lock status is authoritative in the
registry; this doc is a rendering.

Usage:  python scripts/gen_capability_doc.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAP = ROOT / "corpus" / "programbench" / "capability_map.json"
REG = ROOT / "corpus" / "programbench" / "verified_locks.json"
OUT = ROOT / "corpus" / "programbench" / "CAPABILITY.md"


def main() -> int:
    cap = json.loads(CAP.read_text(encoding="utf-8"))
    reg = json.loads(REG.read_text(encoding="utf-8")) if REG.exists() else {"locks": {}}
    s = cap["summary"]
    tools = cap["by_tool"]

    def status_set(st):
        return sorted([t for t, v in tools.items() if v["status"] == st])

    proven, claimed = status_set("PROVEN"), status_set("CLAIMED")
    working, gap = status_set("UNLOCKED_WORKING"), status_set("GAP")

    L = [
        "# Determinex — ProgramBench Full-Capability Map\n",
        f"_Generated {date.today().isoformat()} from `capability_map.json` (schema {cap['schema']}). "
        "Single source of truth for lock status: `verified_locks.json`._\n",
        "> **What this is:** every ProgramBench task, the capability it exercises (language / "
        "eval-reconciliation technique / behavioral surface), and its verification status. A "
        "capability is **PROVEN** only when the tool is a sha-verified clean lock; everything else "
        "is in progress.\n",
        "## Status (the honest count)\n",
        "| Status | Count | Meaning |",
        "|---|---:|---|",
    ]
    sb = s["status_breakdown"]
    meanings = {
        "PROVEN": "sha-verified clean lock (passed==total, 0 not_run/skipped/failed)",
        "CLAIMED": "locked archive exists but unverified (likely degraded record) — re-eval to promote",
        "UNLOCKED_WORKING": "factory/working copy exists, not yet locked",
        "GAP": "no artifact — capability not yet built",
    }
    for st in ("PROVEN", "CLAIMED", "UNLOCKED_WORKING", "GAP"):
        if sb.get(st):
            L.append(f"| {st} | {sb[st]} | {meanings[st]} |")
    L.append(f"| **TOTAL** | **{s['total_tasks']}** | full ProgramBench task universe |\n")

    L += [
        "## Coverage breadth\n",
        f"- **Languages ({len(s['languages_covered'])}):** {', '.join(s['languages_covered'])}",
        f"- **Eval/build techniques ({len(s['techniques_covered'])}):** {', '.join(s['techniques_covered'])}",
        f"- **Behavioral surfaces ({len(s['behaviors_covered'])}):** {', '.join(s['behaviors_covered'])}\n",
    ]

    L.append("## PROVEN locks (canonical, sha-pinned)\n")
    if proven:
        L += [
            "| Tool | Passed/Total | Verified | Languages | Techniques |",
            "|---|---:|---|---|---|",
        ]
        for t in proven:
            e, v = reg["locks"].get(t, {}), tools[t]
            L.append(
                f"| `{t}` | {e.get('passed', '?')}/{e.get('total', '?')} | {e.get('verified_date', '?')} | "
                f"{', '.join(v['languages'])} | {', '.join(v['techniques']) or '—'} |"
            )
        L.append("")
    else:
        L.append("_(none yet)_\n")

    for title, idx in (
        ("Technique coverage (tasks exercising each)", "by_technique"),
        ("Language coverage", "by_language"),
        ("Behavioral surface coverage", "by_behavior"),
    ):
        L += [f"## {title}\n", "| Item | # tasks |", "|---|---:|"]
        for k, v in sorted(cap[idx].items(), key=lambda x: -len(x[1])):
            L.append(f"| {k} | {len(v)} |")
        L.append("")

    L.append("## In-progress (the production line)\n")
    L.append(f"**CLAIMED ({len(claimed)})** — locked archive, awaiting re-verify:\n")
    L.append("> " + ", ".join(f"`{t}`" for t in claimed) + "\n")
    L.append(f"**UNLOCKED_WORKING ({len(working)})** — factory copy, not yet locked:\n")
    L.append("> " + ", ".join(f"`{t}`" for t in working) + "\n")
    if gap:
        L.append(f"**GAP ({len(gap)})** — no artifact: " + ", ".join(f"`{t}`" for t in gap) + "\n")

    L.append(
        "---\n*Regenerate: `python scripts/determinex_pb_capability_map.py build` then "
        "`python scripts/gen_capability_doc.py`. Lock status is authoritative in "
        "`verified_locks.json`; this doc is a rendering.*"
    )
    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
