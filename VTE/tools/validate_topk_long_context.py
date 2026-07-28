"""
Long-context / long-generation validation for VTE_TOPK_LOGITS_READBACK
(graph-captured design), across all three Q4_K models. Two things this
specifically stresses that the earlier 250-300 token validations didn't:

1. context_length=2048 explicitly (VTEModel's own default, but made
   explicit here) with a generation long enough to approach it -- more KV
   cache growth, more decode-graph replays sharing the SAME captured
   topk_reduce_greedy node across a much longer run.
2. A much longer text generation increases the chance of hitting a genuine
   repetition loop or a rare fp16 tie (the exact edge case that caused the
   first correctness bug found in this investigation) purely by having far
   more decode steps to trigger it in.

Reports both correctness (bit-identical vs the full-array path) and tok/s
for each model.

Usage:
    python tools/validate_topk_long_context.py [model_id ...]
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

CONTEXT_LENGTH = 2048
MAX_TOKENS = 1500
PROMPT = ("Write a very long, detailed essay about the history of space exploration, "
          "covering the early rocketry pioneers, the Space Race, the Apollo program, "
          "the Space Shuttle era, the International Space Station, and the modern "
          "commercial spaceflight industry. Go into as much depth as possible.")

DEFAULT_MODELS = [
    "qwen2.5:1.5b-q4_k_m",
    "qwen2.5:7b-q4_k_m",
    "llama3.1:8b-instruct-q4_k_m",
]


def run_generation(model, prompt, max_tokens):
    tokens = []
    stats = {}
    for word in model.generate(prompt, max_tokens=max_tokens, temperature=0.0, stats=stats):
        tokens.append(word)
    return "".join(tokens), stats


def main():
    model_ids = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_MODELS

    results = []
    for model_id in model_ids:
        print(f"\n{'='*70}\n{model_id}  (context_length={CONTEXT_LENGTH}, max_tokens={MAX_TOKENS})\n{'='*70}")

        os.environ.pop("VTE_TOPK_LOGITS_READBACK", None)
        from vte.core.model import VTEModel
        model_off = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True,
                                              context_length=CONTEXT_LENGTH)
        text_off, stats_off = run_generation(model_off, PROMPT, MAX_TOKENS)
        model_off.unload()

        os.environ["VTE_TOPK_LOGITS_READBACK"] = "1"
        model_on = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True,
                                             context_length=CONTEXT_LENGTH)
        text_on, stats_on = run_generation(model_on, PROMPT, MAX_TOKENS)
        model_on.unload()
        os.environ.pop("VTE_TOPK_LOGITS_READBACK", None)

        match = (text_off == text_on)
        tps_off = stats_off.get("decoding_speed_tps")
        tps_on = stats_on.get("decoding_speed_tps")
        gain = (tps_on / tps_off - 1) * 100 if tps_off else float("nan")

        print(f"  tokens: off={stats_off.get('completion_tokens')}  on={stats_on.get('completion_tokens')}")
        print(f"  tok/s:  off={tps_off:.2f}  on={tps_on:.2f}  gain={gain:+.2f}%")
        print(f"  IDENTICAL: {match}")
        if not match:
            for i, (a, b) in enumerate(zip(text_off, text_on)):
                if a != b:
                    print(f"  first divergence at char {i}: off={a!r} on={b!r}")
                    print(f"  context off: ...{text_off[max(0,i-60):i+20]!r}...")
                    print(f"  context on:  ...{text_on[max(0,i-60):i+20]!r}...")
                    break

        results.append((model_id, match, tps_off, tps_on, gain))

    print(f"\n{'='*70}\nSUMMARY\n{'='*70}")
    all_passed = True
    for model_id, match, tps_off, tps_on, gain in results:
        all_passed = all_passed and match
        status = "IDENTICAL" if match else "MISMATCH"
        print(f"{model_id:30s} {status:10s} off={tps_off:.2f}  on={tps_on:.2f}  gain={gain:+.2f}%")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
