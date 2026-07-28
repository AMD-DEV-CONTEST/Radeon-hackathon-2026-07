[← Back to ROCm reference](README.md) · [← Back to README](../../README.md)

# RX 7600 (gfx1102) official specifications

The exact official hardware numbers for the GPU this entire project is developed and measured on, from ROCm's own [AMD GPU specifications](https://rocm.docs.amd.com/en/latest/reference/gpu-specs.html) page (the "AMD Radeon GPUs" table). Reproduced here as a single row (not the full multi-GPU table; see the official page for the RX 7900 XTX/XT/GRE, RX 7800 XT, RX 7700(XT), RX 9000-series, and others) since this is the one row this project's kernels are actually tuned against.

| Field | Value |
|---|---|
| Architecture | RDNA3 |
| LLVM target name | `gfx1102` |
| VRAM | 8 GiB |
| Compute Units | 32 |
| Wavefront Size | 32 or 64 (VTE compiles/runs wave32, see [RDNA3 architecture: Wave32 and Wave64](RDNA3-ARCHITECTURE.md#wave32-and-wave64)) |
| LDS | 128 KiB (per WGP) |
| Infinity Cache | 32 MiB |
| L2 Cache | 2 MiB |
| Graphics L1 Cache | 256 KiB |
| L0 Vector Cache | 32 KiB |
| L0 Scalar Cache | 16 KiB |
| L0 Instruction Cache | 32 KiB |
| VGPR File | 512 KiB (per SIMD) |
| SGPR File | 32 KiB (per SIMD) |
| GFXIP version | 11.0 |

## How this maps to VTE's own numbers

- **32 Compute Units** is the number `HIPRuntime.get_num_cus()` resolves to at runtime on this hardware (see [Performance: portability](../PERFORMANCE.md#portability-dynamic-compute-unit-detection-rdna2rdna3-not-just-the-rx-7600)) and the number every CU-count-dependent grid-sizing formula in this codebase (Split-KV attention's `_chunk_size_for_cus`, `gemv_q4k`'s effective occupancy) is ultimately scaled against.
- **32 MiB Infinity Cache** is the same figure [Performance's batched-decode section](../PERFORMANCE.md#batched-decode) already cites as the likely cause of the batch=8 throughput regression (FFN weights ~27.5MB/layer competing for cache space at higher batch sizes), which is now backed by the official spec rather than general recollection.
- **512 KiB VGPR file per SIMD** is the ceiling behind every "Occupancy [waves/SIMD]" number this project measured via `hipcc -Rpass-analysis=kernel-resource-usage` during the [2026-07 kernel investigation](../PERFORMANCE.md#investigation-pushing-past-100-toks-2026-07): `gemv_q4k`'s 37 VGPRs/work-item and the attention family's 11-22 VGPRs/work-item both leave enough of this 512KiB budget free per wave that the compiler could schedule the maximum reported occupancy (16 waves/SIMD) without spilling.
- **`gfx1102`** is the exact LLVM target name this project's kernel compilation (`hipcc --offload-arch=gfx1102`, `vte/compiler/codegen.py`) and AOT kernel cache (`vte/core/assets/kernels/gfx1102/`) are built for, and the value `HIPRuntime.get_gpu_architecture()` resolves at runtime by reading the actual device.

Source: <https://rocm.docs.amd.com/en/latest/reference/gpu-specs.html> (ROCm documentation, "AMD Radeon GPUs" tab). Check that page directly for other RDNA2/RDNA3/RDNA4 SKUs, including the ones in this project's `GPU_ARCH_MAP` (`vte/config.py`) that have never run on real hardware (see [Known limitations: hardware portability](../LIMITATIONS.md#hardware-portability)).
