"""
eval_hive_compare.py — Three-way micro_eval comparison
=======================================================
Runs all 70 micro_eval probes through three conditions and reports pass rates:

  A) Direct DeepSeek API   — cloud-only, no local model
  B) Direct C3-medium      — local only, no API planning
  C) Hive (DS plan→C3)     — DeepSeek plans, C3-medium builds

Usage:
    python eval_hive_compare.py                    # all 14 concepts
    python eval_hive_compare.py --concept safe_divide
    python eval_hive_compare.py --conditions A,C   # skip B
    python eval_hive_compare.py --save             # write JSON results
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import logging

logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING, format="[EVAL] %(message)s")

from micro_eval import (
    CONCEPT_KEYS,
    CONCEPTS,
    _prewarm_model,
    _strip_fences,
    ask_student,
    run_probe,
)

# ── Config ────────────────────────────────────────────────────────────────────
DEEPSEEK_MODEL = "deepseek/deepseek-chat"  # litellm provider/model
LOCAL_MODEL = "determinex-3-medium-v1.1"  # Ollama tag
RESULTS_DIR = _SCRIPTS.parent / "logs" / "eval_results"
DEEPSEEK_API_KEY = os.environ.get("DETERMINEX_DEEPSEEK_KEY", os.environ.get("DEEPSEEK_API_KEY", ""))


# ── DeepSeek / litellm backend ────────────────────────────────────────────────


def _ask_deepseek(system: str, user: str, max_tokens: int = 512) -> str | None:
    """Call DeepSeek chat via litellm. Returns raw text or None on error."""
    try:
        import litellm

        resp = litellm.completion(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.0,
            api_key=DEEPSEEK_API_KEY,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        print(f"  [DeepSeek error] {e}")
        return None


# ── Condition A: Direct DeepSeek ──────────────────────────────────────────────


def ask_A(system: str, user: str) -> str | None:
    raw = _ask_deepseek(system, user)
    return _strip_fences(raw) if raw else None


# ── Condition B: Direct C3-medium ─────────────────────────────────────────────


def ask_B(system: str, user: str) -> str | None:
    raw = ask_student(LOCAL_MODEL, system, user)
    return _strip_fences(raw) if raw else None


# ── Condition C: Hive (DeepSeek plan → C3-medium code) ───────────────────────

_PLANNER_SYSTEM = (
    "You are a code planning assistant. Given a coding task, output ONE sentence: "
    "a high-level design pattern or approach. "
    "Name the PATTERN or STRATEGY only (e.g. 'guard clause', 'RAII', 'channel-based signaling', "
    "'retry loop with exception capture', 'generic type constraint'). "
    "Do NOT name specific crates, libraries, or external packages. "
    "Do NOT write code. Do NOT reference language-specific APIs by name. "
    "Output the pattern sentence only."
)


def ask_C(system: str, user: str) -> str | None:
    """DeepSeek generates a 1-sentence plan; C3-medium generates code guided by it."""
    plan = _ask_deepseek(_PLANNER_SYSTEM, user, max_tokens=80)
    if not plan:
        return None
    plan = plan.strip().splitlines()[0]  # first line only

    augmented_user = f"{user}\n\nIMPLEMENTATION PLAN: {plan}"
    raw = ask_student(LOCAL_MODEL, system, augmented_user)
    return _strip_fences(raw) if raw else None


# ── Probe runner ──────────────────────────────────────────────────────────────

ASK_FN = {"A": ask_A, "B": ask_B, "C": ask_C}
CONDITION_LABEL = {
    "A": "DeepSeek (direct)",
    "B": "C3-medium (direct)",
    "C": "Hive (DS plan→C3)",
}


def run_condition(condition: str, concepts: list[str], verbose: bool = False) -> dict:
    ask = ASK_FN[condition]
    label = CONDITION_LABEL[condition]

    print(f"\n{'═' * 64}")
    print(f"  CONDITION {condition}: {label}")
    print(f"  {datetime.now().strftime('%H:%M:%S')}  |  {len(concepts)} concepts")
    print(f"{'═' * 64}")

    if condition in ("B", "C"):
        print(f"  [pre-warm] Loading {LOCAL_MODEL}...", end=" ", flush=True)
        ok = _prewarm_model(LOCAL_MODEL, timeout=360)
        print("ready." if ok else "TIMEOUT — continuing anyway.")

    total_passed, total_probes = 0, 0
    concept_results = {}

    for concept_key in concepts:
        concept = CONCEPTS[concept_key]
        probes = concept["probes"]
        system = concept["system"]

        print(f"\n  ┌─ [{concept_key.upper()}]  {concept['description']}  ({concept['lang']})")
        passed_count, probe_results = 0, []

        for probe in probes:
            t0 = time.time()
            print(f"  │  [{probe['id']}] {probe['label']}", end=" ", flush=True)

            raw = ask(system, probe["prompt"])
            elapsed = time.time() - t0

            if raw is None:
                print("  SKIP")
                probe_results.append(
                    {
                        "probe_id": probe["id"],
                        "label": probe["label"],
                        "passed": False,
                        "elapsed": round(elapsed, 2),
                        "reason": "backend_unreachable",
                    }
                )
                continue

            if verbose:
                for line in raw.splitlines()[:8]:
                    print(f"  │    {line}")

            passed, err, stdout = run_probe(raw, probe)
            elapsed = round(time.time() - t0, 2)

            if passed:
                passed_count += 1
                print(f"  PASS ({elapsed}s)")
            else:
                print(f"  FAIL ({elapsed}s)  {err[:80]}")

            probe_results.append(
                {
                    "probe_id": probe["id"],
                    "label": probe["label"],
                    "passed": passed,
                    "elapsed": elapsed,
                    "compile_error": err[:300] if not passed else "",
                }
            )

        score_pct = round(100 * passed_count / len(probes)) if probes else 0
        grade = (
            "S"
            if score_pct == 100
            else "A"
            if score_pct >= 80
            else "B"
            if score_pct >= 60
            else "C"
            if score_pct >= 40
            else "F"
        )
        print(f"  └─ {passed_count}/{len(probes)} ({score_pct}%)  {grade}")

        concept_results[concept_key] = {
            "lang": concept["lang"],
            "passed": passed_count,
            "total": len(probes),
            "score_pct": score_pct,
            "grade": grade,
            "probes": probe_results,
        }
        total_passed += passed_count
        total_probes += len(probes)

    overall_pct = round(100 * total_passed / total_probes) if total_probes else 0
    grade = (
        "S"
        if overall_pct == 100
        else "A"
        if overall_pct >= 80
        else "B"
        if overall_pct >= 60
        else "C"
        if overall_pct >= 40
        else "F"
    )
    print(f"\n  OVERALL: {total_passed}/{total_probes} ({overall_pct}%)  GRADE: {grade}")

    return {
        "condition": condition,
        "label": label,
        "timestamp": datetime.now().isoformat(),
        "total_passed": total_passed,
        "total_probes": total_probes,
        "overall_pct": overall_pct,
        "grade": grade,
        "concepts": concept_results,
    }


# ── Comparison table ──────────────────────────────────────────────────────────


def print_comparison(results: dict[str, dict], concepts: list[str]):
    conditions = list(results.keys())
    print(f"\n{'═' * 72}")
    print("  COMPARISON SUMMARY")
    print(f"{'═' * 72}")

    header = f"  {'Concept':<18}  {'Lang':<6}"
    for c in conditions:
        header += f"  {CONDITION_LABEL[c][:16]:>16}"
    print(header)
    print(f"  {'─' * 18}  {'─' * 6}" + "  " + "  ".join(["─" * 16] * len(conditions)))

    for key in concepts:
        lang = CONCEPTS[key]["lang"]
        row = f"  {key:<18}  {lang:<6}"
        for c in conditions:
            r = results[c]["concepts"].get(key, {})
            pct = r.get("score_pct", "--")
            passed = r.get("passed", "?")
            total = r.get("total", "?")
            row += f"  {f'{passed}/{total} ({pct}%)':>16}"
        print(row)

    print(f"  {'─' * 18}  {'─' * 6}" + "  " + "  ".join(["─" * 16] * len(conditions)))
    total_row = f"  {'TOTAL':<18}  {'':6}"
    for c in conditions:
        r = results[c]
        pct = r["overall_pct"]
        passed = r["total_passed"]
        total = r["total_probes"]
        total_row += f"  {f'{passed}/{total} ({pct}%)':>16}"
    print(total_row)

    # Hive delta vs DeepSeek direct
    if "A" in results and "C" in results:
        delta = results["C"]["overall_pct"] - results["A"]["overall_pct"]
        sign = "+" if delta >= 0 else ""
        arrow = (
            "↑ Hive beats solo API"
            if delta > 0
            else ("↓ API beats Hive" if delta < 0 else "= tied")
        )
        print(f"\n  Hive vs Direct DeepSeek: {sign}{delta}%  {arrow}")

    if "B" in results and "C" in results:
        delta = results["C"]["overall_pct"] - results["B"]["overall_pct"]
        sign = "+" if delta >= 0 else ""
        arrow = (
            "↑ Planning helps"
            if delta > 0
            else ("↓ Planning hurts" if delta < 0 else "= no change")
        )
        print(f"  Hive vs Direct C3-med:  {sign}{delta}%  {arrow}")

    print(f"{'═' * 72}\n")


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Hive vs API vs Local comparison eval")
    parser.add_argument("--concept", default="all", choices=["all"] + CONCEPT_KEYS)
    parser.add_argument(
        "--conditions", default="A,B,C", help="Comma-separated conditions to run: A,B,C"
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--save", action="store_true", help="Save JSON results to logs/eval_results/"
    )
    args = parser.parse_args()

    if not DEEPSEEK_API_KEY:
        print(
            "ERROR: DETERMINEX_DEEPSEEK_KEY (or DEEPSEEK_API_KEY) not set. Export it or add to .env"
        )
        sys.exit(1)

    conditions = [c.strip().upper() for c in args.conditions.split(",")]
    concepts = CONCEPT_KEYS if args.concept == "all" else [args.concept]

    print("\nDeterminex Hive Comparison Eval")
    print(f"Conditions: {', '.join(f'{c}={CONDITION_LABEL[c]}' for c in conditions)}")
    print(f"Concepts:   {len(concepts)} × 5 probes = {len(concepts) * 5} total per condition")
    est_api = len(concepts) * 5 * sum(1 for c in conditions if c in ("A", "C"))
    if "C" in conditions:
        est_api += len(concepts) * 5  # planning calls
    print(f"Est. API calls: {est_api} (~${est_api * 0.0007:.2f})")
    print()

    all_results: dict[str, dict] = {}
    for cond in conditions:
        all_results[cond] = run_condition(cond, concepts, args.verbose)

    print_comparison(all_results, concepts)

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = RESULTS_DIR / f"hive_compare_{ts}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
        print(f"Results saved → {out_path}")


if __name__ == "__main__":
    # Load .env if present
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    main()
