"""
Follow-up: the isolated Sampler.sample() internals (bench_sampler_breakdown.py)
measured ~0.127ms/call for the greedy path, but the real production call
(bench_outer_loop_breakdown.py, wrapping the actual sampler.sample()) measured
~0.272ms/call -- a ~0.145ms/call gap not explained by copy+penalty+argmax
themselves.

Reading model.py's generate() call site directly surfaces two per-call costs
the isolated microbenchmark didn't include, because it passes fresh objects
each token instead of pre-built ones:

    next_token = self.sampler.sample(
        ...,
        generated_tokens=input_tokens[prompt_len:],           # list slice, grows every token
        ignore_tokens=set(self.tokenizer.special_tokens.values()),  # rebuilt from scratch EVERY token
    )

self.tokenizer.special_tokens is set once at tokenizer init and never
mutated during generation -- rebuilding a set from its .values() every
single decode token is pure repeated work with a static input. This
measures both costs directly against the real tokenizer object, instead of
assuming this is "the" explanation without checking magnitude.

Usage:
    python tools/bench_sampler_call_overhead.py <model_id>
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

N_REPEATS = 5000


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    print(f"Model: {model_id}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)

    special_tokens = model.tokenizer.special_tokens
    print(f"\ntokenizer.special_tokens entries: {len(special_tokens)}")

    # Cost of set(dict.values()) rebuilt every call, real dict.
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        s = set(special_tokens.values())
    set_rebuild_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    print(f"set(tokenizer.special_tokens.values()) per call: {set_rebuild_ms:.5f} ms")

    # Cost of the reference precomputed-once version (what it SHOULD cost
    # if hoisted out of the loop): effectively zero per call, just a name lookup.
    precomputed = set(special_tokens.values())
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        s = precomputed
    precomputed_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    print(f"reusing a precomputed set (hoisted once): {precomputed_ms:.5f} ms")

    # Cost of input_tokens[prompt_len:] slicing, at a realistic generation
    # length (simulate a 300-token growing history like the tok/s benchmarks
    # used elsewhere this session).
    prompt_len = 15
    input_tokens = list(range(prompt_len))
    slice_costs = []
    for extra in range(300):
        input_tokens.append(1000 + extra)
        if extra % 50 == 49:  # sample a few points along the growth curve
            t0 = time.perf_counter()
            for _ in range(N_REPEATS):
                window = input_tokens[prompt_len:]
            ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
            slice_costs.append((len(input_tokens) - prompt_len, ms))

    print(f"\ninput_tokens[prompt_len:] slice cost vs. generated-so-far length:")
    for length, ms in slice_costs:
        print(f"  {length:>4} tokens generated so far: {ms:.5f} ms/call")

    model.unload()


if __name__ == "__main__":
    main()
