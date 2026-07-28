"""
Thesis V7, Pilar 2 -- same methodology as tools/bench_gemv_q4k_bandwidth.py
(Thesis V6, Phase A), applied to a shape that was never profiled before:
Qwen2.5 32B's FFN-down GEMV (in_features=27648, out_features=5120, from the
model's real published config.json -- hidden_size=5120,
intermediate_size=27648, confirmed against huggingface.co/Qwen/Qwen2.5-32B-Instruct,
not assumed).

Answers whether the ~20-22 tok/s ceiling both VTE and llama.cpp hit on this
model on the W7900 is a real memory-bandwidth wall or has headroom, using the
exact same achieved-vs-baseline-bandwidth gate as V6 (55-85% = headroom
exists, >=85% = saturated, no kernel-level fix available).

Bootstraps the HIP runtime via the small Qwen2.5 1.5B model (already present
on this instance) purely to get a `HIPRuntime`/`CodegenEngine` handle -- the
32B GGUF itself is never loaded, since this benchmark only needs the kernel
and synthetic weight buffers at the target shape, not real model weights.

Usage:
    python tools/bench_gemv_q4k_bandwidth_qwen32b.py
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

IN_FEATURES = 27648   # Qwen2.5-32B intermediate_size (real config, not guessed)
OUT_FEATURES = 5120    # Qwen2.5-32B hidden_size
N_SB = IN_FEATURES // 256
ROW_BYTES = N_SB * 144
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
        acc += v.x + v.y + v.z + v.w;  // touches all loaded data, prevents dead-code elimination
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


def generate_q4_k_m_blocks(num_rows: int, row_bytes: int) -> bytes:
    """Same generator shape as tools/validate_matmul.py's, sized per-row."""
    blocks = bytearray(num_rows * row_bytes)
    n_sb = row_bytes // 144
    for r in range(num_rows):
        for sb in range(n_sb):
            offset = r * row_bytes + sb * 144
            blocks[offset:offset + 2] = np.array([0.1], dtype=np.float16).tobytes()
            blocks[offset + 2:offset + 4] = np.array([0.05], dtype=np.float16).tobytes()
            for i in range(12):
                blocks[offset + 4 + i] = np.random.randint(0, 10)
            for i in range(128):
                blocks[offset + 16 + i] = np.random.randint(0, 256)
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
    """Runs n_iters launches, returns ms/launch of real GPU-silicon time,
    using HIPRuntime.launch_kernel()'s own built-in per-launch profiling
    (VTE_PROFILE=1)."""
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
    print(f"Shape: Qwen2.5-32B FFN-down, in_features={IN_FEATURES}, out_features={OUT_FEATURES}, "
          f"n_sb={N_SB}, row_bytes={ROW_BYTES}, total_weight_bytes={OUT_FEATURES * ROW_BYTES:,}")

    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    arch = hip.get_gpu_architecture()

    hip._throttle_before_dispatch = lambda: None

    weight_bytes = generate_q4_k_m_blocks(OUT_FEATURES, ROW_BYTES)
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
          f"{NUM_COPIES*total_weight_bytes/1e6:.1f}MB")

    scratch_dir = os.path.dirname(os.path.abspath(__file__))

    _, null_fn = _compile_standalone(hip, scratch_dir, arch, NULL_KERNEL_SRC, "null_bench_32b", "null_kernel")
    codegen = CodegenEngine()
    gemv_hsaco = codegen.compile_kernel("gemv_q4k", arch=arch)
    _, gemv_fn = hip.load_kernel(gemv_hsaco, "gemv_q4k_kernel")
    dst_scalar = hip.safe_malloc(OUT_FEATURES * 4, "bench_dst_scalar")
    _, baseline_fn = _compile_standalone(hip, scratch_dir, arch, BW_BASELINE_SRC, "bw_baseline_32b", "bw_baseline_kernel")

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
              f"gemv_q4k={r['gemv_gbps']:.1f} GB/s  baseline={r['baseline_gbps']:.1f} GB/s  "
              f"ratio={r['ratio']*100:.1f}%")

    ratios = [r["ratio"] for r in trials]
    gemv_gbps_all = [r["gemv_gbps"] for r in trials]
    baseline_gbps_all = [r["baseline_gbps"] for r in trials]
    median_ratio = statistics.median(ratios)

    print(f"\n=== SUMMARY across {N_TRIALS} trials ===")
    print(f"gemv_q4k GB/s: median={statistics.median(gemv_gbps_all):.1f}  "
          f"min={min(gemv_gbps_all):.1f}  max={max(gemv_gbps_all):.1f}")
    print(f"baseline GB/s: median={statistics.median(baseline_gbps_all):.1f}  "
          f"min={min(baseline_gbps_all):.1f}  max={max(baseline_gbps_all):.1f}")
    print(f"ratio: median={median_ratio*100:.1f}%  min={min(ratios)*100:.1f}%  max={max(ratios)*100:.1f}%")

    print(f"\n=== RESULT (gate decision uses the median) ===")
    if median_ratio >= 0.85:
        print(f"gemv_q4k achieves {median_ratio*100:.1f}% of the read-bandwidth baseline on the Qwen2.5-32B shape.")
        print("GATE: >=85% -- kernel is memory-saturated, no recoverable headroom via kernel changes. STOP.")
    elif median_ratio >= 0.55:
        print(f"gemv_q4k achieves {median_ratio*100:.1f}% of the read-bandwidth baseline on the Qwen2.5-32B shape.")
        print("GATE: 55-85% range -- real headroom exists. Proceed to Phase B (header-coalescing already applied via V6, so this would need a further kernel-level fix).")
    else:
        print(f"gemv_q4k achieves {median_ratio*100:.1f}% of the read-bandwidth baseline on the Qwen2.5-32B shape.")
        print("GATE: below 55% -- outside the expected band, investigate before proceeding.")


if __name__ == "__main__":
    main()
