"""
Thesis V7/V8, speculative decoding diagnostic -- CORRECTED verify mechanism.

The first diagnostic (spec_dispatch_diagnostic.py) reused generate_batch()'s
BatchedHIPGraphExecutor with 5 INDEPENDENT per-slot KV caches (batch =
parallel independent sequences), which is architecturally wrong for
speculative-decoding verify: the k+1 candidates are CONSECUTIVE POSITIONS
of the SAME sequence, sharing ONE physical KV cache, not independent
sequences. That measured 171ms/verify (batch=5) -- ~4x a single target
decode step, when it should cost close to 1x (same weight-read dominates,
regardless of how many query positions ride along).

This version builds a tensor_mapping that reuses the target model's REAL
weight/KV-cache/RoPE-cache pointers directly (no new KV pool allocated,
no `kv_batch_stride_elements` key -- absence of that key is what makes the
kernels treat the batch_size slots as consecutive positions of one shared
sequence instead of independent ones), mirroring the design recovered from
a prior session's deleted `speculative_verify_executor.py` (recovered via
bytecode inspection, referenced in docs/LIMITATIONS.md's "Reverted
features" section -- this diagnostic exists specifically because that
prior implementation's eager-dispatch version measured 0.09-0.26x of
baseline, and it's unclear whether that was dispatch overhead, this same
independent-KV verify inefficiency, or something else; isolating just the
verify cost here answers that).

Usage:
    python tools/spec_dispatch_diagnostic_shared_kv.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.bridge.memory import MemoryRegion
from vte.core.model import VTEModel
from vte.core.batched_hip_graph_executor import BatchedHIPGraphExecutor

N_ITERS = 50
N_WARMUP = 10
K = 4  # draft tokens; verify batch_size = K+1


def time_calls(fn, n, warmup):
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    t1 = time.perf_counter()
    return (t1 - t0) / n * 1000.0


def build_verify_tensor_mapping(model, batch_size):
    """Reuses the model's REAL weight/KV-cache/RoPE-cache pointers (shared,
    no new pool) -- only real GGUF weight names are copied (never the whole
    tensor_mapping, which also holds 1-row activation buffers that would
    make allocate_batched_activation_buffers skip allocating new
    batch_size-row ones). No `kv_batch_stride_elements` key: this is what
    makes the kernels treat the batch_size slots as consecutive positions
    of ONE shared sequence instead of independent per-slot KV caches."""
    real_weight_names = set(model.parser.tensors.keys())
    tensor_mapping = {}
    for name, ptr in model.tensor_mapping.items():
        if name in real_weight_names:
            tensor_mapping[name] = ptr

    num_layers = model.metadata.get('block_count', 28)
    for l in range(num_layers):
        for key in (f'blk.{l}.kv_cache.k', f'blk.{l}.kv_cache.v'):
            if key in model.tensor_mapping:
                tensor_mapping[key] = model.tensor_mapping[key]
    for key in ('rope_cos', 'rope_sin'):
        if key in model.tensor_mapping:
            tensor_mapping[key] = model.tensor_mapping[key]

    # 'input_embeddings' is an INPUT-type graph node (the embedding-lookup
    # kernel's output, downstream RMSNorm's input) -- allocate_batched_
    # activation_buffers explicitly skips INPUT/OUTPUT nodes, so this
    # buffer needs a manual, batch_size-row allocation, same as
    # generate_batch()'s own path does (not caught by either the real-
    # weight filter above or the generic activation-buffer allocator).
    hidden_size = model.metadata.get('embedding_length', 1536)
    io_size = batch_size * hidden_size * 2  # fp16
    io_block = model._allocator.allocate(io_size, "speculative_verify_io", MemoryRegion.ACTIVATIONS)
    tensor_mapping['input_embeddings'] = io_block.ptr

    return tensor_mapping


def main():
    print("Carregando alvo (Qwen2.5 32B)...")
    target = VTEModel.from_pretrained("qwen2.5:32b-q4_k_m", context_length=2048, max_batch_size=8)
    list(target.generate("hi", max_tokens=1, temperature=0.0))
    print("Alvo carregado.")

    hip_t = target._hip
    pos = 5
    batch_size = K + 1

    def target_step():
        target.executor.execute_decode(100, kv_offset=pos)
        hip_t.synchronize()

    print(f"\nConstruindo verify tensor_mapping compartilhado (batch_size={batch_size}, KV cache REAL reaproveitado)...")
    verify_tensor_mapping = build_verify_tensor_mapping(target, batch_size)
    print(f"  {len(verify_tensor_mapping)} entradas copiadas (pesos reais + KV cache + RoPE cache).")

    lm_head_batch_info = None
    try:
        lm_head_batch_info = target._resolve_lm_head_capture_info(
            batch_size=batch_size, tensor_mapping=verify_tensor_mapping
        )
    except Exception as e:
        print(f"  (lm head batch capture indisponivel, seguindo sem: {e})")

    verify_executor = BatchedHIPGraphExecutor(
        hip_t, target._allocator, target._graph, verify_tensor_mapping,
        target.metadata, batch_size=batch_size, lm_head_info=lm_head_batch_info
    )

    kv_offsets = [pos + i for i in range(batch_size)]

    def verify_shared():
        verify_executor.execute_decode_batch([100] * batch_size, kv_offsets)

    print("\nMedindo baseline do alvo (1x decode step)...")
    t_target = time_calls(target_step, N_ITERS, N_WARMUP)
    print(f"  {t_target:.3f} ms/iter")

    print(f"Medindo verify COMPARTILHADO (batch={batch_size}, KV cache real reaproveitado)...")
    t_verify = time_calls(verify_shared, N_ITERS, N_WARMUP)
    print(f"  {t_verify:.3f} ms/iter")

    ratio = t_verify / t_target
    print(f"\n=== RESULTADO ===")
    print(f"target baseline (1x):               {t_target:.3f} ms")
    print(f"verify compartilhado (batch={batch_size}):       {t_verify:.3f} ms")
    print(f"ratio (verify / target single-step): {ratio:.2f}x")

    print(f"\n=== GATE (definido antes de medir) ===")
    if t_verify < 55:
        print(f"{t_verify:.1f}ms < 55ms -- speculative VIVO, speedup esperado ~1.5x com K={K}, alpha medido.")
    elif t_verify > 80:
        print(f"{t_verify:.1f}ms > 80ms -- ineficiencia fundamental no batched path, speedup ~1.1x, nao vale.")
    else:
        print(f"{t_verify:.1f}ms entre 55-80ms -- zona intermediaria, avaliar speedup projetado com cuidado.")


if __name__ == "__main__":
    main()
