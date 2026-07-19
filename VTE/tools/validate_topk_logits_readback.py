"""
Correctness validation for VTE_TOPK_LOGITS_READBACK=1 (TopKLogitsReducer,
vte/core/topk_logits_reducer.py + Sampler.pick_greedy_from_gpu_candidates).

Runs the SAME greedy (temperature=0) generation twice in the same process --
once with the feature disabled (full logits readback + Sampler.sample(), the
existing, long-tested path) and once enabled (GPU-side top-k reduction) --
and asserts the generated token sequence is BIT-IDENTICAL. Greedy decode is
fully deterministic, so any divergence here is a real correctness bug, not
noise.

Includes a repetition-stress prompt designed to push the model into a
repetitive loop (the exact scenario the repetition-penalty correctness
argument needs to hold up under -- see the kernel's own comment and
Sampler.pick_greedy_from_gpu_candidates' docstring), since that's precisely
where the "window token shadows a non-window runner-up in the same thread
group" edge case would show up if the implementation were wrong.

Usage:
    python tools/validate_topk_logits_readback.py <model_id>
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

PROMPTS = [
    ("normal", "Write a long, detailed essay about the history of space exploration.", 300),
    ("repetition_stress", "Repeat the word 'the' one hundred times separated by spaces:", 250),
    ("short_factual", "What is the capital of France?", 60),
    ("code_gen", "Write a Python function that implements quicksort, with comments explaining each step.", 300),
    ("list_style", "List 50 interesting facts about the ocean, one per line.", 300),
    ("story", "Tell me a short story about a robot who learns to paint.", 300),
    ("technical", "Explain how transformers and attention mechanisms work in deep learning, in detail.", 300),
]


def run_generation(model, prompt, max_tokens):
    tokens = []
    stats = {}
    for word in model.generate(prompt, max_tokens=max_tokens, temperature=0.0, stats=stats):
        tokens.append(word)
    return "".join(tokens), stats


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    print(f"Model: {model_id}\n")

    all_passed = True

    for label, prompt, max_tokens in PROMPTS:
        print(f"=== {label} (max_tokens={max_tokens}) ===")

        os.environ.pop("VTE_TOPK_LOGITS_READBACK", None)
        from vte.core.model import VTEModel
        model_off = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)
        text_off, stats_off = run_generation(model_off, prompt, max_tokens)
        model_off.unload()

        os.environ["VTE_TOPK_LOGITS_READBACK"] = "1"
        # Force a fresh import path state -- VTEModel itself reads the env
        # var only at __init__ time (self._topk_reducer setup), so a NEW
        # instance picks it up; no need to reload the module.
        model_on = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)
        text_on, stats_on = run_generation(model_on, prompt, max_tokens)
        model_on.unload()
        os.environ.pop("VTE_TOPK_LOGITS_READBACK", None)

        match = (text_off == text_on)
        all_passed = all_passed and match
        print(f"  tokens generated: off={stats_off.get('completion_tokens')}  on={stats_on.get('completion_tokens')}")
        print(f"  tok/s: off={stats_off.get('decoding_speed_tps'):.2f}  on={stats_on.get('decoding_speed_tps'):.2f}")
        print(f"  IDENTICAL: {match}")
        if not match:
            print(f"  --- OFF (first 300 chars) ---\n{text_off[:300]!r}")
            print(f"  --- ON  (first 300 chars) ---\n{text_on[:300]!r}")
            for i, (a, b) in enumerate(zip(text_off, text_on)):
                if a != b:
                    print(f"  first char divergence at position {i}: off={a!r} on={b!r}")
                    break
        print()

    print("=== RESULT ===")
    print("ALL PASSED (bit-identical)" if all_passed else "MISMATCH FOUND -- see above")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
