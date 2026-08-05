"""
process_batch_corpus.py — Compile-verify batch model outputs and merge into lora_train.jsonl

Usage:
    python scripts/process_batch_corpus.py ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/batch_gemini-flash.json
    python scripts/process_batch_corpus.py --all          # process all batch_*.json files
    python scripts/process_batch_corpus.py --all --merge  # also merge into lora_train.jsonl

Output:
    ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/verified_{model}.json    — pass/fail per probe
    ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/lora_train.jsonl         — merged training data (--merge)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import logging

logging.getLogger("LiteLLM").setLevel(logging.WARNING)
logging.getLogger("litellm").setLevel(logging.WARNING)
logging.basicConfig(level=logging.WARNING)

import os as _os

from micro_eval import CONCEPTS, _strip_fences, run_probe
from micro_eval_extra import EXTRA_CONCEPTS

# The rename inserted a *shell* expansion into plain Python strings; Python does
# not expand those, so these silently became a literal directory named
# "${DETERMINEX_MODELS_DIR:-~/determinex-models}". Resolve it the way sh would.
_MODELS_DIR = _os.path.expanduser(_os.environ.get("DETERMINEX_MODELS_DIR", "~/determinex-models"))

ALL_CONCEPTS = {**CONCEPTS, **EXTRA_CONCEPTS}
CORPUS_DIR = Path("" + _MODELS_DIR + "/corpus")


# Lazily load full-corpus concepts from generate_full_corpus_prompts.py
def _load_full_corpus_concepts() -> dict:
    """Convert MODERN_COMPILED/MODERN_SCRIPTING/etc. into ALL_CONCEPTS format."""
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "gfcp", Path(__file__).parent / "generate_full_corpus_prompts.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore
    except Exception as e:
        print(f"  WARN: could not load full_corpus concepts: {e}")
        return {}

    out = {}
    families = [
        getattr(mod, "MODERN_COMPILED", []),
        getattr(mod, "MODERN_SCRIPTING", []),
        getattr(mod, "FUNCTIONAL", []),
        getattr(mod, "LEGACY", []),
        getattr(mod, "INFRA_QUERY", []),
    ]
    for family in families:
        for c in family:
            key = c["key"]
            probes = []
            for p in c["probes"]:
                probes.append(
                    {
                        "id": p["id"],
                        "fn_name": c.get("fn", ""),
                        "prompt": p["p"],
                        "lang": c["lang"],
                        "verifiable": False,  # no compile harness for these
                    }
                )
            out[key] = {
                "lang": c["lang"],
                "system": f"You are an expert {c['lang']} programmer.",
                "probes": probes,
            }
    return out


ALL_CONCEPTS = {**CONCEPTS, **EXTRA_CONCEPTS, **_load_full_corpus_concepts()}


def get_probe(concept_key: str, probe_id: str) -> dict | None:
    concept = ALL_CONCEPTS.get(concept_key)
    if not concept:
        return None
    for p in concept["probes"]:
        if p["id"] == probe_id:
            return p
    return None


def process_file(batch_path: Path) -> dict:
    model_name = batch_path.stem.replace("batch_", "")
    print(f"\n{'=' * 60}")
    print(f"  Processing: {batch_path.name}  ({model_name})")
    print(f"{'=' * 60}")

    try:
        raw = batch_path.read_text(encoding="utf-8")
        # Strip markdown fences if model wrapped output
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0].strip()
        # Find the real JSON array start: the '[' immediately before the first '{'
        first_brace = raw.find("{")
        if first_brace > 0:
            bracket = raw.rfind("[", 0, first_brace)
            if bracket > 0:
                preamble = raw[:bracket].strip()
                print(f"  NOTE: stripped preamble: {preamble[:80]!r}")
                raw = raw[bracket:]
        entries = json.loads(raw)
    except Exception as e:
        print(f"  ERROR reading file: {e}")
        return {}

    if not isinstance(entries, list):
        print(f"  ERROR: expected JSON array, got {type(entries)}")
        return {}

    results = []
    passed = failed = skipped = 0

    for entry in entries:
        concept_key = entry.get("concept_key", "")
        probe_id = entry.get("probe_id", "")
        code = entry.get("code", "")

        probe = get_probe(concept_key, probe_id)
        if not probe:
            print(f"  SKIP {probe_id} — concept not found")
            skipped += 1
            continue

        if not code or not code.strip():
            print(f"  SKIP {probe_id} — empty code")
            skipped += 1
            continue

        t0 = time.time()
        if probe.get("verifiable", True):
            ok, err, stdout = run_probe(code, probe)
        else:
            # No compile harness for this language — accept non-empty code
            ok, err, stdout = True, "", ""
        elapsed = round(time.time() - t0, 2)

        status = "PASS" if ok else "FAIL"
        verify_tag = "" if probe.get("verifiable", True) else " [unverified]"
        print(
            f"  {status}{verify_tag} [{probe_id}]  ({elapsed}s)"
            + (f"  {err[:80]}" if not ok else "")
        )

        concept = ALL_CONCEPTS[concept_key]
        results.append(
            {
                "concept_key": concept_key,
                "probe_id": probe_id,
                "lang": probe["lang"],
                "model": model_name,
                "passed": ok,
                "elapsed": elapsed,
                "error": err[:300] if not ok else "",
                # Training data fields (only populated on pass)
                "instruction": probe["prompt"] if ok else "",
                "system": concept["system"] if ok else "",
                "output": _strip_fences(code) if ok else "",
            }
        )

        if ok:
            passed += 1
        else:
            failed += 1

    total = passed + failed
    pct = round(100 * passed / total) if total else 0
    print(f"\n  {model_name}: {passed}/{total} ({pct}%) passed  |  {skipped} skipped")

    # Save verified results
    out_path = CORPUS_DIR / f"verified_{model_name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved → {out_path}")

    return {model_name: results}


def merge_to_jsonl(all_results: dict[str, list]) -> Path:
    """Deduplicate by (concept_key, probe_id, instruction+output hash) and write lora_train.jsonl"""
    seen = set()
    training_pairs = []

    for model_name, results in all_results.items():
        for r in results:
            if not r["passed"]:
                continue
            key = (r["concept_key"], r["probe_id"], r["output"][:50])
            if key in seen:
                continue
            seen.add(key)
            training_pairs.append(
                {
                    "system": r["system"],
                    "instruction": r["instruction"],
                    "output": r["output"],
                    "meta": {
                        "concept": r["concept_key"],
                        "probe": r["probe_id"],
                        "lang": r["lang"],
                        "source_model": r["model"],
                    },
                }
            )

    out_path = CORPUS_DIR / "lora_train.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for pair in training_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    print(f"\n  Merged {len(training_pairs)} unique training pairs → {out_path}")
    return out_path


def print_comparison_table(all_results: dict[str, list]):
    """Print pass rate per model per concept"""
    concept_keys = list(ALL_CONCEPTS.keys())
    models = list(all_results.keys())

    print(f"\n{'=' * 80}")
    print("  CORPUS COMPARISON TABLE")
    print(f"{'=' * 80}")
    print(f"  {'Concept':<22}  {'Lang':<5}" + "".join(f"  {m[:14]:>14}" for m in models))
    print(f"  {'-' * 22}  {'-' * 5}" + "".join(f"  {'-' * 14}" for _ in models))

    for ck in concept_keys:
        lang = ALL_CONCEPTS[ck]["lang"]
        row = f"  {ck:<22}  {lang:<5}"
        for model_name in models:
            results = all_results.get(model_name, [])
            model_probes = [r for r in results if r["concept_key"] == ck]
            if not model_probes:
                row += f"  {'--':>14}"
                continue
            p = sum(1 for r in model_probes if r["passed"])
            t = len(model_probes)
            row += f"  {f'{p}/{t} ({round(100 * p / t)}%)':>14}"
        print(row)

    print(f"  {'-' * 22}  {'-' * 5}" + "".join(f"  {'-' * 14}" for _ in models))

    # Totals
    row = f"  {'TOTAL':<22}  {'':5}"
    for model_name in models:
        results = all_results.get(model_name, [])
        p = sum(1 for r in results if r["passed"])
        t = len([r for r in results if r["concept_key"] in ALL_CONCEPTS])
        row += f"  {f'{p}/{t} ({round(100 * p / t) if t else 0}%)':>14}"
    print(row)
    print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="batch_*.json files to process")
    parser.add_argument("--all", action="store_true", help="Process all batch_*.json in corpus dir")
    parser.add_argument(
        "--merge", action="store_true", help="Merge passing outputs into lora_train.jsonl"
    )
    args = parser.parse_args()

    files = []
    if args.all:
        files = sorted(CORPUS_DIR.glob("batch_*.json"))
        if not files:
            print(f"No batch_*.json files found in {CORPUS_DIR}")
            sys.exit(1)
    else:
        files = [Path(f) for f in args.files]

    if not files:
        print("Specify files or use --all")
        sys.exit(1)

    all_results: dict[str, list] = {}
    for f in files:
        r = process_file(f)
        all_results.update(r)

    if len(all_results) > 1:
        print_comparison_table(all_results)

    if args.merge:
        merge_to_jsonl(all_results)
    elif all_results:
        total_passing = sum(1 for results in all_results.values() for r in results if r["passed"])
        print(f"\n  Total passing solutions across all models: {total_passing}")
        print("  Run with --merge to write lora_train.jsonl")


if __name__ == "__main__":
    main()
