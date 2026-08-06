# AITER → RDNA3 (gfx1100) Port

Four source changes close vLLM's AITER-on-RDNA3 integration gap: vLLM's
`is_aiter_found_and_supported()` covered CDNA3+ and (later) RDNA4, but never
gfx1100 (RDNA3) — even though AITER upstream lists W7900 as Experimental.
These patches enable a working RDNA3 (W7900 / gfx1100) AITER path in vLLM.
Measured on Aug 3, 2026.

## Changes

| # | File | Change |
|---|------|--------|
| 1 | `vllm/_aiter_ops.py` | `is_aiter_found_and_supported()`: `return on_mi3xx() or on_gfx1100()` |
| 2 | `aiter_meta/csrc/cpp_itfs/utils.py` | arch allow-list: add `gfx1100..gfx1250` |
| 3 | `aiter/ops/triton/configs/gemm/gfx1100-GEMM-A8W8.json` | new M-band tuning config (this dir) |
| 4 | `vllm/_aiter_ops.py` | `_rocm_aiter_w8a8_gemm_impl()`: use Triton `gemm_a8w8` on gfx1100 (CK XDL kernels compile-fail on RDNA3) |

## Tuned config (gfx1100-GEMM-A8W8.json)

- decode M≤32: `BLOCK_SIZE_M=16, N=128, K=128, warps=4, stages=3` → 0.071 ms/GEMM
- prefill M≥64: `BLOCK_SIZE_M=64, N=256, warps=8` → 4.4 ms @ M=2048

## Result

| Path | Linear kernel | Throughput |
|------|--------------|:---:|
| AITER gated off (default) | TritonInt8ScaledMMLinearKernel | 12.3 tok/s |
| **AITER gfx1100 (this port)** | AiterInt8ScaledMMLinearKernel + GDN + conv1d + sampler | 11.7 tok/s (parity) |

Functional parity, not speedup — the decode bottleneck is 140+ serialized
per-layer kernels on RDNA3 WMMA, not a single GEMM (see spec-document 9b/9c).
