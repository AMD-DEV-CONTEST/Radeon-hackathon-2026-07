"""
Breaks down the ~1ms/tok "outer-loop" overhead found outside execute_decode()
(model.py's generate() loop: sampling, logits readback, detokenize, keepalive)
into its actual components, instead of guessing.

Concrete candidate identified by reading model.py's generate() loop: _read_logits()
does a device-to-host memcpy of the FULL vocabulary logits (151936 fp16 values,
~304KB for Qwen2.5) on EVERY decode token, tag="logits_d2h". This is the same
absolute size regardless of model parameter count (same tokenizer/vocab across
Qwen2.5 1.5B/7B) -- a real candidate for a roughly-constant per-token cost that
would explain why the outer-loop overhead doesn't shrink much on faster models.

Usage:
    python tools/bench_outer_loop_breakdown.py <model_id> [n_tokens]
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

PROMPT = "Write a long, detailed essay about the history of space exploration."
WARMUP_TOKENS = 30
DEFAULT_N_TOKENS = 200


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    n_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_N_TOKENS

    print(f"Model: {model_id}  |  decode tokens measured: {n_tokens}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)

    stats = {"logits_d2h_ms": 0.0, "logits_d2h_calls": 0,
              "sample_ms": 0.0, "sample_calls": 0,
              "decode_bytes_ms": 0.0, "decode_bytes_calls": 0,
              "keepalive_ms": 0.0, "keepalive_calls": 0}

    orig_memcpy = model._hip.safe_memcpy_device_to_host
    orig_sample = model.sampler.sample
    orig_decode_bytes = model.tokenizer.decode_bytes
    orig_pulse = model._keepalive.pulse

    def patched_memcpy(dst, src, tag="unnamed"):
        if tag != "logits_d2h":
            return orig_memcpy(dst, src, tag)
        t0 = time.perf_counter()
        r = orig_memcpy(dst, src, tag)
        stats["logits_d2h_ms"] += (time.perf_counter() - t0) * 1000.0
        stats["logits_d2h_calls"] += 1
        return r

    def patched_sample(**kwargs):
        t0 = time.perf_counter()
        r = orig_sample(**kwargs)
        stats["sample_ms"] += (time.perf_counter() - t0) * 1000.0
        stats["sample_calls"] += 1
        return r

    def patched_decode_bytes(token_ids):
        t0 = time.perf_counter()
        r = orig_decode_bytes(token_ids)
        stats["decode_bytes_ms"] += (time.perf_counter() - t0) * 1000.0
        stats["decode_bytes_calls"] += 1
        return r

    def patched_pulse(*args, **kwargs):
        t0 = time.perf_counter()
        r = orig_pulse(*args, **kwargs)
        stats["keepalive_ms"] += (time.perf_counter() - t0) * 1000.0
        stats["keepalive_calls"] += 1
        return r

    model._hip.safe_memcpy_device_to_host = patched_memcpy
    model.sampler.sample = patched_sample
    model.tokenizer.decode_bytes = patched_decode_bytes
    model._keepalive.pulse = patched_pulse

    t_wall0 = time.perf_counter()
    for _ in model.generate(PROMPT, max_tokens=WARMUP_TOKENS, temperature=0.0):
        pass

    for k in stats:
        stats[k] = 0
    t_wall0 = time.perf_counter()

    gen_stats = {}
    for _ in model.generate(PROMPT, max_tokens=n_tokens, temperature=0.0, stats=gen_stats):
        pass
    t_wall1 = time.perf_counter()

    model._hip.safe_memcpy_device_to_host = orig_memcpy
    model.sampler.sample = orig_sample
    model.tokenizer.decode_bytes = orig_decode_bytes
    model._keepalive.pulse = orig_pulse

    n = stats["sample_calls"]
    total_generate_wall_ms = (t_wall1 - t_wall0) * 1000.0

    print(f"\ndecode tokens sampled: {n}")
    print(f"{'component':<24} {'total ms':>10} {'ms/tok':>10}")
    for label, key in [
        ("logits D2H memcpy", "logits_d2h_ms"),
        ("sampler.sample()", "sample_ms"),
        ("tokenizer.decode_bytes()", "decode_bytes_ms"),
        ("keepalive.pulse()", "keepalive_ms"),
    ]:
        v = stats[key]
        print(f"{label:<24} {v:>10.2f} {v/n:>10.4f}")

    tps = gen_stats.get("decoding_speed_tps")
    print(f"\ntotal generate() wall time (incl. execute_decode + everything above): "
          f"{total_generate_wall_ms/n:.4f} ms/tok")
    print(f"production decoding_speed_tps: {tps:.2f} tok/s -> {1000.0/tps:.4f} ms/tok")

    model.unload()


if __name__ == "__main__":
    main()
