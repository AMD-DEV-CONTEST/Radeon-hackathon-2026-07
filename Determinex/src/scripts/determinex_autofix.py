#!/usr/bin/env python3
"""
determinex_autofix.py -- The end-to-end self-correcting loop
=========================================================
One entrypoint that runs the whole thing the user described:

    take any bench -> INGEST (understand it) -> GATE (run + verify against ground
    truth) -> EXPLAIN (why it failed, how it should be per the test, whose fault)
    -> VALIDATE THE TEST (is it correct, or slop -- with proof) -> REMEDIATE
    (apply the fixes it diagnosed) -> and never declare a ceiling without proof.

It composes the five components:
    determinex_ingest         (A) understand the task
    determinex_oracle         (-) the pluggable ground-truth surface
    determinex_adjudicator    (-) the 4-step no-cop-out governor
    determinex_explainer      (C) per-failure blame + delta
    determinex_test_validator (D) deterministic "is the test slop?"
    determinex_remediation    (B) apply the diagnosed fixes

Modes
-----
    # From a finished eval report (ProgramBench / SWE-bench / any JUnit producer):
    python scripts/determinex_autofix.py report <eval_report.json> \
        [--submission DIR] [--tests-dir DIR] [--apply]

    # From a raw repo/task dir (ingest + which oracle + spec):
    python scripts/determinex_autofix.py ingest <repo_dir>

The `report` mode is the workhorse: it turns a wall of red into a structured,
honest verdict -- what to fix, what to match, what to unblock, and what is
genuinely impossible (with the proof) -- and, with --apply, writes the fixes.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import determinex_term_extractor as _term  # noqa: E402
from determinex_adjudicator import (  # noqa: E402
    Verdict,
    _base_nodeid,
    adjudicate_eval_report,
)
from determinex_explainer import explain_eval_report  # noqa: E402
from determinex_remediation import apply_to_submission, remediations_for  # noqa: E402
from determinex_test_validator import (  # noqa: E402
    TestVerdict,
    auto_reference_check,
    validate_eval_report,
)


def run_local_precheck(reimpl: Path, tests_dir: Path | None, sources: dict) -> None:
    """Cheap, free, no-Docker pre-eval check. The SYSTEM does the work:
      - proper verbiage the reimpl lacks, mined from the test SOURCES (authoritative;
        never from a stale eval traceback) -> MECHANICAL, apply verbatim.
      - run the reimpl locally vs the shipped tests -> classify rc/contains
        (MECHANICAL) vs exact-match (one SEMANTIC add-in, with EXPECTED shown).
    Local-green is the gate to spend a Docker eval."""
    print("\n-- LOCAL PRE-CHECK (cheap, no eval spent) --")
    # term normalization from test sources (authoritative verbiage)
    if sources:
        terms = _term.mine_texts(list(sources.values()))
        targets = _term.normalize(terms, reimpl if reimpl.exists() else None)
        if targets:
            print("   MECHANICAL: proper verbiage the reimpl lacks (from test sources):")
            for t in targets[:12]:
                print(f"     [{t['kind']:13}] {t['expected']!r}  (x{t['n']} tests)")
    # local oracle run
    if tests_dir and tests_dir.is_dir() and reimpl.exists():
        from determinex_local_oracle import run_oracle

        passed, total, reasons = run_oracle(reimpl, tests_dir, show_fail=12)
        if passed == total and total:
            print("\n   >> LOCAL-GREEN: worth spending a Docker eval now.")
        else:
            print(
                f"\n   >> {total - passed} local examples failing "
                f"{dict(reasons)} -- fix locally first (free), don't eval yet."
            )
            print(
                "      rc/contains = MECHANICAL; exact = one SEMANTIC formula "
                "(EXPECTED shown above)."
            )


def run_report(
    eval_report: Path,
    submission: Path | None,
    tests_dir: Path | None,
    apply: bool,
    reimpl: Path | None = None,
) -> int:
    conftest = compile_sh = ""
    if submission:
        cf = submission / "conftest.py"
        cs = submission / "compile.sh"
        conftest = cf.read_text(encoding="utf-8", errors="replace") if cf.exists() else ""
        compile_sh = cs.read_text(encoding="utf-8", errors="replace") if cs.exists() else ""
    sources = {}
    td = tests_dir or (submission / "tests" if submission else None)
    if td and td.is_dir():
        for p in td.rglob("test_*.py"):
            sources[p.stem] = p.read_text(encoding="utf-8", errors="replace")

    if reimpl is not None:
        run_local_precheck(reimpl, td, sources)

    adjs = adjudicate_eval_report(eval_report, conftest, compile_sh)
    exps = explain_eval_report(eval_report, sources, conftest, compile_sh)
    judgements = validate_eval_report(eval_report, sources)

    # collapse bidir twins for honest unique counts
    uadj = {}
    for a in adjs:
        uadj.setdefault(_base_nodeid(a.failure.test_id), a)
    uexp = {}
    for e in exps:
        uexp.setdefault(_base_nodeid(e.test_id), e)
    ujud = {}
    for j in judgements:
        ujud.setdefault(_base_nodeid(j.test_id), j)

    print(f"========== DETERMINEX AUTOFIX: {eval_report.name} ==========")
    n = len(uexp)
    blame = Counter(e.responsible for e in uexp.values())
    verdicts = Counter(a.verdict.value for a in uadj.values())
    slop = Counter(j.check for j in ujud.values() if j.verdict == TestVerdict.SLOP)

    print(f"\nUnique failing units: {n}")
    print("\n-- WHOSE FAULT (Explainer) --")
    print(f"   CODE        {blame.get('CODE', 0):4}   fix the implementation")
    print(f"   ENVIRONMENT {blame.get('ENVIRONMENT', 0):4}   match the reference env")
    print(f"   TEST        {blame.get('TEST', 0):4}   proven slop / genuine ceiling")

    print("\n-- THE MOVE (Adjudicator) --")
    for v, cnt in verdicts.most_common():
        print(f"   {v:11} {cnt:4}")

    if slop:
        print("\n-- PROVEN SLOP (Test Validator) --")
        for chk, cnt in slop.most_common():
            print(f"   {chk:18} {cnt:4}")

    genuine = verdicts.get(Verdict.IMPOSSIBLE.value, 0)
    reopen = n - genuine
    print("\n-- VERDICT --")
    print(f"   {reopen} reopenable, {genuine} genuine ceiling (with proof).")
    if reopen and genuine == 0:
        print("   >> NOTHING here is a true ceiling. This is unfinished work.")

    rems = remediations_for(list(uadj.values()))
    if rems:
        print("\n-- REMEDIATION PLAN --")
        for r in rems:
            print(f"   [{r.strategy}] {r.rationale[:88]}")
            if r.manual_followup:
                print(f"       manual: {r.manual_followup[:80]}")
    if apply and submission:
        actions = apply_to_submission(submission, rems)
        print(f"\n-- APPLIED to {submission} --")
        for a in actions:
            print(f"   {a}")
        print("   (repack submission.tar.gz and re-eval to confirm)")
    elif apply and not submission:
        print("\n   --apply requires --submission DIR")
    return 0


def triage(
    eval_report: Path,
    submission: Path | None = None,
    tests_dir: Path | None = None,
    reference_check: bool = False,
) -> dict:
    """The routing BRAIN (programmatic; same engine as run_report's print). Classify a tool's
    failures so the autodrive can ROUTE: reopenable (winnable -> close it) vs genuine ceiling
    (Adjudicator IMPOSSIBLE *with proof* -> certify) vs slop (broken test -> flag). SOUND by
    construction: a failure counts as a ceiling ONLY when proven IMPOSSIBLE; everything else is
    reopenable. Returns {n, code, env, test, genuine, reopen, slop, proofs, remediations}."""
    conftest = compile_sh = ""
    if submission:
        cf, cs = submission / "conftest.py", submission / "compile.sh"
        conftest = cf.read_text(encoding="utf-8", errors="replace") if cf.exists() else ""
        compile_sh = cs.read_text(encoding="utf-8", errors="replace") if cs.exists() else ""
    sources: dict = {}
    td = tests_dir or (submission / "tests" if submission else None)
    if td and td.is_dir():
        for p in td.rglob("test_*.py"):
            sources[p.stem] = p.read_text(encoding="utf-8", errors="replace")
    adjs = adjudicate_eval_report(eval_report, conftest, compile_sh)
    exps = explain_eval_report(eval_report, sources, conftest, compile_sh)
    judgements = validate_eval_report(eval_report, sources)
    uadj: dict = {}
    for a in adjs:
        uadj.setdefault(_base_nodeid(a.failure.test_id), a)
    uexp: dict = {}
    for e in exps:
        uexp.setdefault(_base_nodeid(e.test_id), e)
    ujud: dict = {}
    for j in judgements:
        ujud.setdefault(_base_nodeid(j.test_id), j)
    # AUTOMATED check 4 (opt-in, heavy): build a clean reference from source + prove SLOP where a
    # CORRECT binary fails the test too. Overrides a static CORRECT with proven SLOP. Off by default
    # (a per-tool reference build is costly); a deliberate re-triage / close-decision turns it on.
    # This is the mechanized "build the upstream binary and run it" proof.
    if reference_check and submission:
        try:
            for rj in auto_reference_check(submission, eval_report):
                if rj.verdict == TestVerdict.SLOP:
                    ujud[_base_nodeid(rj.test_id)] = rj
        except Exception:
            pass
    n = len(uexp)
    blame = Counter(e.responsible for e in uexp.values())
    verdicts = Counter(a.verdict.value for a in uadj.values())
    genuine = verdicts.get(Verdict.IMPOSSIBLE.value, 0)
    reopen = max(0, n - genuine)
    slop = sum(1 for j in ujud.values() if j.verdict == TestVerdict.SLOP)
    proofs = [
        getattr(a, "proof", "") or ""
        for a in uadj.values()
        if a.verdict == Verdict.IMPOSSIBLE and getattr(a, "proof", "")
    ][:10]
    proofs += [
        getattr(j, "proof", "") or ""
        for j in ujud.values()  # reference-fail slop proofs
        if j.verdict == TestVerdict.SLOP and getattr(j, "proof", "")
    ][:10]
    rems = remediations_for(list(uadj.values()))
    return {
        "n": n,
        "code": blame.get("CODE", 0),
        "env": blame.get("ENVIRONMENT", 0),
        "test": blame.get("TEST", 0),
        "genuine": genuine,
        "reopen": reopen,
        "slop": slop,
        "proofs": proofs,
        "remediations": [
            {
                "strategy": r.strategy,
                "rationale": (r.rationale or "")[:160],
                "manual": (r.manual_followup or "")[:160],
            }
            for r in rems
        ][:10],
    }


def run_ingest(repo: Path) -> int:
    from determinex_ingest import ingest

    u = ingest(repo)
    print(f"========== DETERMINEX INGEST: {u.root} ==========")
    print(
        f"  language={u.language} build={u.build_system} harness={u.harness} "
        f"oracle={u.oracle} available={u.oracle_available}"
    )
    print(f"  {u.spec.summary}")
    if u.oracle == "SYNTHESIZE":
        print(
            "  >> no shipped tests: run synthesize_oracle() to manufacture ground "
            "truth before solving."
        )
    for note in u.notes:
        print(f"  ! {note}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Determinex end-to-end autofix loop")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="full analysis of an eval report")
    r.add_argument("eval_report", type=Path)
    r.add_argument("--submission", type=Path, default=None)
    r.add_argument("--tests-dir", type=Path, default=None)
    r.add_argument(
        "--reimpl",
        type=Path,
        default=None,
        help="run the cheap local pre-check against this reimplementation",
    )
    r.add_argument("--apply", action="store_true")
    i = sub.add_parser("ingest", help="understand a raw repo/task")
    i.add_argument("repo", type=Path)
    args = ap.parse_args()
    if args.cmd == "report":
        return run_report(
            args.eval_report, args.submission, args.tests_dir, args.apply, args.reimpl
        )
    if args.cmd == "ingest":
        return run_ingest(args.repo)
    return 1


if __name__ == "__main__":
    sys.exit(main())
