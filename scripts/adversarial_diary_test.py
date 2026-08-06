#!/usr/bin/env python
"""
Adversarial end-to-end diary pipeline test (single-run regression).

For each turn it exercises the FULL loop the real app runs:

    LLM user-simulator  ->  script text (the "ground truth")
         ->  TTS (Kokoro)        ->  real WAV file
         ->  ASR (recognize WAV) ->  recognized text
         ->  DiaryAgent          ->  reply  (records to Bionic-Graph)
         ->  Bionic-Graph        ->  entries / mentions / todos

After the turns it:
  * reads the day back from the graph and DIFFS it against the simulator script,
  * verifies previously-mentioned PLANS / TODOS are HIGHLIGHTED (the agent's
    future-todo nudge resurfaces them on later turns),
  * runs a coverage loop where the "system" asks valuable follow-up questions
    until the daily-life facets are confident,
  * runs deterministic CORNER CASES (empty, duplicate, far-future plan, very long,
    mixed language, garbage, activity-with-time, nudge).

ASR is pluggable:
  --asr echo     : perfect recognition (default) — the WAV is still generated &
                   saved, but recognition returns the source text. This isolates
                   the agent + graph + questioning logic from ASR quality.
  --asr noise    : adversarial — character drops/substitutions simulate a noisy
                   recognizer so we can watch the agent/db degrade gracefully.
  --asr whisper  : real local recognition (needs `faster_whisper` installed).

The batch/scaled version (100 runs x N interactions + prompt mining) lives in
`batch_diary_sim.py` / `mine_prompts.py`; both import the shared pieces from
`diary_sim_lib.py`.

Run:
    .venv/bin/python scripts/adversarial_diary_test.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# All reusable pieces live in the shared library so the regression test and the
# scaled batch harness can never drift apart.
from diary_sim_lib import (  # noqa: E402
    FACETS,
    LLM,
    simulate_day,
    corner_cases,
    run_turn,
    read_day_full,
    evaluate,
    facet_coverage,
    coverage_loop,
    mint_run_keys,
)
from diary import runtime
from diary.agent import DiaryAgent, DiaryContext


# ─── Single-run driver (kept here; the scaled batch is in batch_diary_sim.py) ─

def main():
    ap = argparse.ArgumentParser(description="Adversarial diary pipeline test")
    ap.add_argument("--date", default="2099-08-05", help="test day (used as-is unless --fresh-date)")
    ap.add_argument("--asr", choices=["echo", "noise", "whisper"], default="echo")
    ap.add_argument("--noise-rate", type=float, default=0.15)
    ap.add_argument("--n-sim-turns", type=int, default=8, help="simulated 'user' turns per run")
    ap.add_argument("--max-coverage-rounds", type=int, default=2)
    ap.add_argument("--no-llm", action="store_true", help="skip the LLM simulator (corner cases only)")
    ap.add_argument("--out", default=None, help="write JSON report to this path")
    ap.add_argument("--fresh-date", action="store_true",
                    help="mint a unique far-future date per run (hermetic; avoids "
                         "cross-run graph contamination from _upsert's no-overwrite behaviour)")
    ap.add_argument("--runs", type=int, default=1, help="number of independent simulated days")
    ap.add_argument("--no-tts", action="store_true",
                    help="skip real Kokoro WAV generation (recognition still simulated). "
                         "Use for large batches; keep on for voice-fidelity sampling.")
    args = ap.parse_args()

    def run_date(run_idx: int) -> str:
        if not args.fresh_date:
            return args.date
        return mint_run_keys(run_idx)[0]

    all_runs = []
    for run_idx in range(args.runs):
        d = run_date(run_idx)
        rep = _run_one_day(d, args, run_idx)
        all_runs.append(rep)
        if args.runs > 1:
            print(f"\n##### RUN {run_idx + 1}/{args.runs}  date={d}  "
                  f"hard_failures={len(rep.get('hard_failures', []))}")

    total_hard_fail = sum(len(r.get("hard_failures", [])) for r in all_runs)
    if args.runs > 1:
        print("\n" + "=" * 78)
        print(f" BATCH SUMMARY: {args.runs} runs, {total_hard_fail} total hard failures")
        print("=" * 78)
    if args.out and args.runs > 1:
        batch = {"runs": all_runs, "total_hard_failures": total_hard_fail}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, indent=2)
        print(f"\n[report] batch written to {args.out}")
    return 1 if total_hard_fail else 0


def _run_one_day(args_date: str, args, run_idx: int) -> dict:
    outdir = tempfile.mkdtemp(prefix="adv_diary_")
    session_id = "adv-" + _date.today().isoformat()
    print(f"[setup] test day={args_date}  asr={args.asr}  session={session_id}")
    print(f"[setup] audio + report under {outdir}\n")

    llm = LLM() if not args.no_llm else None
    agent, ctx = runtime.get_or_create_diary_agent(session_id)
    client = runtime.get_client()

    # 1) Build the script (ground truth)
    turns: list[dict] = []
    if llm:
        turns += simulate_day(llm, args_date, args.n_sim_turns)
    turns += corner_cases(args_date)

    # Scope every turn_id/id to this run. CRITICAL: the graph stores Entry nodes
    # under stable_key = entry:<turn_id> (NOT date-scoped), and _upsert never
    # overwrites properties. Without a per-run nonce, repeated runs would all
    # share the same entry:sim0 / todo:... nodes and poison the script-vs-DB diff.
    import time as _time
    nonce = f"r{run_idx}_{int(_time.time() * 1000) % 100000}_"
    for t in turns:
        if t.get("turn_id"):
            t["turn_id"] = nonce + t["turn_id"]
        t["id"] = nonce + t["id"]

    # 2) Run every turn through TTS -> ASR -> agent -> graph
    results = []
    for t in turns:
        results.append(run_turn(agent, ctx, args_date, t, args.asr, outdir,
                                 args.noise_rate, seed=7, no_tts=args.no_tts))

    # 3) Read the day back and diff against the script
    db = read_day_full(client, ctx, args_date, turns)
    checks = evaluate(results, db, ctx, args_date)

    # 4) Coverage loop
    cov_log = []
    if llm and args.max_coverage_rounds > 0:
        cov_log = coverage_loop(llm, agent, ctx, args_date, db, outdir, args.asr,
                                args.max_coverage_rounds)
        db = read_day_full(client, ctx, args_date, turns)

    # 5) Report
    covered, missing = facet_coverage(db)
    hard = [c for c in checks if c[1]]
    soft = [c for c in checks if not c[1]]
    hard_fail = [c for c in hard if not c[2]]
    n_hard = len(hard)
    n_fail = len(hard_fail)
    n_soft = len(soft)

    print("=" * 78)
    print(" DIFF: simulator script  ->  database")
    print("=" * 78)
    for r in results:
        tag = r["source_tag"]
        print(f"\n[{r['id']}] ({tag})")
        print(f"  said : {r['source']}")
        if r["recognized"] != r["source"]:
            print(f"  ASR  : {r['recognized']}")
        print(f"  reply: {r['reply']}")
        print(f"  wav  : {os.path.basename(r['wav']) if r['wav'] else '(none)'}")

    print("\n" + "=" * 78)
    print(" CHECKS")
    print("=" * 78)
    for label, h, passed in checks:
        mark = "PASS" if passed else ("FAIL" if h else "warn")
        print(f"  [{mark}] {label}")

    print("\n" + "=" * 78)
    print(" COVERAGE")
    print("=" * 78)
    print(f"  facets covered : {covered}")
    print(f"  facets missing : {missing}")
    for c in cov_log:
        print(f"  Q: {c['question']}")
        print(f"  A: {c['answer']}")
        print(f"  (was probing: {c['missing']})")

    print("\n" + "=" * 78)
    print(" SUMMARY: %d/%d hard checks passed, %d soft (mention) checks, %d failures"
          % (n_hard - n_fail, n_hard, n_soft, n_fail))
    print("=" * 78)

    report = {
        "date": args_date, "asr": args.asr, "session": session_id,
        "diff": results, "checks": [
            {"label": l, "hard": h, "passed": p} for l, h, p in checks
        ],
        "coverage": {"covered": covered, "missing": missing},
        "coverage_qa": cov_log,
        "db": {"entries": db["entries_by_turn"], "mentions": db["mentions_by_turn"], "todos": db["todos"]},
        "hard_failures": [l for l, h, p in hard_fail],
    }
    if args.out and args.runs <= 1:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[report] written to {args.out}")

    return report


if __name__ == "__main__":
    sys.exit(main())
