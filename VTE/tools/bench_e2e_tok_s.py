"""
Thesis V6 -- end-to-end decode tok/s on every Q4_K model, using VTEModel's
own production stats accounting (decoding_speed_tps, excludes prefill --
see VTEModel.generate()'s docstring). Run this BEFORE and AFTER a kernel
change (e.g. via `git stash` / `git stash pop` around the two runs) to see
whether an isolated-kernel bandwidth gain shows up in real generation
speed.

Usage:
    python tools/bench_e2e_tok_s.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

MODELS = [
    "qwen2.5:1.5b-q4_k_m",
    "qwen2.5:7b-q4_k_m",
    "llama3.1:8b-instruct-q4_k_m",
]

PROMPT = "Write a long, detailed essay about the history of space exploration."
MAX_TOKENS = 300
N_RUNS = 3


def bench_model(model_id: str):
    print(f"\n{'='*70}\n{model_id}\n{'='*70}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)

    # Warmup: first generate() call pays HIP Graph capture cost.
    warm_stats = {}
    for _ in model.generate(PROMPT, max_tokens=20, temperature=0.0, stats=warm_stats):
        pass

    tps_runs = []
    last_text = ""
    for i in range(N_RUNS):
        stats = {}
        text = ""
        for token in model.generate(PROMPT, max_tokens=MAX_TOKENS, temperature=0.0, stats=stats):
            text += token
        tps = stats.get("decoding_speed_tps")
        completion = stats.get("completion_tokens")
        finish = stats.get("finish_reason")
        print(f"  run {i+1}/{N_RUNS}: {tps:.2f} tok/s  ({completion} tokens, finish={finish})")
        tps_runs.append(tps)
        last_text = text

    import statistics
    median_tps = statistics.median(tps_runs)
    print(f"  median: {median_tps:.2f} tok/s  (runs: {[f'{t:.1f}' for t in tps_runs]})")

    has_nan = "nan" in last_text.lower() and len(last_text) < 20
    sample = last_text[:200].replace("\n", " ")
    print(f"  sample output: {sample!r}")
    if len(last_text.strip()) < 10:
        print("  WARNING: suspiciously short/empty output, possible coherence issue")

    model.unload()
    return model_id, median_tps, tps_runs


def main():
    results = []
    for model_id in MODELS:
        try:
            results.append(bench_model(model_id))
        except Exception as e:
            print(f"  ERROR benchmarking {model_id}: {e}")
            import traceback
            traceback.print_exc()
            results.append((model_id, None, []))

    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    for model_id, median_tps, runs in results:
        if median_tps is not None:
            print(f"{model_id:40s} median={median_tps:.2f} tok/s")
        else:
            print(f"{model_id:40s} FAILED")


if __name__ == "__main__":
    main()
