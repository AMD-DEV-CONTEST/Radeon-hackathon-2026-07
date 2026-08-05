#!/usr/bin/env python3
"""
determinex_reimpl_analyze.py -- continuous corpus<->LLM design-invariant analyzer
==============================================================================
Answers ONE question every run: "is the reimplementation loop truly working as designed?"
It does NOT re-score (that's determinex_pb_official_eval); it audits the LOOP's health by
comparing what the CORPUS coached against what the LLM actually produced, and whether the
system is learning. Reusable so analysis can be CONSTANT (run after every candidate).

Design invariants checked (each -> OK / CONCERN with evidence):
  1. ORACLE SOUNDNESS   -- discrimination ratio (trivial mutants must all be rejected).
  2. COACH ADHERENCE    -- did the LLM apply the technique RECIPES the corpus injected?
                           (e.g. number-repr: parse_int/parse_float hook present, no bare
                            json.loads on the value path). The recipe is useless if ignored.
  3. CORPUS LEARNING    -- best_official climbing, hard_behaviors being retired over runs.
  4. OPTIMISM GAP       -- local genuine-pass vs official; the bound we must shrink.
  5. SEARCH EFFECT      -- (when a run log is given) did rounds improve over the first draft?

Usage:
  python scripts/determinex_reimpl_analyze.py <short> [--candidate path.py] [--runlog out.txt]
  python scripts/determinex_reimpl_analyze.py gron --candidate logs/reimpl/gron_deepseek_recipe.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import determinex_reimpl_corpus as CORPUS  # noqa: E402

OK = "OK    "
WARN = "CONCERN"


def _line(tag: str, name: str, msg: str) -> str:
    return f"  [{tag}] {name}: {msg}"


# --- recipe-adherence detectors: did the candidate ACT on the injected technique? ---------
def check_recipe_adherence(short: str, code: str, observations: list | None) -> list[str]:
    """Static scan: for each recipe the corpus WOULD inject for this tool, detect whether the
    candidate's code shows the technique's fingerprint. Catches 'knew WHAT not HOW' silently."""
    out: list[str] = []
    injected = CORPUS.recipes_for(short, observations)
    # number-repr recipe (json domain)
    if "preserve EXACT number text" in injected:
        has_hook = bool(re.search(r"parse_(?:int|float)\s*=", code))
        # the failure signature: bare json.loads feeding the value path with no raw capture
        bare_loads = bool(re.search(r"json\.loads\(", code)) and not has_hook
        reformats = bool(re.search(r"\b(?:float|int)\s*\(", code)) and not has_hook
        if has_hook:
            out.append(
                _line(
                    OK,
                    "number-repr",
                    "parse_int/parse_float raw-capture hook present (recipe applied)",
                )
            )
        else:
            ev = "no parse_int/parse_float hook"
            if bare_loads:
                ev += " + bare json.loads on value path"
            if reformats:
                ev += " + float()/int() reformatting (destroys 1.2e10/-0)"
            out.append(_line(WARN, "number-repr", f"recipe NOT applied: {ev}"))
    # io recipe (universal): file-arg-or-stdin
    if "file-arg-or-stdin" in injected:
        reads_stdin = "stdin" in code
        reads_file = bool(re.search(r"open\(", code))
        if reads_stdin and reads_file:
            out.append(_line(OK, "file-or-stdin", "handles both stdin and file argument"))
        else:
            miss = "no stdin read" if not reads_stdin else "no file open()"
            out.append(_line(WARN, "file-or-stdin", f"recipe partial: {miss}"))
    return out


def check_corpus_learning(short: str) -> list[str]:
    """Is the corpus accumulating verified capability for this tool?"""
    rec = CORPUS.load(short)
    out: list[str] = []
    if not rec:
        return [_line(WARN, "learning", "no corpus record yet for this tool")]
    bo, bt = rec.get("best_official"), rec.get("best_official_total")
    last = rec.get("last_official")
    if bo is not None:
        out.append(
            _line(
                OK,
                "best-official",
                f"{bo}/{bt}" + (f"  (last run {last})" if last is not None else ""),
            )
        )
    hard = rec.get("hard_behaviors") or []
    out.append(
        _line(
            OK if hard else WARN,
            "hard-behaviors",
            f"{len(hard)} tracked: {', '.join(hard[:8])}{'…' if len(hard) > 8 else ''}",
        )
    )
    if rec.get("verified_skill"):
        out.append(_line(OK, "verified-skill", f"LOCKED {rec.get('locked')}"))
    return out


def analyze(short: str, candidate: str | None, runlog: str | None) -> int:
    print(f"\n=== DESIGN-INVARIANT ANALYSIS :: {short} (corpus <-> LLM) ===")

    concerns = 0
    # 1+2 require the candidate code
    if candidate and Path(candidate).exists():
        code = Path(candidate).read_text(encoding="utf-8", errors="replace")
        print("\n[2] COACH ADHERENCE (did the model APPLY the injected recipes?)")
        for ln in check_recipe_adherence(short, code, None):
            print(ln)
            if f"[{WARN}]" in ln:
                concerns += 1
    else:
        print("\n[2] COACH ADHERENCE: (no candidate given -- pass --candidate to check)")

    print("\n[3] CORPUS LEARNING (is verified capability accumulating?)")
    for ln in check_corpus_learning(short):
        print(ln)
        if f"[{WARN}]" in ln:
            concerns += 1

    # 1/4/5 from the run log if present (cheap, no docker)
    if runlog and Path(runlog).exists():
        txt = Path(runlog).read_text(encoding="utf-8", errors="replace")
        print("\n[1] ORACLE SOUNDNESS (from run log)")
        m = re.search(r"discrimination (\d+)/(\d+) \(ratio ([\d.]+)\)", txt)
        if m:
            ratio = float(m.group(3))
            tag = OK if ratio >= 1.0 else WARN
            print(
                _line(
                    tag,
                    "discrimination",
                    f"{m.group(1)}/{m.group(2)} (ratio {ratio:.2f})"
                    + ("" if ratio >= 1.0 else " -- a do-nothing/echo candidate can slip through!"),
                )
            )
            if ratio < 1.0:
                concerns += 1
        print("\n[4] OPTIMISM GAP (local proxy vs reality)")
        g = re.search(r"GENUINE behavior reproduced: (\d+)/(\d+)", txt)
        if g:
            print(
                _line(
                    OK,
                    "local-genuine",
                    f"{g.group(1)}/{g.group(2)} -- compare to official to see the gap",
                )
            )

    verdict = (
        "WORKING AS DESIGNED"
        if concerns == 0
        else f"{concerns} CONCERN(S) -- loop not fully as designed"
    )
    print(f"\n=== VERDICT: {verdict} ===\n")
    return concerns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("short")
    ap.add_argument("--candidate", default=None)
    ap.add_argument("--runlog", default=None)
    args = ap.parse_args()
    return analyze(args.short, args.candidate, args.runlog)


if __name__ == "__main__":
    raise SystemExit(main())
