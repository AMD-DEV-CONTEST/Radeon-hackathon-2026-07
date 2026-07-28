"""
Sanity check on the previous instrumentation itself: bench_decode_step_breakdown.py
wraps graph_launch with 2 extra hipEventRecord calls plus hipEventElapsedTime
(which forces its own hipEventSynchronize) -- none of that exists in real
production code. Before treating the measured ~1-2ms/tok "gap" as a real
optimization target, this checks whether that gap is partly just the cost
of the measurement tooling itself.

Method: wrap executor.execute_decode() with a SINGLE perf_counter pair (zero
extra ctypes/HIP calls) to get the leanest possible per-token wall-clock
measurement, then compare against:
  (a) the production stats['decoding_speed_tps'] number (zero instrumentation
      at all, includes sampling/detokenize outside execute_decode too)
  (b) the heavier HIP-event-instrumented "TOTAL" bucket from
      bench_decode_step_breakdown.py

If (lean measurement) is close to production ms/tok minus the outer-loop
sampling cost, and clearly LOWER than the heavier instrumented total, that
means the earlier "gap" was significantly inflated by the measurement tool.

Usage:
    python tools/bench_lean_decode_step.py <model_id> [n_tokens]
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
    executor = model.executor

    orig_execute_decode = executor.execute_decode
    total_ms = [0.0]
    call_count = [0]

    def lean_wrapped(token_id, kv_offset):
        t0 = time.perf_counter()
        orig_execute_decode(token_id, kv_offset)
        total_ms[0] += (time.perf_counter() - t0) * 1000.0
        call_count[0] += 1

    executor.execute_decode = lean_wrapped

    for _ in model.generate(PROMPT, max_tokens=WARMUP_TOKENS, temperature=0.0):
        pass

    total_ms[0] = 0.0
    call_count[0] = 0

    gen_stats = {}
    for _ in model.generate(PROMPT, max_tokens=n_tokens, temperature=0.0, stats=gen_stats):
        pass

    executor.execute_decode = orig_execute_decode

    lean_ms_per_tok = total_ms[0] / call_count[0]
    tps = gen_stats.get("decoding_speed_tps")
    production_ms_per_tok = 1000.0 / tps if tps else float("nan")

    print(f"\nexecute_decode() calls measured: {call_count[0]}")
    print(f"lean execute_decode() wall time:  {lean_ms_per_tok:.4f} ms/tok  (single perf_counter pair, zero HIP events)")
    print(f"production decoding_speed_tps:     {tps:.2f} tok/s  ->  {production_ms_per_tok:.4f} ms/tok (includes sampling/detokenize outside execute_decode)")
    print(f"outer-loop overhead (production - lean execute_decode): {production_ms_per_tok - lean_ms_per_tok:+.4f} ms/tok")

    model.unload()


if __name__ == "__main__":
    main()
