#!/usr/bin/env python3
"""
determinex_case_memory.py -- Solution Retrieval / Case Memory (Amplifier piece #3)
===============================================================================
Determinex already turns every verified fix into a training pair (the flywheel).
But training is offline; a weak model needs the verified fix RIGHT NOW, at
inference. This is the case memory: a store of (failure-signature -> verified
solution) cases, retrievable by similarity, so a new failure is solved by analogy
to a past one that *provably passed the oracle*.

Only oracle-verified cases are admitted (no unverified "solutions" -- that would
poison retrieval the same way a slop test poisons the oracle). Retrieval is
dependency-free (token-overlap / Jaccard over the failure signature), so it runs
on the same box as a 1.5B local model. Embeddings can be swapped in later behind
the same interface.

    from determinex_case_memory import CaseMemory
    mem = CaseMemory(Path("corpus/programbench/training_corpus/case_memory.jsonl"))
    mem.add(signature=err_text, solution=verified_patch, oracle_passed=True, tool="fd")
    for case in mem.retrieve(new_err_text, k=3):
        # inject case.solution as a worked example into the model prompt
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


@dataclass
class Case:
    signature: str  # the failure signature (error / assertion text)
    solution: str  # the verified fix (patch / code)
    tool: str = ""
    language: str = ""
    oracle_passed: bool = True


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


class CaseMemory:
    def __init__(self, store: Path):
        self.store = Path(store)
        self._cases: list[Case] = []
        self._load()

    def _load(self) -> None:
        if not self.store.exists():
            return
        for line in self.store.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                self._cases.append(
                    Case(
                        **{
                            k: d.get(k)
                            for k in ("signature", "solution", "tool", "language", "oracle_passed")
                        }
                    )
                )
            except Exception:
                continue

    def add(
        self, signature: str, solution: str, oracle_passed: bool, tool: str = "", language: str = ""
    ) -> bool:
        """Admit a case ONLY if the oracle passed. Unverified solutions are
        refused -- retrieval must never surface something that did not work."""
        if not oracle_passed:
            return False
        case = Case(
            signature=signature, solution=solution, tool=tool, language=language, oracle_passed=True
        )
        self._cases.append(case)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(case)) + "\n")
        return True

    def retrieve(self, signature: str, k: int = 3, min_similarity: float = 0.05) -> list[Case]:
        q = _tokens(signature)
        scored = [(_jaccard(q, _tokens(c.signature)), c) for c in self._cases if c.oracle_passed]
        scored = [(s, c) for s, c in scored if s >= min_similarity]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]]

    def __len__(self) -> int:
        return len(self._cases)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Determinex Case Memory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("store", type=Path)
    a.add_argument("--signature", required=True)
    a.add_argument("--solution", required=True)
    a.add_argument("--tool", default="")
    a.add_argument("--passed", action="store_true")
    r = sub.add_parser("retrieve")
    r.add_argument("store", type=Path)
    r.add_argument("--signature", required=True)
    r.add_argument("--k", type=int, default=3)
    args = ap.parse_args()
    mem = CaseMemory(args.store)
    if args.cmd == "add":
        ok = mem.add(args.signature, args.solution, args.passed, args.tool)
        print("admitted" if ok else "REFUSED (oracle did not pass)")
        return 0 if ok else 1
    if args.cmd == "retrieve":
        cases = mem.retrieve(args.signature, args.k)
        print(f"{len(cases)} similar verified cases:")
        for c in cases:
            print(f"  [{c.tool}] {c.signature[:60]} -> {c.solution[:50]}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
