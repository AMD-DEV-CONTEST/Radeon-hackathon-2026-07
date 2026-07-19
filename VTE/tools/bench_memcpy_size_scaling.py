"""
Follow-up: is the ~0.21ms/call D2H memcpy cost (measured for the 304KB
full-vocab logits readback) latency-bound or bandwidth-bound? This matters
directly for whether "do a top-k reduction on GPU, read back only ~50
candidates instead of 151936" would actually help -- if the cost is a fixed
per-call latency floor (WDDM/driver round-trip), shrinking the transfer size
alone won't shrink the measured time much; only reducing the NUMBER of
synchronous memcpy calls would.

Measures raw hipMemcpy(D2H) time across several transfer sizes, from a
realistic "top-k readback" size (~1KB: 50 floats + 50 int32 indices) up to
the current full-vocab size (304KB), on the same allocation each time (no
safety-scan/allocation-tracking noise -- pure transfer timing).

Usage:
    python tools/bench_memcpy_size_scaling.py <model_id>
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vte.core.model import VTEModel

N_REPEATS = 3000
HIP_MEMCPY_D2H = 2

SIZES = [
    (400, "~top-50 (50 floats + 50 int32 idx)"),
    (2048, "2KB"),
    (16384, "16KB"),
    (65536, "64KB"),
    (303872, "304KB (current full-vocab fp16)"),
]


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:1.5b-q4_k_m"
    print(f"Model: {model_id}")
    model = VTEModel.from_pretrained(model_id, use_hip_graph=True, enable_fusion=True)
    hip = model._hip

    lm_head_captured = getattr(model.executor, 'lm_head_info', None) is not None
    logits_ptr_val = model.lm_head.logits_buffer
    src_val = logits_ptr_val.value if hasattr(logits_ptr_val, 'value') else logits_ptr_val

    print(f"\n{'size':<10} {'label':<38} {'ms/call':>10} {'effective GB/s':>16}")
    for size_bytes, label in SIZES:
        dst = bytearray(size_bytes)
        c_dst = (ctypes.c_char * size_bytes).from_buffer(dst)

        # warmup
        for _ in range(50):
            hip._lib.hipMemcpy(c_dst, ctypes.c_void_p(src_val), size_bytes, HIP_MEMCPY_D2H)

        t0 = time.perf_counter()
        for _ in range(N_REPEATS):
            hip._lib.hipMemcpy(c_dst, ctypes.c_void_p(src_val), size_bytes, HIP_MEMCPY_D2H)
        ms = (time.perf_counter() - t0) * 1000.0 / N_REPEATS
        gbps = (size_bytes / 1e9) / (ms / 1000.0)
        print(f"{size_bytes:<10} {label:<38} {ms:>10.5f} {gbps:>16.3f}")

    model.unload()


if __name__ == "__main__":
    main()
