#!/usr/bin/env python
"""
Mine robust system prompts from a batch corpus, then REPLAY candidate variants
on a frozen script to pick the best.

Pipeline:
  1. Load the corpus JSONL produced by batch_diary_sim.py.
  2. Recompute per-interaction failures, distinguishing:
       - hard   : entry_missing, empty_leak, todo_missing, nudge_missing
       - soft   : mention_label_missing (entity not extracted at all),
                  mention_key_mismatch (extracted under a different key/normalization)
  3. Cluster failures; pick the top genuine clusters.
  4. An LLM "prompt-engineer" proposes revised INTERVIEWER_SYSTEM variants targeting
     those clusters (baseline + targeted + aggregate).
  5. Build a frozen canonical script (deterministic simulator output) and replay
     EVERY variant on it with a pinned agent temperature (DIARY_AGENT_TEMP=0) and
     perfect ASR, so variants are compared on identical inputs.
  6. Print a variant x failure-type table and recommend the best; write the
     recommended prompt to --out-prompt for human sign-off (does NOT auto-edit
     diary/agent.py).

Run after a pilot:
    .venv/bin/python scripts/mine_prompts.py --corpus /tmp/corpus_pilot.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diary_sim_lib import LLM, simulate_day  # noqa: E402
from diary.agent import INTERVIEWER_SYSTEM  # noqa: E402
from diary import config  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(REPO_ROOT, "scripts", "batch_diary_sim.py")

# Function/modifier characters that the agent and the simulator routinely insert
# or swap when verbalizing the SAME plan (把↔给, 几本, 的, 这周/今天, 明天-reorder, …).
# Stripping them makes the todo match normalization-tolerant so we stop flagging
# paraphrases as `todo_missing`. Meaning-bearing verbs are deliberately excluded.
_TODO_FILLERS = set("的了一下几本这些那这周本周今天今日明天明日下周次周准备开始顺便把给被还也就要用一")


def _norm_todo(s: str) -> str:
    return "".join(c for c in (s or "") if c not in _TODO_FILLERS)


def _todo_present(td: str, got: list[str]) -> bool:
    """True if an extracted todo captures the expected plan (tolerant of rewording)."""
    ntd = _norm_todo(td)
    for t in got:
        if td in t or t in td:
            return True
        nt = _norm_todo(t)
        if ntd and (ntd in nt or nt in ntd):
            return True
    return False


# ─── 1+2. failure recomputation ──────────────────────────────────────────────

def classify(r: dict) -> list[str]:
    """Return the failure types for one corpus record (nuanced)."""
    exp = r.get("expected", {})
    out = []
    extracted = r.get("db", {}).get("extracted_mentions", [])
    labels = {ml.lower() for ml, _ in extracted}
    if exp.get("empty"):
        if r.get("db", {}).get("entry_present"):
            out.append("empty_leak")
        return out
    if not r.get("db", {}).get("entry_present"):
        out.append("entry_missing")
    for td in exp.get("todos", []):
        if not _todo_present(td, r.get("db", {}).get("day_todos", [])):
            out.append("todo_missing")
    for m in exp.get("mentions", []):
        lab, key = (m.split(":", 1) + ["", ""])[:2]
        lab = lab.lower()
        if lab not in labels:
            out.append("mention_label_missing")
        else:
            mk = {mk.lower() for _, mk in extracted}
            if key.lower() not in mk:
                out.append("mention_key_mismatch")
    for nk in exp.get("nudge", []):
        if nk not in (r.get("reply") or ""):
            out.append("nudge_missing")
    return out


HARD = {"entry_missing", "empty_leak", "todo_missing", "nudge_missing"}

# Harness `evaluate()` emits these labels as HARD checks (the replay summary uses
# them); map them so the comparison metric matches what was actually measured.
HARD_HARNESS = {
    "entry_present", "empty_no_entry", "todo_present",
    "target_day_todo", "nudge", "dedup",
}


def load_corpus(path: str) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


# ─── 3. clustering + representative examples ──────────────────────────────────

def cluster(recs: list[dict]):
    from collections import Counter, defaultdict
    counts = Counter()
    examples = defaultdict(list)
    for r in recs:
        for f in classify(r):
            counts[f] += 1
            if len(examples[f]) < 4:
                examples[f].append(r)
    return counts, examples


def fmt_examples(examples: list[dict], n: int = 3) -> str:
    lines = []
    for r in examples[:n]:
        lines.append(
            f"- user: {r['user_text']}\n"
            f"  expected: {r['expected']}\n"
            f"  extracted_mentions: {r['db']['extracted_mentions']}\n"
            f"  reply: {(r['reply'] or '')[:90]}"
        )
    return "\n".join(lines)


# ─── 4. prompt engineering ───────────────────────────────────────────────────

ENGINEER_SYSTEM = (
    "You are a prompt engineer improving a voice-diary assistant. You are given the "
    "assistant's current SYSTEM prompt and a set of FAILURE examples (user utterance, "
    "what was expected to be extracted, what was actually extracted, and the reply). "
    "Your job: rewrite the SYSTEM prompt so the assistant stops making these mistakes, "
    "while KEEPING it warm, concise, and conversational. Be concrete and minimal — add "
    "or sharpen instructions about (a) capturing every clearly-stated PLAN/TODO with "
    "its absolute date, (b) tagging mentioned PEOPLE/PLACE/THING/FOOD/MOOD/ACTIVITY with "
    "the SAME wording the user used (do not translate/rename entities), and (c) surfacing "
    "previously-planned items. Return ONLY the rewritten SYSTEM prompt text, nothing else."
)


def propose_variant(llm: LLM, focus: str, examples_block: str) -> str:
    user = (
        f"FAILURE CLUSTER: {focus}\n\n"
        f"EXAMPLES:\n{examples_block}\n\n"
        f"CURRENT SYSTEM PROMPT:\n{INTERVIEWER_SYSTEM}\n\n"
        "Return the improved SYSTEM prompt only."
    )
    return llm.chat(ENGINEER_SYSTEM, user, max_tokens=900, temperature=0.3).strip()


# ─── 5. frozen canonical script + replay ─────────────────────────────────────

def build_canonical_script(llm: LLM, n: int, path: str) -> None:
    script = simulate_day(llm, "2099-08-05", n)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)


def replay(script_path: str, prompt_path: str, corpus_out: str) -> dict:
    """Run the harness on a frozen script with a given prompt; return failure counts."""
    env = dict(os.environ)
    env["DIARY_AGENT_TEMP"] = "0"  # deterministic extraction for fair comparison
    cmd = [
        sys.executable, HARNESS,
        "--script-file", script_path,
        "--with-corners", "--no-llm", "--no-tts", "--asr", "echo",
        "--system-prompt-file", prompt_path,
        "--corpus-out", corpus_out,
        "--quiet",
    ]
    out = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    # Parse "failure counts by type:" block from stdout.
    counts: dict[str, int] = {}
    in_block = False
    for line in out.stdout.splitlines():
        if line.strip().startswith("failure counts by type"):
            in_block = True
            continue
        if in_block:
            if line.strip().startswith("="):
                break
            if ":" in line:
                k, v = line.strip().split(":", 1)
                counts[k.strip()] = int(v.strip())
    if not counts and out.returncode != 0:
        print("[replay] harness stderr:\n", out.stderr[-2000:])
    return counts


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Mine + replay diary system prompts")
    ap.add_argument("--corpus", default="/tmp/corpus_pilot.jsonl")
    ap.add_argument("--out-prompt", default="/tmp/best_prompt.txt",
                    help="where to write the recommended prompt (for sign-off)")
    ap.add_argument("--canonical-n", type=int, default=20,
                    help="turns in the frozen replay script")
    ap.add_argument("--max-variants", type=int, default=3)
    args = ap.parse_args()

    recs = load_corpus(args.corpus)
    counts, examples = cluster(recs)
    print(f"corpus: {len(recs)} records")
    print("failure clusters (hard in CAPS):")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        tag = "HARD" if k in HARD else "soft"
        print(f"  [{tag}] {k}: {v}")

    # Pick top genuine clusters to target (prefer hard; include a soft if dominant).
    ranked = sorted(counts.items(), key=lambda x: (-(x[1] if x[0] in HARD else x[1] / 10), -x[1]))
    targets = [k for k, _ in ranked if k in HARD][:2]
    if not targets and ranked:
        targets = [ranked[0][0]]
    print(f"\ntargeting clusters: {targets}")

    llm = LLM()

    # Build candidate variants: baseline + one per target + aggregate.
    variants = {"baseline": INTERVIEWER_SYSTEM}
    for t in targets:
        variants[f"target:{t}"] = propose_variant(llm, t, fmt_examples(examples[t]))
    if len(targets) > 1:
        agg_block = "\n\n".join(
            f"CLUSTER {t}:\n{fmt_examples(examples[t])}" for t in targets
        )
        variants["aggregate"] = propose_variant(llm, " + ".join(targets), agg_block)
    variants = dict(list(variants.items())[: args.max_variants])

    # Frozen script for replay.
    script_path = os.path.join(tempfile.gettempdir(), "canonical_script.json")
    build_canonical_script(llm, args.canonical_n, script_path)
    print(f"\ncanonical replay script: {script_path} ({args.canonical_n} turns + corners)")

    # Replay each variant.
    table = {}
    prompt_files = {}
    for name, prompt in variants.items():
        pf = os.path.join(tempfile.gettempdir(), f"prompt_{name}.txt")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt)
        prompt_files[name] = pf
        cout = os.path.join(tempfile.gettempdir(), f"replay_{name}.jsonl")
        table[name] = replay(script_path, pf, cout)
        print(f"  replayed {name}: {table[name]}")

    # Report.
    all_types = sorted({t for c in table.values() for t in c})
    print("\n" + "=" * 78)
    print(" VARIANT COMPARISON (failures by type; lower = better)")
    print("=" * 78)
    hdr = "variant".ljust(22) + "".join(t.ljust(18) for t in all_types) + "HARD_TOTAL"
    print(hdr)
    best, best_score = None, None
    for name, c in table.items():
        hard_total = sum(c.get(t, 0) for t in HARD_HARNESS)
        soft_total = sum(v for t, v in c.items() if t not in HARD_HARNESS)
        row = name.ljust(22) + "".join(str(c.get(t, 0)).ljust(18) for t in all_types) + str(hard_total)
        print(row)
        # Hard failures dominate; soft (mention) mismatches break ties.
        score = hard_total * 1000 + soft_total
        if best_score is None or score < best_score:
            best, best_score = name, score
    print("=" * 78)
    print(f"RECOMMENDED: {best}  (hard failures={best_score})")
    with open(args.out_prompt, "w", encoding="utf-8") as f:
        f.write(variants[best])
    print(f"recommended prompt written to {args.out_prompt} (review, then apply to diary/agent.py)")


if __name__ == "__main__":
    main()
