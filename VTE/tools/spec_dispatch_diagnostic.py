"""
Thesis V7/V8, speculative decoding pre-implementation diagnostic.

Measures RAW kernel dispatch+execution cost of "4x draft decode-graph
launches + 1x verify decode-graph launch (batch=5)" against "1x target
decode-graph launch", with NO accept/reject logic, NO KV rollback, NO
speculative-decoding logic at all -- just the graph launches themselves,
since a prior implementation of real speculative decoding on the RX7600
measured 0.09-0.26x of baseline (4-11x SLOWER), and dispatch overhead
(eager per-layer launches, not HIP-Graph-captured) is the leading
hypothesis for that result (see docs/LIMITATIONS.md "Reverted features").
This gate answers: does that same dispatch-bound failure mode reproduce
here (both draft and target/verify ARE HIP-Graph-captured this time), or
was it specific to the RX7600/Windows environment (WDDM P-state drops,
narrower bandwidth)?

Loads BOTH the draft (1.5B) and target (32B) models in the SAME process
-- confirms HIPRuntime._live_instance_count's multi-instance design
(see hip_runtime.py) actually works for a draft+target pair, not just in
theory.

Usage:
    python tools/spec_dispatch_diagnostic.py
"""
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel
from vte.core.batched_hip_graph_executor import BatchedHIPGraphExecutor

N_ITERS = 50
N_WARMUP = 10


def time_calls(fn, n, warmup):
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    t1 = time.perf_counter()
    return (t1 - t0) / n * 1000.0  # ms/call


def main():
    print("Carregando draft (Qwen2.5 1.5B)...")
    draft = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", context_length=2048)
    list(draft.generate("hi", max_tokens=1, temperature=0.0))
    print("Draft carregado.")

    print("Carregando alvo (Qwen2.5 32B)...")
    target = VTEModel.from_pretrained("qwen2.5:32b-q4_k_m", context_length=2048, max_batch_size=8)
    list(target.generate("hi", max_tokens=1, temperature=0.0))
    print("Alvo carregado -- ambos coexistindo no mesmo processo com sucesso.")

    hip_t = target._hip
    hip_d = draft._hip
    pos = 5

    def target_step():
        target.executor.execute_decode(100, kv_offset=pos)
        hip_t.synchronize()

    def draft_4x():
        for i in range(4):
            draft.executor.execute_decode(100, kv_offset=pos + i)
        hip_d.synchronize()

    print("Construindo executor batched de verificacao (batch=5) no alvo...")
    batch_size = 5
    batch_tensor_mapping = target._mapper.allocate_batch_runtime_state(
        target.tensor_mapping, target._allocator, hip_t, target._context_length,
        batch_size, profiler=target.profiler
    )
    lm_head_batch_info = None
    try:
        lm_head_batch_info = target._resolve_lm_head_capture_info(
            batch_size=batch_size, tensor_mapping=batch_tensor_mapping
        )
    except Exception as e:
        print(f"  (lm head batch capture indisponivel, seguindo sem: {e})")

    batch_executor = BatchedHIPGraphExecutor(
        hip_t, target._allocator, target._graph, batch_tensor_mapping,
        target.metadata, batch_size=batch_size, lm_head_info=lm_head_batch_info
    )

    def verify_5x():
        batch_executor.execute_decode_batch([100] * batch_size, [pos] * batch_size)

    print("\nMedindo baseline do alvo (1x decode step)...")
    t_target = time_calls(target_step, N_ITERS, N_WARMUP)
    print(f"  {t_target:.3f} ms/iter")

    print("Medindo draft (4x decode steps, 1 sync no final)...")
    t_draft = time_calls(draft_4x, N_ITERS, N_WARMUP)
    print(f"  {t_draft:.3f} ms/iter")

    print("Medindo verify (batch=5, 1 chamada)...")
    t_verify = time_calls(verify_5x, N_ITERS, N_WARMUP)
    print(f"  {t_verify:.3f} ms/iter")

    total_spec = t_draft + t_verify
    ratio = total_spec / t_target

    print(f"\n=== RESULTADO ===")
    print(f"target baseline (1x):              {t_target:.3f} ms")
    print(f"draft (4x) + verify (batch=5):      {t_draft:.3f} + {t_verify:.3f} = {total_spec:.3f} ms")
    print(f"ratio (spec dispatch / target):     {ratio:.2f}x")

    print(f"\n=== GATE (definido antes de medir) ===")
    if ratio < 2.0:
        print(f"{ratio:.2f}x < 2.0x -- VIAVEL. Overhead de dispatch NAO domina. Prosseguir com speculative.py real.")
    elif ratio > 3.0:
        print(f"{ratio:.2f}x > 3.0x -- MORTO DE NOVO. Mesma causa raiz (dispatch/sincronizacao), nao vale reimplementar.")
    else:
        print(f"{ratio:.2f}x entre 2-3x -- zona cinzenta, avaliar com cuidado antes de comprometer 4-6h.")


if __name__ == "__main__":
    main()
