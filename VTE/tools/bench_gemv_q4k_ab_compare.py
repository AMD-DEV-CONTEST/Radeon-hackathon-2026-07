"""
Thesis V6, Phase B1 -- same-process, interleaved A/B comparison of the
original gemv_q4k_kernel (git HEAD) against the header-coalescing B1
rewrite (current working tree), against the SAME read-bandwidth baseline.

Why this exists: tools/bench_gemv_q4k_bandwidth.py run separately against
each kernel version (across two separate `python` process launches) showed
the RATIO improve (76.5% -> 82.8%) but the gemv_q4k kernel's own ABSOLUTE
GB/s actually went slightly DOWN (median 160.9 -> 156.4), while the
baseline kernel -- unchanged between the two runs -- also dropped (210.1 ->
195.9). That's a red flag: if an unchanged kernel's measured bandwidth
drifts >5% between two process launches, some of the "improvement" in the
ratio could be process-level GPU clock/thermal variance, not a real effect
of the code change. A trustworthy comparison needs both kernel versions
measured within the SAME process, back-to-back, ideally interleaved so any
monotonic drift (e.g. warming up over the run) hits both variants equally
rather than biasing whichever one happens to run first or second.

Usage:
    python tools/bench_gemv_q4k_ab_compare.py
"""
import ctypes
import os
import statistics
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ["VTE_PROFILE"] = "1"

from vte.core.model import VTEModel
from vte.compiler.codegen import CodegenEngine
from vte.bridge.kernel_profiler import PROFILER

IN_FEATURES = 8960
OUT_FEATURES = 1536
N_SB = IN_FEATURES // 256
ROW_BYTES = N_SB * 144
N_ITERS = 500
WARMUP_ITERS = 300
N_TRIALS = 15
NUM_COPIES = 40

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

ORIGINAL_GEMV_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..",
    "_scratch_gemv_q4k_original.hip"
)


def generate_q4_k_m_blocks(num_rows: int, row_bytes: int) -> bytes:
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


def _compile_standalone(hip, scratch_dir: str, arch: str, src_path: str, out_name: str, kernel_name: str):
    hsaco_path = os.path.join(scratch_dir, f"{out_name}.hsaco")

    env = os.environ.copy()
    hip_root = env.get("HIP_PATH") or env.get("ROCM_PATH")
    if hip_root:
        bin_dir = os.path.join(hip_root, "bin")
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")

    cmd = ["hipcc", "--genco", f"--offload-arch={arch}", "-O3", src_path, "-o", hsaco_path]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile {out_name}:\n{result.stdout}\n{result.stderr}")

    return hip.load_kernel(hsaco_path, kernel_name)


def _compile_inline(hip, scratch_dir: str, arch: str, src: str, out_name: str, kernel_name: str):
    src_path = os.path.join(scratch_dir, f"{out_name}.hip")
    with open(src_path, "w") as f:
        f.write(src)
    return _compile_standalone(hip, scratch_dir, arch, src_path, out_name, kernel_name)


def time_launches_gpu_only(launch_fn, n_iters: int, category: str) -> float:
    PROFILER.set_category(category)
    PROFILER.gpu_ms[category] = 0.0
    PROFILER.counts[category] = 0
    for i in range(n_iters):
        launch_fn(i)
    return PROFILER.gpu_ms[category] / PROFILER.counts[category]


def measure_one(hip, launch_fn, category: str) -> float:
    for i in range(WARMUP_ITERS):
        launch_fn(i)
    hip.synchronize()
    return time_launches_gpu_only(launch_fn, N_ITERS, category)


def main():
    print(f"Shape: in_features={IN_FEATURES}, out_features={OUT_FEATURES}, "
          f"n_sb={N_SB}, row_bytes={ROW_BYTES}, total_weight_bytes={OUT_FEATURES * ROW_BYTES:,}")

    if not os.path.exists(ORIGINAL_GEMV_PATH):
        print(f"ERROR: expected original kernel source at {ORIGINAL_GEMV_PATH}")
        print("Extract it first: git show HEAD:vte/compiler/templates/gemv_q4k.hip.template > _scratch_gemv_q4k_original.hip")
        sys.exit(1)

    model = VTEModel.from_pretrained("qwen2.5:1.5b-q4_k_m", use_hip_graph=False, enable_fusion=False)
    hip = model._hip
    arch = hip.get_gpu_architecture()
    hip._throttle_before_dispatch = lambda: None

    weight_bytes = generate_q4_k_m_blocks(OUT_FEATURES, ROW_BYTES)
    total_weight_bytes = len(weight_bytes)

    x_fp16 = np.random.randn(IN_FEATURES).astype(np.float16)
    out_fp16 = np.zeros(OUT_FEATURES, dtype=np.float16)

    x_block = hip.safe_malloc(x_fp16.nbytes, "bench_x")
    out_block_orig = hip.safe_malloc(out_fp16.nbytes, "bench_out_orig")
    out_block_b1 = hip.safe_malloc(out_fp16.nbytes, "bench_out_b1")
    hip.safe_memcpy_host_to_device(x_block, x_fp16.tobytes(), "bench_x_h2d")

    w_blocks = []
    for i in range(NUM_COPIES):
        wb = hip.safe_malloc(total_weight_bytes, f"bench_w_{i}")
        hip.safe_memcpy_host_to_device(wb, weight_bytes, f"bench_w_h2d_{i}")
        w_blocks.append(wb)
    print(f"Weight pool: {NUM_COPIES} copies x {total_weight_bytes/1e6:.1f}MB = "
          f"{NUM_COPIES*total_weight_bytes/1e6:.1f}MB (Infinity Cache is 32MB)")

    scratch_dir = os.path.dirname(os.path.abspath(__file__))

    codegen = CodegenEngine()
    b1_hsaco = codegen.compile_kernel("gemv_q4k", arch=arch, force_recompile=True)
    _, b1_fn = hip.load_kernel(b1_hsaco, "gemv_q4k_kernel")

    _, orig_fn = _compile_standalone(hip, scratch_dir, arch, ORIGINAL_GEMV_PATH, "gemv_q4k_original", "gemv_q4k_kernel")

    dst_scalar = hip.safe_malloc(OUT_FEATURES * 4, "bench_dst_scalar")
    _, baseline_fn = _compile_inline(hip, scratch_dir, arch, BW_BASELINE_SRC, "bw_baseline", "bw_baseline_kernel")

    def launch_orig(i):
        args = [
            x_block, w_blocks[i % NUM_COPIES], out_block_orig,
            ctypes.c_int(1), ctypes.c_int(1),
            ctypes.c_int(IN_FEATURES), ctypes.c_int(OUT_FEATURES),
            ctypes.c_void_p(0), ctypes.c_void_p(0), ctypes.c_float(1.0),
        ]
        hip.launch_kernel(orig_fn, grid=(OUT_FEATURES, 1, 1), block=(64, 1, 1),
                           args=args, shared_mem=0, expected_args=10)

    def launch_b1(i):
        args = [
            x_block, w_blocks[i % NUM_COPIES], out_block_b1,
            ctypes.c_int(1), ctypes.c_int(1),
            ctypes.c_int(IN_FEATURES), ctypes.c_int(OUT_FEATURES),
            ctypes.c_void_p(0), ctypes.c_void_p(0), ctypes.c_float(1.0),
        ]
        hip.launch_kernel(b1_fn, grid=(OUT_FEATURES, 1, 1), block=(64, 1, 1),
                           args=args, shared_mem=0, expected_args=10)

    def launch_baseline(i):
        args = [w_blocks[i % NUM_COPIES], dst_scalar, ctypes.c_int(ROW_BYTES)]
        hip.launch_kernel(baseline_fn, grid=(OUT_FEATURES, 1, 1), block=(64, 1, 1),
                           args=args, shared_mem=0, expected_args=3)

    # Interleaved: trial N does baseline, then original, then B1, in that
    # order, alternating which of original/B1 goes first every other trial
    # -- so neither variant systematically benefits from "runs when the GPU
    # is freshest" or "runs when the GPU is most warmed up".
    orig_gbps, b1_gbps, baseline_gbps = [], [], []
    for t in range(N_TRIALS):
        baseline_ms = measure_one(hip, launch_baseline, "ab_baseline")
        baseline_gb = (total_weight_bytes / 1e9) / (baseline_ms / 1000.0)

        if t % 2 == 0:
            orig_ms = measure_one(hip, launch_orig, "ab_orig")
            b1_ms = measure_one(hip, launch_b1, "ab_b1")
        else:
            b1_ms = measure_one(hip, launch_b1, "ab_b1")
            orig_ms = measure_one(hip, launch_orig, "ab_orig")

        orig_gb = (total_weight_bytes / 1e9) / (orig_ms / 1000.0)
        b1_gb = (total_weight_bytes / 1e9) / (b1_ms / 1000.0)

        orig_gbps.append(orig_gb)
        b1_gbps.append(b1_gb)
        baseline_gbps.append(baseline_gb)

        print(f"\nTrial {t+1}/{N_TRIALS} (order: {'orig->b1' if t % 2 == 0 else 'b1->orig'}): "
              f"baseline={baseline_gb:.1f} GB/s  original={orig_gb:.1f} GB/s ({orig_gb/baseline_gb*100:.1f}%)  "
              f"b1={b1_gb:.1f} GB/s ({b1_gb/baseline_gb*100:.1f}%)  "
              f"b1_vs_orig={(b1_gb/orig_gb - 1)*100:+.1f}%")

    print(f"\n=== SUMMARY across {N_TRIALS} interleaved trials (same process) ===")
    print(f"baseline GB/s: median={statistics.median(baseline_gbps):.1f}  min={min(baseline_gbps):.1f}  max={max(baseline_gbps):.1f}")
    print(f"original GB/s: median={statistics.median(orig_gbps):.1f}  min={min(orig_gbps):.1f}  max={max(orig_gbps):.1f}")
    print(f"b1       GB/s: median={statistics.median(b1_gbps):.1f}  min={min(b1_gbps):.1f}  max={max(b1_gbps):.1f}")

    med_orig_ratio = statistics.median(orig_gbps) / statistics.median(baseline_gbps)
    med_b1_ratio = statistics.median(b1_gbps) / statistics.median(baseline_gbps)
    med_gain = statistics.median(b1_gbps) / statistics.median(orig_gbps) - 1

    print(f"\noriginal ratio to baseline (median/median): {med_orig_ratio*100:.1f}%")
    print(f"b1 ratio to baseline (median/median):       {med_b1_ratio*100:.1f}%")
    print(f"\nB1 vs ORIGINAL, same-process direct comparison: {med_gain*100:+.1f}% GB/s change")

    per_trial_gain = [(b1_gbps[i] / orig_gbps[i] - 1) * 100 for i in range(N_TRIALS)]
    print(f"Per-trial B1-vs-orig gain: {[f'{g:+.1f}%' for g in per_trial_gain]}")
    print(f"mean per-trial gain: {statistics.mean(per_trial_gain):+.2f}%  "
          f"stdev: {statistics.stdev(per_trial_gain):.2f}%  "
          f"median: {statistics.median(per_trial_gain):+.1f}%")
    n_positive = sum(1 for g in per_trial_gain if g > 0)
    print(f"trials favoring B1: {n_positive}/{N_TRIALS}")


if __name__ == "__main__":
    main()
