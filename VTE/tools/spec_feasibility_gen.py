"""
Thesis V7/V8, feasibility check for real draft-model speculative decoding
(Qwen2.5 0.5B draft vs 1.5B target) -- Fase 1 (target).

Mirrors V4's PLD feasibility check methodology (same 3 prompt categories:
favorable/code, borderline/repeat, unfavorable/creative) but for a real
draft model instead of n-gram lookup. Not a full speculative-decoding
implementation -- just generates real sequences with the TARGET model
(greedy, temperature=0) and saves the token-id sequences to disk, so a
SEPARATE process (spec_feasibility_check.py) can load the DRAFT model
without both models sharing one HIP context/process at once (VTE's
one-model-per-process design, same pattern vte-server/Lemonade rely on).

Usage:
    python tools/spec_feasibility_gen.py [target_pull_name] [out_path]
    (defaults: qwen2.5:1.5b-q4_k_m, spec_feasibility_sequences.json)
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

PROMPTS = {
    "favorable_code": "Write a Python function that checks if a number is prime. Include a docstring.",
    "borderline_repeat": "Summarize the following in exactly the same words, repeated verbatim: 'The quick brown fox jumps over the lazy dog.'",
    "unfavorable_creative": "Write a short, original opening line for a fantasy novel.",
}

MAX_TOKENS = 40
TARGET_NAME = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "spec_feasibility_sequences.json")


def main():
    target = VTEModel.from_pretrained(TARGET_NAME, context_length=2048)
    target_tok = target.tokenizer

    sequences = {}
    for name, prompt in PROMPTS.items():
        gen = target.generate(prompt, max_tokens=MAX_TOKENS, temperature=0.0)
        text = ''.join(list(gen)) if hasattr(gen, '__iter__') else gen
        full_text = prompt + text

        ids = target_tok.encode(full_text)
        if hasattr(ids, 'ids'):
            ids = ids.ids
        prompt_ids = target_tok.encode(prompt)
        if hasattr(prompt_ids, 'ids'):
            prompt_ids = prompt_ids.ids
        prompt_len = len(prompt_ids)

        sequences[name] = {"full_ids": list(ids), "prompt_len": prompt_len}
        print(f"[{name}] gerado: {len(ids) - prompt_len} tokens novos")
        print(f"  texto: {text[:150]}")

    with open(OUT_PATH, "w") as f:
        json.dump(sequences, f)
    print(f"\nSalvo em {OUT_PATH}")


if __name__ == "__main__":
    main()
