#!/usr/bin/env python3
"""
determinex_pb_dup_guard.py -- single-source-of-truth: no canonical definition defined twice
=========================================================================================
The taxonomy got duplicated (determinex_pb_fingerprint re-built determinex_pb_taxonomy's mechanism
classes). This makes that IMPOSSIBLE: each canonical name may be DEFINED in exactly one module
(others must import it). Catches "add-on instead of adapt" at commit time. Going forward:
add-to or adapt the owner module; never re-define.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

# canonical names that must live in exactly ONE module (the owner). assignment, not import.
CANONICAL = [
    "FAMILY_PATTERNS",
    "MECHANISMS",
    "EVAL_OVERRIDE_PATTERNS",
    "DiffKind",
    "GAMING",
    "HERMETIC_PLUGIN",
    "DROPPRIV_PLUGIN",
    "MECHANISM_PATTERNS",
]
_DEF = {n: re.compile(rf"^{n}\s*[:=]", re.M) for n in CANONICAL}


def main() -> int:
    owners = defaultdict(list)
    for p in Path("scripts").rglob("*.py"):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for n, rx in _DEF.items():
            if rx.search(t):
                owners[n].append(p.name)
    dups = {n: ms for n, ms in owners.items() if len(ms) > 1}
    if dups:
        print(
            "DUP GUARD FAILED: canonical definition(s) live in >1 module (adapt, don't re-define):"
        )
        for n, ms in dups.items():
            print(f"  {n}: defined in {ms} -- keep ONE owner, others import it")
        return 1
    print(f"dup guard: clean ({len(owners)} canonical defs, each single-owner)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
