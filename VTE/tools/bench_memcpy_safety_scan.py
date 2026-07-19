"""
Follow-up to the outer-loop breakdown: safe_memcpy_device_to_host() (used for
the every-token logits readback, tag="logits_d2h") does a SAFETY CHECK before
the real hipMemcpy call -- a plain Python for-loop scanning self._active_allocations
(a dict of every tracked VRAM allocation: weights, KV cache, arena, scratch
buffers) to confirm the source pointer belongs to a known allocation
(vte/bridge/hip_runtime.py, safe_memcpy_device_to_host, ~line 737).

With hundreds of persistent buffers per model (log shows "Buffers persistentes
alocados: 393 tensores"), this is a real O(n) Python-level linear scan on
EVERY logits readback -- a plausible, concrete, and fully explainable
candidate for (part of) the measured 0.38ms/tok logits-memcpy cost, entirely
separate from actual PCIe transfer time.

This measures, without touching any production code:
  1. How many entries are actually in _active_allocations for each model.
  2. How long the scan itself takes in isolation, replicated against the
     real dict, for the real logits buffer pointer.
  3. How long the raw hipMemcpy call takes in isolation (same transfer size,
     no safety scan) as a reference "the transfer itself" cost.

Usage:
    python tools/bench_memcpy_safety_scan.py <model_id>
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

N_REPEATS = 2000


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    print(f"Model: {model_id}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)
    hip = model._hip

    allocations = hip._active_allocations
    print(f"\n_active_allocations entries: {len(allocations)}")

    # Find the real logits buffer pointer the same way generate() does.
    lm_head_captured = getattr(model.executor, 'lm_head_info', None) is not None
    if lm_head_captured:
        logits_ptr_val = model.lm_head.logits_buffer
    else:
        raise RuntimeError("This diagnostic assumes LM head is captured in the HIP graph (production default).")

    src_val = logits_ptr_val.value if hasattr(logits_ptr_val, 'value') else logits_ptr_val
    vocab_size = model.lm_head.vocab_size
    dst_len = vocab_size * 2  # fp16

    # Find where in iteration order the match sits (position matters for a
    # linear scan -- an early match is cheap regardless of dict size).
    match_position = None
    for i, (alloc_base, (size, t)) in enumerate(allocations.items()):
        if alloc_base <= src_val < alloc_base + size:
            match_position = i
            break
    print(f"logits buffer pointer found at scan position: {match_position} / {len(allocations)}")

    # 1) Time the scan alone, replicated exactly, many times for a stable average.
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        for alloc_base, (size, t) in allocations.items():
            if alloc_base <= src_val < alloc_base + size:
                break
    scan_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    print(f"\nsafety-scan alone: {scan_ms:.5f} ms/call  (over {N_REPEATS} repeats)")

    # 2) Time the real safe_memcpy_device_to_host() call (scan + real hipMemcpy).
    dst = bytearray(dst_len)
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        hip.safe_memcpy_device_to_host(dst, ctypes.c_void_p(src_val), tag="logits_d2h")
    full_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    print(f"full safe_memcpy_device_to_host(): {full_ms:.5f} ms/call")

    # 3) Time the RAW hipMemcpy call directly, bypassing the safety scan
    #    entirely, as a reference for "transfer + ctypes call only".
    c_dst = (ctypes.c_char * dst_len).from_buffer(dst)
    HIP_MEMCPY_D2H = 2  # hipMemcpyDeviceToHost, matches hip_runtime.py's constant
    t0 = time.perf_counter()
    for _ in range(N_REPEATS):
        hip._lib.hipMemcpy(c_dst, ctypes.c_void_p(src_val), dst_len, HIP_MEMCPY_D2H)
    raw_ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
    print(f"raw hipMemcpy() only (no safety scan): {raw_ms:.5f} ms/call")

    print(f"\nscan overhead as fraction of full call: {scan_ms/full_ms*100:.1f}%")
    print(f"raw transfer as fraction of full call:  {raw_ms/full_ms*100:.1f}%")
    print(f"(bytes transferred per call: {dst_len:,})")

    model.unload()


if __name__ == "__main__":
    main()
