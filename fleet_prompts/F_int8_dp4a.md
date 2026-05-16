You are an expert in GPU integer arithmetic, Vulkan compute, and WGSL shaders. I need INT8 DP4A acceleration for a Rust+wgpu inference engine on Pascal GPUs (Tesla P100, GTX 1070).

## Hardware context
- Pascal (sm_60/sm_61): supports DP4A — 4-way packed INT8 dot product in one clock
- DP4A throughput: 4x INT8 ops per clock vs 1x FP32 → theoretical 4x speedup for INT8 matmul
- P100 has 9.3 TFLOPS FP32 → ~37 TOPS INT8 theoretical
- GTX 1070 has 6.5 TFLOPS FP32 → ~26 TOPS INT8 theoretical
- Maxwell (GTX 960, M2200): does NOT support DP4A — skip INT8 for those

## What we have
- Q8_0 dequant: 32-element blocks, 2-byte f16 scale + 32 signed i8 values
- Currently: dequant to f32 on CPU at load time, then f32 matmul on GPU
- Target: keep weights as INT8 on GPU, do INT8 matmul, scale at the end

## WGSL INT8 DP4A availability
WGSL does not expose DP4A directly. However, wgpu on Vulkan can use:
1. `VK_KHR_shader_integer_dot_product` (Vulkan 1.3 / extension) — exposes `dot4x8Packed` in SPIR-V
2. WGSL `dot4I8Packed(a: u32, b: u32) -> i32` — available in WGSL when the extension is enabled

Check: does wgpu expose `dot4I8Packed` in WGSL? If yes, show how to use it.
If not, show the fallback: manual 4-way INT8 multiply-accumulate using bit manipulation.

## Deliverable 1: Q8_0 GPU-side matmul shader

```wgsl
// shaders/matvec_q8.wgsl
// Matrix-vector multiply where weights are stored as Q8_0 (INT8 + f16 scale per 32 elements)
// Uses DP4A (dot4I8Packed) if available, else manual INT8 MAC

struct Params {
    N: u32,          // output rows
    K: u32,          // input cols (must be multiple of 32 for Q8_0 blocks)
    _pad0: u32,
    _pad1: u32,
}

// Weights stored as raw Q8_0 bytes: for each block of 32 elements:
//   bytes [0..1]: f16 scale
//   bytes [2..33]: 32 signed i8 quants
// Total: 34 bytes per 32 elements
@group(0) @binding(0) var<storage, read> input_f32: array<f32>;    // [K] f32 input vector
@group(0) @binding(1) var<storage, read> weights_q8: array<u32>;   // Q8_0 raw bytes as u32
@group(0) @binding(2) var<storage, read_write> output: array<f32>; // [N]
@group(0) @binding(3) var<uniform> params: Params;
```

For each output element n:
1. Loop over K in blocks of 32
2. Read f16 scale from block header
3. Read 32 INT8 weights (packed as 8 u32s, 4 bytes each)
4. Read 32 f32 input values
5. Compute dot product: either via dot4I8Packed or manual
6. Multiply by scale, accumulate

Show both paths:
```wgsl
// Path A: dot4I8Packed (if available)
// Requires: enable chromium_experimental_dp4a; or similar
let packed_w = weights_q8[block_base + j];
let packed_i = pack4x8snorm_from_f32(input[k..k+4]); // pack input as i8
let dp = dot4I8Packed(packed_w, packed_i);

// Path B: manual (always works)
let b0 = i32((packed_w >>  0u) & 0xFFu); // sign-extend
let b1 = i32((packed_w >>  8u) & 0xFFu);
// ... etc
```

## Deliverable 2: Runtime DP4A detection

```rust
// src/dp4a_support.rs
/// Check if the wgpu device supports DP4A (dot4I8Packed in WGSL).
/// Returns true on Pascal+ with Vulkan 1.3 or VK_KHR_shader_integer_dot_product.
pub fn supports_dp4a(device: &wgpu::Device, adapter: &wgpu::Adapter) -> bool {
    // Check wgpu::Features or adapter limits
    // wgpu exposes this via Features::SHADER_INT8 or similar
    // Show the exact feature flag to check
}
```

## Deliverable 3: Q8_0 weight upload path

Currently Q8_0 is dequanted to f32 at load time. Show how to keep it as raw bytes:

```rust
// In tensor_loader_safe.rs, for Q8_0 tensors:
// Instead of: dequantize_to_f32(raw_bytes, n_elements, TensorType::Q8_0)
// Do: upload raw_bytes directly as STORAGE buffer
// Then use matvec_q8.wgsl instead of matvec.wgsl for dispatch
```

Show the dispatch path change in forward_pass.rs — how to detect Q8_0 weights and route to the INT8 shader.

## Deliverable 4: Expected speedup math

For Qwen 1.5B Q8_0 (hypothetical):
- Weight matrix Q_proj: 1536 × 1536 × 1 byte = 2.25 MB (vs 6 MB for f32)
- Memory bandwidth: 2.25 MB × 28 layers × 9 ops/layer = 567 MB/token
- At P100 HBM2 732 GB/s: 567 MB / 732 GB/s = 0.77 ms/token (theoretical)
- Current f32: 6 MB × 28 × 9 / 732 GB/s = 2.06 ms/token
- Speedup: 2.7x from bandwidth alone, plus DP4A compute speedup

Show the math for our actual model (Q6_K dequanted to f32 = 6 bytes/element stored as f32).

## OUTPUT FORMAT
```wgsl
// === FILE: shaders/matvec_q8.wgsl ===
// Full implementation with both DP4A and fallback paths

// === FILE: src/dp4a_support.rs ===
// Feature detection

// === DIFF: src/tensor_loader_safe.rs ===
// Q8_0 raw upload path

// === DIFF: src/forward_pass.rs ===
// Route Q8_0 weights to INT8 shader

// === PERFORMANCE ANALYSIS ===
// Bandwidth math, expected t/s improvement
```

Be concrete. If WGSL dot4I8Packed is not available in stable wgpu, say so clearly and show the manual fallback that still benefits from INT8 storage bandwidth reduction.
