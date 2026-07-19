"""
Thesis V6 follow-up -- measures the achieved memory bandwidth of
gemv_q6k_kernel in isolation, against a same-topology read-bandwidth
baseline (no dequant, no MAC), to determine whether it has the same kind
of recoverable headroom that gemv_q4k had before the header-coalescing fix.

Motivation: reading gemv_q6k.hip.template directly (not assumed) shows an
even BIGGER redundancy than gemv_q4k had -- ALL 64 threads in a block
independently re-read the SAME superblock header (`d`, 2 bytes at blk+208)
every iteration, vs gemv_q4k's 8-threads-per-sbgroup redundancy. Q6_K is
Qwen3.5 2B's PRIMARY quantization (not just a tied-embedding fallback like
it is for some other architectures), so a real fix here would matter for
that model's whole FFN/QKV path, not a narrow slice.

Uses the FFN-down shape (in_features=6144, out_features=2048, Qwen3.5 2B's
largest single Q6_K GEMV per layer -- hidden=2048, ffn=6144, confirmed by
loading the real model's metadata, not assumed).

Same methodology as tools/bench_gemv_q4k_bandwidth.py (arrived at only
after several failed approaches there -- see that file's docstring for the
full history): long warm-up, GPU-only per-launch event timing
(VTE_PROFILE=1), multiple trials reporting median/min/max, cold round-robin
buffer pool to defeat the Infinity Cache.

Usage:
    python tools/bench_gemv_q6k_bandwidth.py
"""
import ctypes
import os
import statistics
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ["VTE_PROFILE"] = "1"

from vte.core.model import VTEModel
from vte.compiler.codegen import CodegenEngine
from vte.bridge.kernel_profiler import PROFILER

IN_FEATURES = 6144   # Qwen3.5 2B: ffn (feed_forward_length)
OUT_FEATURES = 2048  # Qwen3.5 2B: hidden (embedding_length)
N_SB = IN_FEATURES // 256
ROW_BYTES = N_SB * 210   # bloco Q6_K = 210 bytes / 256 elementos
N_ITERS = 500
WARMUP_ITERS = 300
N_TRIALS = 5
NUM_COPIES = 40

NULL_KERNEL_SRC = r"""
#include <hip/hip_runtime.h>

extern "C" __global__ void null_kernel() {}
"""

BW_BASELINE_SRC = r"""
#include <hip/hip_runtime.h>

extern "C" __global__ void bw_baseline_kernel(
    const void* __restrict__ src,
    void* __restrict__ dst_scalar,
    int row_bytes
) {
    __shared__ unsigned int partial[64];
    int row = blockIdx.x;
    int tid = threadIdx.x;
    int bs = blockDim.x;

    const uint4* s = reinterpret_cast<const uint4*>((const unsigned char*)src + (size_t)row * row_bytes);
    int n_vec = row_bytes / 16;

    unsigned int acc = 0;
    for (int i = tid; i < n_vec; i += bs) {
        uint4 v = s[i];
        acc += v.x + v.y + v.z + v.w;
    }
    partial[tid] = acc;
    __syncthreads();

    if (tid == 0) {
        unsigned int total = 0;
        for (int i = 0; i < bs; i++) total += partial[i];
        ((unsigned int*)dst_scalar)[row] = total;
    }
}
"""


def generate_q6_k_blocks(num_rows: int, row_bytes: int) -> bytes:
    """Bloco Q6_K real (210 bytes): [0:128]ql [128:192]qh [192:208]scales(int8) [208:210]d(fp16)."""
    blocks = bytearray(num_rows * row_bytes)
    n_sb = row_bytes // 210
    for r in range(num_rows):
        for sb in range(n_sb):
            offset = r * row_bytes + sb * 210
            for i in range(128):
                blocks[offset + i] = np.random.randint(0, 256)          # ql
            for i in range(64):
                blocks[offset + 128 + i] = np.random.randint(0, 256)    # qh
            for i in range(16):
                blocks[offset + 192 + i] = np.random.randint(0, 256)    # scales (int8, qualquer byte serve p/ bandwidth)
            blocks[offset + 208:offset + 210] = np.array([0.1], dtype=np.float16).tobytes()  # d
    return bytes(blocks)


def _compile_standalone(hip, scratch_dir: str, arch: str, src: str, filename: str, kernel_name: str):
    src_path = os.path.join(scratch_dir, f"{filename}.hip")
    hsaco_path = os.path.join(scratch_dir, f"{filename}.hsaco")
    with open(src_path, "w") as f:
        f.write(src)

    import subprocess
    env = os.environ.copy()
    hip_root = env.get("HIP_PATH") or env.get("ROCM_PATH")
    if hip_root:
        bin_dir = os.path.join(hip_root, "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

    cmd = ["hipcc", "--genco", f"--offload-arch={arch}", "-O3", src_path, "-o", hsaco_path]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile {filename}:\n{result.stdout}\n{result.stderr}")

    return hip.load_kernel(hsaco_path, kernel_name)


def time_launches_gpu_only(launch_fn, n_iters: int, category: str) -> float:
    PROFILER.set_category(category)
    PROFILER.gpu_ms[category] = 0.0
    PROFILER.counts[category] = 0
    for i in range(n_iters):
        launch_fn(i)
    return PROFILER.gpu_ms[category] / PROFILER.counts[category]


def run_trial(hip, launch_null, launch_gemv, launch_baseline, total_weight_bytes: float) -> dict:
    for i in range(WARMUP_ITERS):
        launch_null(i)
    hip.synchronize()
    null_ms = time_launches_gpu_only(launch_null, N_ITERS, "bench_null")

    for i in range(WARMUP_ITERS):
        launch_gemv(i)
    hip.synchronize()
    gemv_ms = time_launches_gpu_only(launch_gemv, N_ITERS, "bench_gemv")

    for i in range(WARMUP_ITERS):
        launch_baseline(i)
    hip.synchronize()
    baseline_ms = time_launches_gpu_only(launch_baseline, N_ITERS, "bench_baseline")

    gemv_ms_corrected = max(gemv_ms - null_ms, 1e-6)
    baseline_ms_corrected = max(baseline_ms - null_ms, 1e-6)
    gemv_gbps = (total_weight_bytes / 1e9) / (gemv_ms_corrected / 1000.0)
    baseline_gbps = (total_weight_bytes / 1e9) / (baseline_ms_corrected / 1000.0)

    return {
        "null_ms": null_ms,
        "gemv_ms": gemv_ms, "gemv_ms_corrected": gemv_ms_corrected, "gemv_gbps": gemv_gbps,
        "baseline_ms": baseline_ms, "baseline_ms_corrected": baseline_ms_corrected, "baseline_gbps": baseline_gbps,
        "ratio": gemv_gbps / baseline_gbps,
    }


def main():
    print(f"Shape: in_features={IN_FEATURES}, out_features={OUT_FEATURES}, "
          f"n_sb={N_SB}, row_bytes={ROW_BYTES}, total_weight_bytes={OUT_FEATURES * ROW_BYTES:,}")

    model = VTEModel.from_pretrained("qwen3.5:2b-q6_k", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    arch = hip.get_gpu_architecture()
    hip._throttle_before_dispatch = lambda: None

    weight_bytes = generate_q6_k_blocks(OUT_FEATURES, ROW_BYTES)
    total_weight_bytes = len(weight_bytes)
    assert total_weight_bytes == OUT_FEATURES * ROW_BYTES

    x_fp16 = np.random.randn(IN_FEATURES).astype(np.float16)
    out_fp16 = np.zeros(OUT_FEATURES, dtype=np.float16)

    x_block = hip.safe_malloc(x_fp16.nbytes, "bench_x")
    out_block = hip.safe_malloc(out_fp16.nbytes, "bench_out")
    hip.safe_memcpy_host_to_device(x_block, x_fp16.tobytes(), "bench_x_h2d")

    w_blocks = []
    for i in range(NUM_COPIES):
        wb = hip.safe_malloc(total_weight_bytes, f"bench_w_{i}")
        hip.safe_memcpy_host_to_device(wb, weight_bytes, f"bench_w_h2d_{i}")
        w_blocks.append(wb)
    print(f"Weight pool: {NUM_COPIES} copies x {total_weight_bytes/1e6:.1f}MB = "
          f"{NUM_COPIES*total_weight_bytes/1e6:.1f}MB (Infinity Cache is 32MB)")

    scratch_dir = os.path.dirname(os.path.abspath(__file__))

    _, null_fn = _compile_standalone(hip, scratch_dir, arch, NULL_KERNEL_SRC, "null_bench_q6k", "null_kernel")
    codegen = CodegenEngine()
    gemv_hsaco = codegen.compile_kernel("gemv_q6k", arch=arch)
    _, gemv_fn = hip.load_kernel(gemv_hsaco, "gemv_q6k_kernel")
    dst_scalar = hip.safe_malloc(OUT_FEATURES * 4, "bench_dst_scalar")
    _, baseline_fn = _compile_standalone(hip, scratch_dir, arch, BW_BASELINE_SRC, "bw_baseline_q6k", "bw_baseline_kernel")

    def launch_null(i):
        hip.launch_kernel(null_fn, grid=(1, 1, 1), block=(1, 1, 1), args=[], shared_mem=0, expected_args=0)

    def launch_gemv(i):
        args = [
            x_block, w_blocks[i % NUM_COPIES], out_block,
            ctypes.c_int(1), ctypes.c_int(1),
            ctypes.c_int(IN_FEATURES), ctypes.c_int(OUT_FEATURES),
            ctypes.c_void_p(0), ctypes.c_void_p(0), ctypes.c_float(1.0),
        ]
        hip.launch_kernel(gemv_fn, grid=(OUT_FEATURES, 1, 1), block=(64, 1, 1),
                           args=args, shared_mem=0, expected_args=10)

    def launch_baseline(i):
        args = [w_blocks[i % NUM_COPIES], dst_scalar, ctypes.c_int(ROW_BYTES)]
        hip.launch_kernel(baseline_fn, grid=(OUT_FEATURES, 1, 1), block=(64, 1, 1),
                           args=args, shared_mem=0, expected_args=3)

    trials = []
    for t in range(N_TRIALS):
        r = run_trial(hip, launch_null, launch_gemv, launch_baseline, total_weight_bytes)
        trials.append(r)
        print(f"\nTrial {t+1}/{N_TRIALS}: null={r['null_ms']:.4f}ms  "
              f"gemv_q6k={r['gemv_gbps']:.1f} GB/s  baseline={r['baseline_gbps']:.1f} GB/s  "
              f"ratio={r['ratio']*100:.1f}%")

    ratios = [r["ratio"] for r in trials]
    gemv_gbps_all = [r["gemv_gbps"] for r in trials]
    baseline_gbps_all = [r["baseline_gbps"] for r in trials]
    median_ratio = statistics.median(ratios)

    print(f"\n=== SUMMARY across {N_TRIALS} trials ===")
    print(f"gemv_q6k GB/s: median={statistics.median(gemv_gbps_all):.1f}  "
          f"min={min(gemv_gbps_all):.1f}  max={max(gemv_gbps_all):.1f}")
    print(f"baseline GB/s: median={statistics.median(baseline_gbps_all):.1f}  "
          f"min={min(baseline_gbps_all):.1f}  max={max(baseline_gbps_all):.1f}")
    print(f"ratio: median={median_ratio*100:.1f}%  min={min(ratios)*100:.1f}%  max={max(ratios)*100:.1f}%")

    print(f"\n=== RESULT (gate decision uses the median) ===")
    if median_ratio >= 0.85:
        print(f"gemv_q6k achieves {median_ratio*100:.1f}% of the read-bandwidth baseline.")
        print("GATE: >=85% -- kernel is memory-saturated, no recoverable headroom via kernel changes. STOP.")
    elif median_ratio >= 0.55:
        print(f"gemv_q6k achieves {median_ratio*100:.1f}% of the read-bandwidth baseline.")
        print("GATE: 55-85% range -- real headroom exists. Proceed to a header-coalescing rewrite.")
    else:
        print(f"gemv_q6k achieves {median_ratio*100:.1f}% of the read-bandwidth baseline.")
        print("GATE: below 55% -- outside the expected band, investigate before proceeding.")


if __name__ == "__main__":
    main()
