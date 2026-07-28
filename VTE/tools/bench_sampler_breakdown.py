"""
Follow-up: breaks Sampler.sample() itself into its internal steps for the
GREEDY path (temperature=0.0), which is what every benchmark this session
has used for reproducibility -- and, on reading vte/core/sampler.py directly,
is NOT the path the "vectorized sampler" top-k optimization documented in
docs/PERFORMANCE.md actually speeds up. Reading the code: the top_k/top_p
narrowing only happens AFTER the `if temperature <= 0.0: return argmax(logits)`
early return -- greedy decode still does a full .copy() of the whole
151936-entry array, the (vectorized but still real) repetition-penalty
computation, and a full-array np.argmax(), every single token.

This measures each step in isolation, using the actual vocab size and a
realistic repeated-token pattern, instead of assuming the vectorized-sampler
optimization applies uniformly across all decode modes.

Usage:
    python tools/bench_sampler_breakdown.py [vocab_size]
"""
import sys
import time

import numpy as np

VOCAB_SIZE = int(sys.argv[1]) if len(sys.argv) > 1 else 151936
N_REPEATS = 2000
REPETITION_WINDOW = 512
REPETITION_COUNT_CAP = 10
REPETITION_PENALTY = 1.1


def main():
    print(f"vocab_size={VOCAB_SIZE}, repeats={N_REPEATS}")

    rng = np.random.RandomState(42)
    logits_src = rng.randn(VOCAB_SIZE).astype(np.float32)
    # Realistic generated-token history: a 512-token sliding window with some repeats.
    generated_tokens = list(rng.randint(0, VOCAB_SIZE, size=REPETITION_WINDOW))
    ignore_tokens = set()

    # 1. logits.copy()
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        logits = logits_src.copy()
    copy_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS

    # 2. repetition penalty block (vectorized, as in sampler.py)
    def repetition_penalty_step(logits):
        window = generated_tokens[-REPETITION_WINDOW:]
        token_ids_arr = np.asarray(window, dtype=np.int64)
        token_ids_arr = token_ids_arr[token_ids_arr < len(logits)]
        if ignore_tokens and token_ids_arr.size > 0:
            mask = np.isin(token_ids_arr, list(ignore_tokens), invert=True)
            token_ids_arr = token_ids_arr[mask]
        if token_ids_arr.size > 0:
            unique_ids, counts = np.unique(token_ids_arr, return_counts=True)
            counts = np.minimum(counts, REPETITION_COUNT_CAP).astype(np.float64)
            vals = logits[unique_ids]
            eff_penalty = REPETITION_PENALTY ** counts
            logits[unique_ids] = np.where(vals > 0, vals / eff_penalty, vals * eff_penalty)
        return logits

    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        logits = logits_src.copy()
        repetition_penalty_step(logits)
    copy_plus_penalty_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    penalty_only_ms = copy_plus_penalty_ms - copy_ms

    # 3. full argmax (the greedy path's actual final step)
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        logits = logits_src.copy()
        repetition_penalty_step(logits)
        result = int(np.argmax(logits))
    full_greedy_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    argmax_only_ms = full_greedy_ms - copy_plus_penalty_ms

    print(f"\n{'step':<28} {'ms/call':>10}")
    print(f"{'logits.copy()':<28} {copy_ms:>10.5f}")
    print(f"{'repetition penalty (vec.)':<28} {penalty_only_ms:>10.5f}")
    print(f"{'np.argmax() full array':<28} {argmax_only_ms:>10.5f}")
    print(f"{'TOTAL (greedy path)':<28} {full_greedy_ms:>10.5f}")

    # 4. Reference: what if top-k (e.g. 50) narrowing happened BEFORE argmax
    #    instead of operating on the full array (i.e. the same trick the
    #    non-greedy path already uses, applied to greedy too)?
    top_k = 50

    def narrowed_greedy(logits_full):
        # Still needs SOME full-array pass to know which indices are the
        # repetition-penalized ones and to find the top-k -- argpartition
        # over the full array is the honest cost here, not zero.
        top_indices = np.argpartition(logits_full, -top_k)[-top_k:]
        candidate = logits_full[top_indices]
        return int(top_indices[np.argmax(candidate)])

    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        logits = logits_src.copy()
        repetition_penalty_step(logits)
        result = narrowed_greedy(logits)
    narrowed_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    print(f"\n{'hypothetical: top-k argpartition then argmax':<45} {narrowed_ms:>10.5f} ms/call "
          f"({(narrowed_ms/full_greedy_ms - 1)*100:+.1f}% vs current full-array argmax)")


if __name__ == "__main__":
    main()
