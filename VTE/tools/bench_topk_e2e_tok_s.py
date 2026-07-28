"""
End-to-end tok/s measurement for VTE_TOPK_LOGITS_READBACK, following the same
discipline as Thesis V6's gemv_q4k A/B comparison: interleaved trials
(alternating which variant measures first each round) within ONE process, to
avoid the cross-process GPU-clock-variance trap that inflated the first
gemv_q4k comparison in V6.

The env var is only read at VTEModel.__init__ time, so each trial reloads the
model fresh with the flag set/unset -- more model-load overhead than ideal,
but it's the only way to toggle the feature per trial within one process.

Usage:
    python tools/bench_topk_e2e_tok_s.py <model_id> [n_trials]
"""
import os
import statistics
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

PROMPT = "Write a long, detailed essay about the history of space exploration."
MAX_TOKENS = 300
WARMUP_TOKENS = 20
N_TRIALS = 5


def measure_once(model_id: str, topk_enabled: bool) -> float:
    if topk_enabled:
        os.environ["VTE_TOPK_LOGITS_READBACK"] = "1"
    else:
        os.environ.pop("VTE_TOPK_LOGITS_READBACK", None)

    from vte.core.model import VTEModel
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)

    for _ in model.generate(PROMPT, max_tokens=WARMUP_TOKENS, temperature=0.0):
        pass

    stats = {}
    for _ in model.generate(PROMPT, max_tokens=MAX_TOKENS, temperature=0.0, stats=stats):
        pass
    tps = stats["decoding_speed_tps"]

    model.unload()
    os.environ.pop("VTE_TOPK_LOGITS_READBACK", None)
    return tps


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    n_trials = int(sys.argv[2]) if len(sys.argv) > 2 else N_TRIALS

    print(f"Model: {model_id}  |  trials: {n_trials}")

    off_vals, on_vals = [], []
    for t in range(n_trials):
        if t % 2 == 0:
            off_tps = measure_once(model_id, topk_enabled=False)
            on_tps = measure_once(model_id, topk_enabled=True)
            order = "off->on"
        else:
            on_tps = measure_once(model_id, topk_enabled=True)
            off_tps = measure_once(model_id, topk_enabled=False)
            order = "on->off"

        off_vals.append(off_tps)
        on_vals.append(on_tps)
        gain = (on_tps / off_tps - 1) * 100
        print(f"Trial {t+1}/{n_trials} ({order}): off={off_tps:.2f} tok/s  on={on_tps:.2f} tok/s  gain={gain:+.2f}%")

    print(f"\n=== SUMMARY ===")
    print(f"off: median={statistics.median(off_vals):.2f}  min={min(off_vals):.2f}  max={max(off_vals):.2f}")
    print(f"on:  median={statistics.median(on_vals):.2f}  min={min(on_vals):.2f}  max={max(on_vals):.2f}")

    per_trial_gain = [(on_vals[i] / off_vals[i] - 1) * 100 for i in range(n_trials)]
    print(f"per-trial gain: {[f'{g:+.2f}%' for g in per_trial_gain]}")
    print(f"mean gain: {statistics.mean(per_trial_gain):+.2f}%  stdev: {statistics.stdev(per_trial_gain):.2f}%  "
          f"median: {statistics.median(per_trial_gain):+.2f}%")
    n_positive = sum(1 for g in per_trial_gain if g > 0)
    print(f"trials favoring topk: {n_positive}/{n_trials}")

    median_gain = (statistics.median(on_vals) / statistics.median(off_vals) - 1) * 100
    print(f"\nmedian/median gain: {median_gain:+.2f}%")


if __name__ == "__main__":
    main()
