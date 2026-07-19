"""
Follow-up to Thesis V6 -- tests the hypothesis the user raised from watching
Task Manager live: after the B1 gemv_q4k speedup, Qwen2.5 1.5B's GPU usage
dropped ~90%->70% while the bigger models (7B/8B) stayed pinned at ~90%.

Task Manager's default "GPU" graph in the Performance tab is usually the 3D
engine, not necessarily the Compute engine HIP kernels run on -- so before
trusting that number at all, this measures the same idea with tool-independent
HIP events: for each real decode-graph replay (HIPGraphExecutor.execute_decode,
the actual production path), record how much of the token's WALL-CLOCK time
was spent with the GPU actually busy (HIP-event-measured) vs. idle/dispatch
overhead.

duty_cycle = total_gpu_busy_ms / total_wall_clock_ms, over many decode tokens.

A low/dropping duty cycle after B1 (mainly on the smallest model) would
support "1.5B become dispatch-bound"; a duty cycle that stays high on 7B/8B
supports "those are still genuinely GPU-bound", matching the bigger tok/s
gains measured there in Thesis V6.

Usage:
    python tools/bench_dispatch_vs_gpu_duty.py <model_id> [n_tokens]
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

PROMPT = "Write a long, detailed essay about the history of space exploration."
WARMUP_TOKENS = 30
DEFAULT_N_TOKENS = 200


def instrument_decode_duty_cycle(model, n_tokens: int):
    hip = model._hip
    executor = model.executor

    orig_graph_launch = hip.graph_launch
    ev_start = hip.event_create()
    ev_stop = hip.event_create()

    stats = {"gpu_ms": 0.0, "wall_ms": 0.0, "decode_calls": 0, "other_calls": 0}

    def patched_graph_launch(graph_exec):
        is_decode = (executor.decode_graph is not None
                     and graph_exec.value == executor.decode_graph.value)
        if not is_decode:
            stats["other_calls"] += 1
            return orig_graph_launch(graph_exec)

        t0 = time.perf_counter()
        hip.event_record(ev_start)
        orig_graph_launch(graph_exec)
        hip.event_record(ev_stop)
        gpu_ms = hip.event_elapsed_ms(ev_start, ev_stop)
        t1 = time.perf_counter()

        stats["gpu_ms"] += gpu_ms
        stats["wall_ms"] += (t1 - t0) * 1000.0
        stats["decode_calls"] += 1

    hip.graph_launch = patched_graph_launch

    # Warmup: first calls pay graph-capture cost, and clocks need to reach a
    # stable boost state (same lesson as Thesis V6 Phase A).
    for _ in model.generate(PROMPT, max_tokens=WARMUP_TOKENS, temperature=0.0):
        pass

    stats["gpu_ms"] = 0.0
    stats["wall_ms"] = 0.0
    stats["decode_calls"] = 0

    gen_stats = {}
    for _ in model.generate(PROMPT, max_tokens=n_tokens, temperature=0.0, stats=gen_stats):
        pass

    hip.graph_launch = orig_graph_launch

    return stats, gen_stats


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    n_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_N_TOKENS

    print(f"Model: {model_id}  |  decode tokens measured: {n_tokens}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)

    stats, gen_stats = instrument_decode_duty_cycle(model, n_tokens)

    duty_cycle = stats["gpu_ms"] / stats["wall_ms"] * 100.0 if stats["wall_ms"] > 0 else float("nan")
    ms_per_tok_wall = stats["wall_ms"] / stats["decode_calls"]
    ms_per_tok_gpu = stats["gpu_ms"] / stats["decode_calls"]

    print(f"\ndecode-graph replays measured: {stats['decode_calls']}")
    print(f"total wall-clock time:  {stats['wall_ms']:.1f} ms  ({ms_per_tok_wall:.3f} ms/tok)")
    print(f"total GPU-busy time:    {stats['gpu_ms']:.1f} ms  ({ms_per_tok_gpu:.3f} ms/tok)")
    print(f"GPU DUTY CYCLE:         {duty_cycle:.1f}%")
    print(f"tok/s (production stats, unaffected by instrumentation): {gen_stats.get('decoding_speed_tps'):.2f}")

    model.unload()


if __name__ == "__main__":
    main()
