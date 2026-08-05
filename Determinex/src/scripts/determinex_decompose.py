#!/usr/bin/env python3
"""
determinex_decompose.py -- Adaptive Decomposer (Amplifier piece #2)
================================================================
A weak model cannot solve a big task in one shot, but it can solve a small one.
This splits a task into independently-verifiable LEAVES, sized to the model's
capability: a tiny model gets one-check leaves; a frontier model gets coarse
leaves. Each leaf carries its OWN oracle slice (the exact checks that verify it),
so VerifiedSearch can drive each leaf to a passing oracle independently and the
whole task assembles from verified parts.

The decomposition is by verification unit: checks/tests that exercise the same
module/unit are grouped, then groups are capped at the capability's max leaf
size. This is deterministic and works on any oracle that exposes named checks
(pytest nodeids, compiler error sites, type errors, ...).

    from determinex_decompose import decompose, Capability
    leaves = decompose(test_ids, capability=Capability.TINY)   # 1 check / leaf
    for leaf in leaves:
        # run VerifiedSearch with an oracle restricted to leaf.check_ids
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum


class Capability(int, Enum):
    TINY = 1  # ~1.5B local: one check per leaf
    SMALL = 5  # ~7B: a few related checks
    MEDIUM = 20  # mid model
    LARGE = 100  # frontier: coarse leaves
    WHOLE = 100000  # no decomposition


@dataclass
class Leaf:
    unit: str  # the unit these checks share (module/file/symbol)
    check_ids: list[str] = field(default_factory=list)
    rationale: str = ""

    @property
    def size(self) -> int:
        return len(self.check_ids)


def _unit_of(check_id: str) -> str:
    """Group key: strip the leaf test name, keep the module/class path. Works for
    pytest nodeids (a.b.test_x), compiler sites (path:line), etc."""
    cid = check_id
    for pre in ("eval.tests.", "eval/tests/", "tests.", "tests/"):
        if cid.startswith(pre):
            cid = cid[len(pre) :]
    cid = cid.replace("/", ".")
    parts = cid.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:-1])  # drop the final test name -> the module/class
    # compiler-style path:line -> the file
    m = re.match(r"(.+?):\d+", cid)
    return m.group(1) if m else cid


def decompose(check_ids: list[str], capability: Capability | int = Capability.SMALL) -> list[Leaf]:
    cap = int(capability)
    if cap >= int(Capability.WHOLE):
        return [
            Leaf(
                unit="<whole>",
                check_ids=list(check_ids),
                rationale="no decomposition (capable model)",
            )
        ]
    by_unit: dict[str, list[str]] = defaultdict(list)
    for cid in check_ids:
        by_unit[_unit_of(cid)].append(cid)
    leaves: list[Leaf] = []
    for unit, ids in sorted(by_unit.items()):
        # split each unit's checks into chunks of <= cap
        for i in range(0, len(ids), cap):
            chunk = ids[i : i + cap]
            leaves.append(
                Leaf(
                    unit=unit,
                    check_ids=chunk,
                    rationale=f"{len(chunk)} checks from unit '{unit}' "
                    f"(capped at {cap} for capability)",
                )
            )
    return leaves


def recommend_capability(model_hint: str) -> Capability:
    """Map a model name/size hint to a leaf-size capability. Smaller -> finer."""
    h = model_hint.lower()
    if any(s in h for s in ("1.5b", "1b", "tiny", "0.5b", "qwen2.5-coder:1")):
        return Capability.TINY
    if any(s in h for s in ("3b", "7b", "8b", "small", "mini", "haiku")):
        return Capability.SMALL
    if any(s in h for s in ("13b", "14b", "32b", "medium", "sonnet")):
        return Capability.MEDIUM
    if any(s in h for s in ("70b", "opus", "gpt-5", "deepseek", "frontier", "large")):
        return Capability.LARGE
    return Capability.SMALL


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Adaptive Decomposer")
    ap.add_argument("--checks", nargs="+", required=True, help="check/test ids")
    ap.add_argument("--capability", default="SMALL", choices=[c.name for c in Capability])
    args = ap.parse_args()
    leaves = decompose(args.checks, Capability[args.capability])
    print(f"{len(leaves)} leaves at capability {args.capability}:")
    for leaf in leaves:
        print(
            f"  [{leaf.size}] {leaf.unit}: {', '.join(leaf.check_ids[:5])}"
            + (" ..." if leaf.size > 5 else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
