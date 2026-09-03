# Reproducing the numbers

All benchmarks run on an AMD Radeon GPU on ROCm (validated on Radeon AI PRO R9700, gfx1201). Each kernel **correctness-gates against a CPU reference before it reports any throughput** — a fast-but-wrong kernel exits non-zero. Set `HIP_VISIBLE_DEVICES` to a non-display GPU; do not set `ROCR_VISIBLE_DEVICES` (it silently forces CPU fallback).

## 1. Decode — the production kernel: 96–97% of the measured memory roofline

**This is the headline decode result.** `k_mmvq_dot8_iu4` is the kernel that actually
ships in the roc9 llama.cpp fork (T170): one block per row, threads striding along K
so adjacent lanes read adjacent blocks (coalesced), then a shared-memory reduction,
launched `<<<N, 64>>>`. It correctness-gates against a CPU reference before reporting
any throughput.

```bash
cd kernels/decode
hipcc --offload-arch=gfx1201 -O3 decode_mmvq_iu4.hip -o decode_mmvq_iu4
HIP_VISIBLE_DEVICES=0 ./decode_mmvq_iu4
```
```
N=65536  K=4096   |  144.0 MiB (DRAM-honest) | 0.2498 ms | 604 GB/s | 96% of roofline | PASS
N=16384  K=14336  |  126.0 MiB (DRAM-honest) | 0.2156 ms | 613 GB/s | 97% of roofline | PASS
```
Roofline reference is **631 GB/s**, the measured streaming DRAM bandwidth of this board
(our `bw_roofline.cu`, independently cross-checked against ROCm Validation Suite `babel`
at 598–635 GB/s). At 96–97% there is essentially no headroom left in this kernel — it is
memory-bound and saturating.

### Why the working-set size is printed, and why you should care

The R9700 has a **64 MiB Infinity Cache**. Any int4 decode benchmark whose weights fit
inside it measures *cache*, not DRAM, and will happily report a bandwidth **above** the
DRAM roofline. The harness prints MiB and flags the case:

```bash
HIP_VISIBLE_DEVICES=0 ./decode_mmvq_iu4 14336 4096
# N=14336 K=4096 | 31.5 MiB (CACHE-RESIDENT!) | 792 GB/s | 126% of roofline
```
126% of roofline is not a win — it is the measurement telling you it read cache. We
report the DRAM-honest shapes as the result and keep this switch in so the failure mode
is self-evident rather than flattering.

## 1b. Instruction A/B — native int4 dot8 vs the dp4a route (2.2× at a fixed shape)

A separate, narrower question: with the memory path held constant, how much does the
native 8-wide `v_dot8_i32_iu4` beat unpacking to int8 and using `v_dot4_i32_iu8`?
`decode_dot8.hip` and `decode_dp4a.hip` isolate exactly that — identical
one-thread-per-row harness, only the inner instruction differs, both gated against the
same CPU int reference.

```bash
hipcc --offload-arch=gfx1201 -O3 decode_dp4a.hip -o decode_dp4a
hipcc --offload-arch=gfx1201 -O3 decode_dot8.hip -o decode_dot8
HIP_VISIBLE_DEVICES=0 ./decode_dp4a     # PASS, 0.0844 ms
HIP_VISIBLE_DEVICES=0 ./decode_dot8     # PASS, 0.0380 ms  => 2.2x
```

**Scope this claim honestly — it is an instruction comparison, not a kernel result.**
One thread per row means adjacent lanes land `K/2` bytes apart, which is uncoalesced.
That is invisible at the default 28 MiB (cache absorbs it) and catastrophic once the
weights must come from DRAM — at N=65536 both routes collapse to ~17 GB/s and the dot8
advantage disappears entirely, because both are then bound by the access pattern rather
than by the instruction. The ratio is a valid answer to "which instruction is faster";
it is **not** a claim about achievable decode throughput. For that, see §1 — the
production kernel, which fixes the access pattern and reaches 96–97% of roofline.

Or drive the A/B through AMD's Magpie evaluator: `../toolkit/magpie.sh compare -k compare_decode.yaml`
(correctness ranking) + `metrix profile` for the gfx1201 duration (see `toolkit/magpie.sh`
header for the RDNA4 metrix recipe).

## 2. Prefill — int4 2:4-sparse K64 SWMMAC full GEMM (3.67×)

The SWMMAC per-lane layout helpers live in the roc9 llama.cpp fork (`swmmac24_iu4_k64.cuh`). To keep this repo self-contained, the standalone bench and the required layout header are bundled here as `gemm_bench.hip` + `swmmac24_iu4_k64.cuh` (see PACKAGING note below).

```bash
cd kernels/prefill
hipcc --offload-arch=gfx1201 -O3 -DRDNA4 gemm_bench.hip -o gemm_bench
HIP_VISIBLE_DEVICES=0 ./gemm_bench       # correctness err=0 for all shapes, then the K sweep
```
Expected (M=N=4096, ILP=4, WARPS=32, median-of-6). Correctness gates run first and must
report `max_abs_err=0` for all three kernels at all shapes before any perf number is printed:

```
K            iu8-K16 dense        iu4-K32 dense        iu4-K64 2:4-SWMMAC   K64/K16
K=2048    2.699ms/25.5 TOP/s   1.459ms/47.1 TOP/s   1.182ms/58.1 TOP/s   2.283x
K=4096    5.160ms/26.6 TOP/s   2.739ms/50.2 TOP/s   1.658ms/82.9 TOP/s   3.112x
K=8192   11.016ms/25.0 TOP/s   5.186ms/53.0 TOP/s   3.002ms/91.6 TOP/s   3.669x
```

**3.67× at K=8192**, which is 88–95% of the register-resident raw-instruction ceiling of
3.90×. Capture grows with K as fixed overhead amortizes. TOPS convention is
`2*M*N*K_logical/time` with `K_logical` the full uncompressed K for all three kernels, so
the ratios are directly comparable to the ISA ceiling (3.90× vs K16, 1.95× vs K32 dense).

> Note: `-DRDNA4` is required — the SWMMAC/WMMA intrinsics are gated behind `#if defined(RDNA4)`; without it every matrix op silently falls to a zero-returning stub (a bug the correctness gate caught during development).

## 3. Comms — INT6 compressed all-reduce (numpy reference)

The exact-reduce property and the accuracy curve are validated in numpy (CPU, no GPU needed); the HIP two-shot kernel is provided for the GPU stage.

```bash
cd kernels/allreduce
python test_accuracy.py        # exact-reduce drift ~5e-7 (shared scale); INT6 vs INT4 vs INT8 curve
python test_weight_quant.py    # INT6 vs MXFP6 as a weight-quant format, on real tensors
```
See `DESIGN.md` for the two-shot NUMA-aware structure and the GPU-window benchmark plan.

---

## Packaging notes

The SWMMAC layout headers (`swmmac24_iu4_k64.cuh`, `swmmac24.cuh`) are bundled in
`kernels/prefill/`, so the GEMM benchmark builds with no external tree. Validated on
ROCm 7.x with `hipcc` targeting `gfx1201`.
