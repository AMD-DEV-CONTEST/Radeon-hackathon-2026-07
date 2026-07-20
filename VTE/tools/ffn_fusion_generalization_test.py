"""
Thesis V7/V8, Pilar 3 generalization sweep: does the header-cached FFN
fusion fix generalize beyond Qwen2.5 1.5B (where it measured +3.5%)?

One model per invocation (VTE is one-model-per-process by design). Set
VTE_ENABLE_FFN_FUSION=1 in the environment to test the fused path.

Usage:
    python tools/ffn_fusion_generalization_test.py <pull_name> [n_trials]
    VTE_ENABLE_FFN_FUSION=1 python tools/ffn_fusion_generalization_test.py <pull_name> [n_trials]
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

PROMPT = "Explain what ROCm is in a few sentences."
MAX_TOKENS = 40


def main():
    pull_name = sys.argv[1]
    n_trials = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    fusion_on = bool(os.environ.get('VTE_ENABLE_FFN_FUSION'))
    print(f"=== {pull_name} | fusion={'ON' if fusion_on else 'OFF'} | trials={n_trials} ===")

    model = VTEModel.from_pretrained(pull_name, context_length=2048)

    tps_values = []
    for t in range(n_trials):
        stats = {}
        gen = model.generate(PROMPT, max_tokens=MAX_TOKENS, temperature=0.0, stats=stats)
        text = ''.join(list(gen)) if hasattr(gen, '__iter__') else gen
        tps = stats['decoding_speed_tps']
        tps_values.append(tps)
        print(f"  trial {t+1}: {tps:.2f} tok/s | texto: {text[:80]}")

    median_tps = statistics.median(tps_values)
    print(f"RESULT {pull_name} fusion={'ON' if fusion_on else 'OFF'}: median={median_tps:.2f} tok/s (trials: {tps_values})")


if __name__ == "__main__":
    main()
