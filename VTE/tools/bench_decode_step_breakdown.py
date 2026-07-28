"""
Follow-up to the duty-cycle diagnostic -- breaks a real production decode
step (HIPGraphExecutor.execute_decode) into its actual wall-clock buckets,
instead of guessing why Qwen 1.5B's duty cycle (86-87%) sits below Qwen
7B's (95-96%).

Concrete, falsifiable hypothesis being tested here (not assumed): HIPRuntime
has a production 95% GPU duty-cycle safety limiter (vte/bridge/hip_runtime.py
_enforce_duty_cycle_limit, self._duty_cycle_limit = 0.95, called from both
_throttle_before_dispatch() before every launch and _throttle_duty_cycle()
after every synchronize()). Qwen 7B's measured 95.6-96.1% duty cycle sits
suspiciously exactly at that ceiling -- consistent with the limiter actively
inserting sleeps to cap it there, meaning 7B's REAL uncapped duty cycle may
be even higher (more tok/s left on the table). Qwen 1.5B's 86-87% is well
BELOW the 95% trigger point, so the limiter should almost never engage for
it -- if true, 1.5B's gap must come from something else entirely (fixed
per-token CPU-side overhead -- staging-buffer memcpys, ctypes dispatch call
overhead -- being a bigger fraction of its smaller per-token time budget),
not from "big kernels being unoptimized" (which would also predict LOWER
duty cycle for the bigger model, the opposite of what's measured).

Usage:
    python tools/bench_decode_step_breakdown.py <model_id> [n_tokens]
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

PROMPT = "Write a long, detailed essay about the history of space exploration."
WARMUP_TOKENS = 30
DEFAULT_N_TOKENS = 200


def instrument(model, n_tokens: int):
    hip = model._hip
    executor = model.executor

    orig_update_staging = executor._update_staging_buffers
    orig_throttle_before = hip._throttle_before_dispatch
    orig_graph_launch = hip.graph_launch
    orig_synchronize = hip.synchronize

    ev_start = hip.event_create()
    ev_stop = hip.event_create()

    stats = {
        "staging_ms": 0.0,
        "throttle_before_ms": 0.0,
        "graph_launch_wall_ms": 0.0,
        "gpu_busy_ms": 0.0,
        "synchronize_ms": 0.0,
        "decode_calls": 0,
        "throttle_before_sleep_events": 0,
        "synchronize_sleep_events": 0,
    }

    def patched_update_staging(token_id, kv_offset):
        t0 = time.perf_counter()
        orig_update_staging(token_id, kv_offset)
        stats["staging_ms"] += (time.perf_counter() - t0) * 1000.0

    def patched_throttle_before():
        t0 = time.perf_counter()
        orig_throttle_before()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        stats["throttle_before_ms"] += dt_ms
        if dt_ms > 1.0:  # a bare deque check is microseconds; >1ms means it slept
            stats["throttle_before_sleep_events"] += 1

    def patched_graph_launch(graph_exec):
        is_decode = (executor.decode_graph is not None
                     and graph_exec.value == executor.decode_graph.value)
        if not is_decode:
            return orig_graph_launch(graph_exec)

        t0 = time.perf_counter()
        hip.event_record(ev_start)
        orig_graph_launch(graph_exec)
        hip.event_record(ev_stop)
        gpu_ms = hip.event_elapsed_ms(ev_start, ev_stop)
        t1 = time.perf_counter()

        stats["graph_launch_wall_ms"] += (t1 - t0) * 1000.0
        stats["gpu_busy_ms"] += gpu_ms
        stats["decode_calls"] += 1

    def patched_synchronize():
        t0 = time.perf_counter()
        result = orig_synchronize()
        dt_ms = (time.perf_counter() - t0) * 1000.0
        stats["synchronize_ms"] += dt_ms
        if dt_ms > 1.0:
            stats["synchronize_sleep_events"] += 1
        return result

    executor._update_staging_buffers = patched_update_staging
    hip._throttle_before_dispatch = patched_throttle_before
    hip.graph_launch = patched_graph_launch
    hip.synchronize = patched_synchronize

    for _ in model.generate(PROMPT, max_tokens=WARMUP_TOKENS, temperature=0.0):
        pass

    for key in stats:
        stats[key] = 0

    gen_stats = {}
    for _ in model.generate(PROMPT, max_tokens=n_tokens, temperature=0.0, stats=gen_stats):
        pass

    executor._update_staging_buffers = orig_update_staging
    hip._throttle_before_dispatch = orig_throttle_before
    hip.graph_launch = orig_graph_launch
    hip.synchronize = orig_synchronize

    return stats, gen_stats


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    n_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_N_TOKENS

    print(f"Model: {model_id}  |  decode tokens measured: {n_tokens}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)

    stats, gen_stats = instrument(model, n_tokens)
    n = stats["decode_calls"]

    total_wall_ms = stats["staging_ms"] + stats["graph_launch_wall_ms"] + stats["synchronize_ms"]

    print(f"\ndecode steps measured: {n}")
    print(f"{'bucket':<28} {'total ms':>10} {'ms/tok':>10} {'% of wall':>10}")
    for label, key in [
        ("staging buffer memcpys", "staging_ms"),
        ("graph_launch (wall)", "graph_launch_wall_ms"),
        ("  of which GPU-busy", "gpu_busy_ms"),
        ("synchronize()", "synchronize_ms"),
    ]:
        v = stats[key]
        pct = v / total_wall_ms * 100.0 if total_wall_ms > 0 else float("nan")
        print(f"{label:<28} {v:>10.1f} {v/n:>10.4f} {pct:>9.1f}%")

    print(f"{'TOTAL (staging+launch+sync)':<28} {total_wall_ms:>10.1f} {total_wall_ms/n:>10.4f} {100.0:>9.1f}%")

    print(f"\nthrottle_before_dispatch(): {stats['throttle_before_ms']:.2f}ms total "
          f"({stats['throttle_before_ms']/n:.4f} ms/tok), "
          f"{stats['throttle_before_sleep_events']}/{n} calls took >1ms (likely slept)")
    print(f"synchronize() calls that took >1ms (likely slept in _throttle_duty_cycle): "
          f"{stats['synchronize_sleep_events']}/{n}")

    print(f"\ntok/s (production stats): {gen_stats.get('decoding_speed_tps'):.2f}")

    model.unload()


if __name__ == "__main__":
    main()
