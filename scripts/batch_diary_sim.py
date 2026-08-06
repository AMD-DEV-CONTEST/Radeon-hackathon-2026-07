#!/usr/bin/env python
"""
Scaled adversarial batch harness for the diary agent.

Runs many simulated "user <-> agent" days and writes an incremental JSONL
corpus of every interaction so the data can be mined for robust system prompts
(see `mine_prompts.py`).

For each run (a simulated day):
  * mint a hermetic (date, nonce) pair (see diary_sim_lib.mint_run_keys);
  * an LLM "user" narrates `interactions` turns (optionally + corner cases);
  * each turn: TTS -> ASR (simulated by default) -> DiaryAgent -> record;
  * after the run, the day is read back and every turn is evaluated against the
    simulator's ground truth (missed todo / mention / date-off / nudge ...).

One JSON object per interaction is appended to --corpus-out (so a crash loses
only the current run). A run summary (failures by type) is printed at the end.

Hermmeticity: each run gets a fresh far-future date AND a per-run nonce on every
turn_id, because Entry stable_keys are global and `_upsert` never overwrites.

Run a pilot:
    .venv/bin/python scripts/batch_diary_sim.py \
        --runs 5 --interactions 20 --no-tts --fresh-date \
        --corpus-out /tmp/corpus.jsonl

Full batch (background, hours):
    .venv/bin/python scripts/batch_diary_sim.py \
        --runs 100 --interactions 100 --no-tts --fresh-date \
        --corpus-out /tmp/corpus_100x100.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from diary_sim_lib import (  # noqa: E402
    LLM,
    DiaryAgent,
    DiaryContext,
    simulate_day,
    corner_cases,
    run_turn,
    read_day_full,
    evaluate,
    mint_run_keys,
)
from diary import runtime


def load_system_prompt(path: str | None) -> str | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def run_one_day(run_idx: int, args, system_prompt: str | None, corpus_f, summary) -> None:
    date, nonce = mint_run_keys(run_idx)
    outdir = tempfile.mkdtemp(prefix="batch_diary_")
    session_id = f"batch-{_date.today().isoformat()}-{run_idx}"

    llm = LLM(base_url=args.sim_llm_base_url) if not args.no_llm else None
    client = runtime.get_client()
    ctx = DiaryContext(client=client)
    # Fresh agent per run -> hermetic conversation history (no cross-run leakage).
    agent = DiaryAgent(system_prompt=system_prompt)

    print(f"[run {run_idx}] date={date} asr={args.asr} interactions={args.interactions}")

    turns: list[dict] = []
    if args.script_file:
        # Frozen inputs for replay (prompt-mining compares variants on identical
        # turns). Expects a JSON list of {text, expect, [id, turn_id, source]}.
        with open(args.script_file, "r", encoding="utf-8") as f:
            turns = json.load(f)
    else:
        if llm:
            turns += simulate_day(llm, date, args.interactions)
        if args.with_corners:
            turns += corner_cases(date)

    # Scope every turn id so the global Entry/Todo stable_keys never collide.
    for t in turns:
        if t.get("turn_id"):
            t["turn_id"] = nonce + t["turn_id"]
        t["id"] = nonce + t["id"]

    results = []
    for i, t in enumerate(turns):
        r = run_turn(agent, ctx, date, t, args.asr, outdir,
                     args.noise_rate, seed=7, no_tts=args.no_tts)
        results.append(r)
        # Read-back after every turn would be expensive; read once at the end and
        # attribute per-turn via stable_key (each turn is its own entry node).
        if not args.quiet:
            print(f"  [{i:03d}] {t.get('source')}: {r['reply'][:50]}")

    db = read_day_full(client, ctx, date, turns)
    checks = evaluate(results, db, ctx, date)

    # Tally failures by type and emit a corpus record per interaction.
    for r in results:
        tid = r.get("turn_id") or r["id"]
        exp = r.get("expect", {})
        entry_present = db["entries_by_turn"].get(tid) == r["recognized"]
        extracted = db["mentions_by_turn"].get(tid, [])
        nudge_fired = ("「" in (r["reply"] or "")) and ("有进展吗" in (r["reply"] or ""))
        rec = {
            "run": run_idx,
            "turn": tid,
            "source_tag": r.get("source_tag"),
            "user_text": r["source"],
            "asr_text": r["recognized"],
            "reply": r["reply"],
            "expected": exp,
            "db": {
                "entry_present": entry_present,
                "extracted_mentions": extracted,
                "day_todos": db["todos"],
            },
            "nudge_fired": nudge_fired,
            "reply_len": len(r["reply"] or ""),
            "empty_input": (not r["source"] or not r["source"].strip()),
        }
        corpus_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        corpus_f.flush()

    # Per-run failure accounting.
    for label, hard, passed in checks:
        if not passed:
            kind = label.split(":", 1)[0]
            summary[kind] = summary.get(kind, 0) + 1
    run_fail = sum(1 for _, h, p in checks if h and not p)
    print(f"[run {run_idx}] done. hard_failures={run_fail}; running totals={summary}")


def main():
    ap = argparse.ArgumentParser(description="Scaled diary adversarial batch simulator")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--interactions", type=int, default=20, help="simulated user turns per run")
    ap.add_argument("--asr", choices=["echo", "noise", "whisper"], default="echo")
    ap.add_argument("--noise-rate", type=float, default=0.15)
    ap.add_argument("--no-tts", action="store_true",
                    help="skip real Kokoro WAV generation (recognition simulated). "
                         "Required for large batches.")
    ap.add_argument("--fresh-date", action="store_true", help="hermetic unique date per run")
    ap.add_argument("--no-llm", action="store_true", help="skip simulator (corners only)")
    ap.add_argument("--with-corners", action="store_true", help="also inject corner cases each run")
    ap.add_argument("--sim-llm-base-url", default=None,
                    help="optional 2nd LLM (e.g. a smaller model) for the user-simulator")
    ap.add_argument("--script-file", default=None,
                    help="frozen turn list (JSON) instead of the LLM simulator; "
                         "used to replay prompt variants on identical inputs")
    ap.add_argument("--system-prompt-file", default=None,
                    help="override the agent's INTERVIEWER_SYSTEM (for prompt-mining replay)")
    ap.add_argument("--corpus-out", default="/tmp/corpus.jsonl", help="JSONL corpus output")
    ap.add_argument("--quiet", action="store_true", help="suppress per-turn console output")
    args = ap.parse_args()

    system_prompt = load_system_prompt(args.system_prompt_file)
    summary: dict[str, int] = {}
    with open(args.corpus_out, "w", encoding="utf-8") as corpus_f:
        for run_idx in range(args.runs):
            run_one_day(run_idx, args, system_prompt, corpus_f, summary)

    print("\n" + "=" * 78)
    print(f" BATCH COMPLETE: {args.runs} runs x ~{args.interactions} interactions")
    print(f" corpus -> {args.corpus_out}")
    print(" failure counts by type:")
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        print(f"   {k}: {v}")
    print("=" * 78)


if __name__ == "__main__":
    main()
