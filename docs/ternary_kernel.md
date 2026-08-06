# Ternary GEMM Kernel Design

## Goal

Accelerate inference for models whose weights are restricted to the ternary set
`{-1, 0, +1}` on AMD GPUs using HIP/ROCm.

## Representation

Each weight is encoded with two bits:

| Bits | Value |
|------|-------|
| 00   | 0     |
| 01   | +1    |
| 10   | -1    |
| 11   | reserved |

Four weights are packed into one `uint8_t`, LSB-first. For a weight matrix of
shape `(N, K)`, the packed shape is `(N, ceil(K/4))` bytes, yielding a **8x**
memory reduction over float32 and **4x** over int8.

## Kernel (`kernels/ternary_gemm.hip`)

- Tile-based GEMM with shared memory for activations and packed weights.
- Each thread unpacks its own 2-bit weight in registers, avoiding expansion to
  higher precision formats.
- Coalesced loads for the activation matrix and packed weights.
- Grid-stride loops to handle large matrices efficiently.
- A per-output-channel scale is applied after accumulation.

## Python wrapper (`backend/kernels/ternary_extension.py`)

- Auto-compiles the HIP kernel with `hipcc` when available.
- Exposes the kernel as a `torch.autograd.Function` so it integrates with
  PyTorch autograd during forward passes.
- Falls back to a dense PyTorch matmul when the kernel is unavailable or the
  input is on CPU, ensuring the app runs anywhere.

## Benchmarks

Benchmarks measure:
- Tokens per second
- Latency (ms)
- VRAM usage (MB)
- GPU utilization (%)
- Speedup vs dense FP32 baseline

When running on AMD hardware with `hipcc` and a ROCm PyTorch wheel, the custom
kernel should show significant speedup and lower memory usage. On CPU or NVIDIA
hardware it falls back to the reference implementation.

## Future improvements

- Use `__half2` / `__bf1616` activations for mixed-precision ternary GEMM.
- Add warp-level matrix-tile instructions (e.g., `__builtin_amdgcn_mfma`) for
  MI200/MI300 class GPUs.
- Implement online ternary dequantization with per-channel scales fused into
  the kernel.
