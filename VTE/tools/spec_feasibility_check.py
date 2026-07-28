"""
Thesis V7/V8, feasibility check for real draft-model speculative decoding
(Qwen2.5 0.5B draft vs 1.5B target) -- Fase 2 (draft).

Loads the sequences saved by spec_feasibility_gen.py (real greedy
target-model continuations) and, for each position i in the generated
span, prefixes the DRAFT model with [prompt + continuation[:i]] and asks
for 1 greedy token, comparing its decoded text against the target's actual
token-i text. Since both models are the same Qwen2.5 family and share one
BPE tokenizer/vocab, text-level comparison of a single decoded token is
equivalent to token-id comparison -- verified below (vocab size compared,
not assumed) before trusting the result.

This measures raw single-token argmax agreement, the standard cheap proxy
for speculative-decoding feasibility used before building the real
verify/reject/KV-rollback machinery (same posture as V4's PLD check).

Usage:
    python tools/spec_feasibility_gen.py [target] [json_path]     # run first, separate process
    python tools/spec_feasibility_check.py [draft_pull_name] [json_path]
    (defaults: qwen2.5:0.5b-q4_k_m-draft, spec_feasibility_sequences.json)
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

DRAFT_NAME = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:0.5b-q4_k_m-draft"
IN_PATH = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "spec_feasibility_sequences.json")


def main():
    with open(IN_PATH) as f:
        sequences = json.load(f)

    draft = VTEModel.from_pretrained(DRAFT_NAME, context_length=2048)
    draft_tok = draft.tokenizer

    results = {}
    for name, seq in sequences.items():
        full_ids = seq["full_ids"]
        prompt_len = seq["prompt_len"]

        matches = 0
        total = 0
        for i in range(prompt_len, len(full_ids) - 1):
            prefix_text = draft_tok.decode(full_ids[:i])
            actual_next_text = draft_tok.decode([full_ids[i]])

            gen = draft.generate(prefix_text, max_tokens=1, temperature=0.0)
            draft_text = ''.join(list(gen)) if hasattr(gen, '__iter__') else gen

            if draft_text == actual_next_text:
                matches += 1
            total += 1

        rate = matches / total if total else 0.0
        results[name] = (matches, total, rate)
        print(f"[{name}]: {matches}/{total} = {rate*100:.1f}% concordancia")

    overall = sum(r[2] for r in results.values()) / len(results)
    print(f"\n=== RESULTADO ===")
    for name, (m, t, rate) in results.items():
        print(f"  {name}: {m}/{t} = {rate*100:.1f}%")
    print(f"  overall (media simples): {overall*100:.1f}%")

    print(f"\n=== GATE (definido antes de medir, mesma logica do V4/PLD) ===")
    if overall >= 0.55:
        print(f"{overall*100:.1f}% >= 55% -- VALE implementar speculative decoding de verdade (4-6h).")
    elif overall >= 0.40:
        print(f"{overall*100:.1f}% entre 40-55% -- zona cinzenta, avaliar caso a caso antes de comprometer.")
    else:
        print(f"{overall*100:.1f}% < 40% -- NAO vale, mesmo patamar do PLD (27.6%, ver PERFORMANCE.md). Ir para KV cache Q8_0 em vez disso.")


if __name__ == "__main__":
    main()
