#!/usr/bin/env python3
"""
determinex_explainer.py -- The Failure Explainer (Adjudicator component C)
=======================================================================
"...if it fails it shows why, with how it should be according to the test, and
what it would take to be right, and the actual test be correct, not slop."

This is the synthesis layer. It fuses the Impossibility Adjudicator (WHY the
failure happened + the move that resolves it) with the Test Validator (whether
the TEST itself is correct) into a single structured Explanation per failure:

    responsible : CODE | TEST | ENVIRONMENT   (who is actually wrong)
    expected    : what the test demands
    actual      : what the program produced
    delta       : the concrete change to be right
    proof       : deterministic evidence (only when TEST/ENVIRONMENT is at fault)
    confidence  : 0..1

The honest assignment of blame is the point: a failure is only laid on the TEST
when the Validator produced a PROOF (contradiction / env-baked / tautology /
reference-fail). Otherwise the blame is on the CODE and the delta is the fix.
Environment mismatches are called out separately so they are matched, not chased.

    from determinex_explainer import explain_eval_report
    for e in explain_eval_report(Path("eval.json"), test_sources):
        print(e.render())

CLI
---
    python scripts/determinex_explainer.py <eval_report.json> [--tests-dir DIR]
                                        [--conftest C --compile-sh S] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from determinex_adjudicator import (  # noqa: E402
    Verdict,
    _base_nodeid,
    _failures_from_eval_report,
    classify_failure,
)
from determinex_test_validator import (  # noqa: E402
    TestVerdict,
    validate_eval_report,
)


@dataclass
class Explanation:
    test_id: str
    responsible: str  # CODE | TEST | ENVIRONMENT
    why: str  # the adjudicator's plain-language cause
    expected: str | None
    actual: str | None
    delta: str  # the concrete change to be right
    proof: str  # deterministic evidence (TEST/ENVIRONMENT only)
    confidence: float

    def render(self) -> str:
        head = {
            "CODE": "FIX THE CODE",
            "TEST": "THE TEST IS WRONG (proven)",
            "ENVIRONMENT": "MATCH THE ENVIRONMENT",
        }[self.responsible]
        lines = [f"[{self.responsible}] {head}  ({self.test_id})", f"  why     : {self.why}"]
        if self.expected is not None:
            lines.append(f"  expected: {self.expected[:100]}")
        if self.actual is not None:
            lines.append(f"  actual  : {self.actual[:100]}")
        lines.append(f"  delta   : {self.delta}")
        if self.proof:
            lines.append(f"  PROOF   : {self.proof[:140]}")
        lines.append(f"  conf    : {self.confidence:.2f}")
        return "\n".join(lines)


def explain_eval_report(
    eval_report: Path,
    test_sources: dict[str, str] | None = None,
    conftest_text: str = "",
    compile_sh_text: str = "",
) -> list[Explanation]:
    failures = _failures_from_eval_report(eval_report)
    # peers for routing/contradiction signals
    from collections import defaultdict

    peers = defaultdict(list)
    for f in failures:
        peers[_base_nodeid(f.test_id)].append(f)
    # test validity judgements keyed by test_id
    judgements = {j.test_id: j for j in validate_eval_report(eval_report, test_sources)}

    out: list[Explanation] = []
    for f in failures:
        adj = classify_failure(f, peers, conftest_text, compile_sh_text)
        jv = judgements.get(f.test_id)

        # Decide the responsible party honestly.
        if jv and jv.verdict == TestVerdict.SLOP:
            responsible = "ENVIRONMENT" if jv.check == "environment-baked" else "TEST"
            why = (
                adj.remediation
                if responsible == "ENVIRONMENT"
                else "The test does not describe correct behavior."
            )
            delta = jv.recommended_action or adj.remediation
            proof = jv.proof
            conf = 0.8
        elif adj.verdict == Verdict.UNBLOCK:
            responsible = "CODE"  # our own blocker, but the move is on our side
            why = adj.remediation
            delta = adj.remediation
            proof = ""
            conf = adj.confidence
        elif adj.verdict == Verdict.MATCH:
            responsible = "ENVIRONMENT"
            why = adj.remediation
            delta = adj.remediation
            proof = ""
            conf = adj.confidence
        elif adj.verdict == Verdict.ROUTE:
            responsible = "CODE"  # the binary must learn to route
            why = adj.remediation
            delta = adj.remediation
            proof = ""
            conf = adj.confidence
        elif adj.verdict == Verdict.IMPOSSIBLE:
            responsible = "TEST"
            why = adj.remediation
            delta = "Report as a genuine ceiling; do not chase."
            proof = adj.strategy
            conf = adj.confidence
        else:  # NEEDS_WORK
            responsible = "CODE"
            why = "Behavioral mismatch with the test's expectation."
            delta = "Change the implementation so output matches the expected golden."
            proof = ""
            conf = adj.confidence

        out.append(
            Explanation(
                test_id=f.test_id,
                responsible=responsible,
                why=why,
                expected=f.expected,
                actual=f.actual,
                delta=delta,
                proof=proof,
                confidence=conf,
            )
        )
    return out


def _summary(eval_report: Path, exps: list[Explanation], as_json: bool) -> int:
    # collapse bidir twins
    seen: dict[str, Explanation] = {}
    for e in exps:
        seen.setdefault(_base_nodeid(e.test_id), e)
    uniq = list(seen.values())
    if as_json:
        print(json.dumps([asdict(e) for e in uniq], indent=2))
        return 0
    c = Counter(e.responsible for e in uniq)
    print(f"=== FAILURE EXPLANATION: {eval_report.name} ===")
    print(f"unique failures: {len(uniq)}  ->  {dict(c)}")
    print("\nWho is actually wrong:")
    print(f"  CODE        : {c.get('CODE', 0):4}  (fix the implementation)")
    print(f"  ENVIRONMENT : {c.get('ENVIRONMENT', 0):4}  (match the reference env)")
    print(f"  TEST        : {c.get('TEST', 0):4}  (proven slop / genuine ceiling)")
    # show a few examples per bucket
    for party in ("TEST", "ENVIRONMENT", "CODE"):
        items = [e for e in uniq if e.responsible == party]
        if not items:
            continue
        print(f"\n--- {party} (showing up to 3) ---")
        for e in items[:3]:
            print(e.render())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex Failure Explainer")
    ap.add_argument("eval_report", type=Path)
    ap.add_argument("--tests-dir", type=Path, default=None)
    ap.add_argument("--conftest", type=Path, default=None)
    ap.add_argument("--compile-sh", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sources = {}
    if args.tests_dir and args.tests_dir.is_dir():
        for p in args.tests_dir.rglob("test_*.py"):
            sources[p.stem] = p.read_text(encoding="utf-8", errors="replace")
    conf = (
        args.conftest.read_text(encoding="utf-8", errors="replace")
        if args.conftest and args.conftest.exists()
        else ""
    )
    cs = (
        args.compile_sh.read_text(encoding="utf-8", errors="replace")
        if args.compile_sh and args.compile_sh.exists()
        else ""
    )
    exps = explain_eval_report(args.eval_report, sources, conf, cs)
    return _summary(args.eval_report, exps, args.json)


if __name__ == "__main__":
    sys.exit(main())
