You are an expert in WGSL compute shaders and GPU memory optimization for Pascal/Maxwell GPUs (Tesla P100, GTX 1070, GTX 1060). I need two optimized shader rewrites.

## Hardware context
- Tesla P100: 60 SMs, 48KB shared/SM, HBM2 732 GB/s, 9.3 TFLOPS FP32, native FP16 at 2x
- GTX 1070: 15 SMs, GP104, FP32 only practical
- All are memory-bandwidth-bound for transformer inference (matvec is the hot path)

## Current matvec.wgsl (the bottleneck)
```wgsl
struct Params { N: u32, K: u32, _pad0: u32, _pad1: u32 }
@group(0) @binding(0) var<storage, read> input: array<f32>;
@group(0) @binding(1) var<storage, read> weights: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<f32>;
@group(0) @binding(3) var<uniform> params: Params;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let n = gid.x;
    if (n >= params.N) { return; }
    var sum: f32 = 0.0;
    let w_base = n * params.K;
    // 8x unrolled scalar loop
    let k8 = params.K & ~7u;
    var k: u32 = 0u;
    while (k < k8) {
        sum += weights[w_base + k] * input[k]; // ... x8
        k = k + 8u;
    }
    output[n] = sum;
}
```

Problems:
1. Scalar f32 loads — wastes 3/4 of memory bus width (128-bit bus reads 4 f32s but we use 1)
2. One output per thread — 256 threads × 1 output = 256 outputs per workgroup. For N=1536, that's 6 workgroups. P100 has 60 SMs — we're only using 6/60 = 10% of the GPU.

## Deliverable 1: vec4 + thread-coarsened matvec

Rewrite matvec.wgsl to:
1. **vec4 loads**: Read weights and input as `vec4<f32>` (4 floats per load = full 128-bit bus utilization)
2. **Thread coarsening**: Each thread computes COARSEN=4 output rows instead of 1. This means:
   - Workgroup size stays 256
   - Each workgroup computes 256 × 4 = 1024 output elements
   - For N=1536: ceil(1536/1024) = 2 workgroups → much better SM utilization
   - Reuses the input vector across 4 rows (loaded once into registers, used 4 times)

```wgsl
// Target structure:
const COARSEN: u32 = 4u;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let base_n = gid.x * COARSEN;
    // Load input into local array (reused across COARSEN rows)
    // For each of COARSEN rows: dot product using vec4 loads
    // Write COARSEN outputs
}
```

Key constraints:
- K must be divisible by 4 for vec4 loads (add scalar tail for remainder)
- N may not be divisible by COARSEN (bounds check each output)
- Keep the same binding layout (bindings 0-3, same Params struct)
- Must produce identical numerical output to the scalar version

Also provide a **shared-memory tiled variant** where the input vector is loaded into workgroup shared memory once (256 threads cooperatively load K elements), then all threads read from fast shared memory instead of global memory. This is especially good when K is large (K=1536 for Qwen 1.5B, K=8960 for FFN).

```wgsl
var<workgroup> shared_input: array<f32, 2048>; // or vec4 version
// Phase 1: cooperative load of input into shared memory
// Phase 2: each thread computes its COARSEN outputs from shared_input
```

## Deliverable 2: Fused RMSNorm + MatVec

Currently we do:
1. RMSNorm: hidden_state → normed (writes 1536 f32s to global memory)
2. MatVec: normed → q_proj (reads 1536 f32s from global memory)

This is 2 global memory round-trips for the same data. Fuse them:

```wgsl
// shaders/rmsnorm_matvec.wgsl
// Computes: output[n] = sum_k( (input[k] * rms_scale * weight[k]) * W[n][k] )
// where rms_scale = 1/sqrt(mean(input^2) + eps)
//
// Phase 1: parallel reduction to compute rms_scale (same as rmsnorm.wgsl)
// Phase 2: each thread computes one output element using the fused formula
//          WITHOUT writing the normed intermediate to global memory
```

Binding layout:
```wgsl
struct FusedParams {
    N: u32,           // output dim
    K: u32,           // hidden dim  
    K_vec4: u32,      // K/4
    epsilon: f32,
}
@group(0) @binding(0) var<storage, read> input: array<vec4<f32>>;    // [K/4]
@group(0) @binding(1) var<storage, read> norm_weight: array<vec4<f32>>; // [K/4]
@group(0) @binding(2) var<storage, read> matrix: array<f32>;          // [N × K]
@group(0) @binding(3) var<storage, read_write> output: array<f32>;    // [N]
@group(0) @binding(4) var<uniform> params: FusedParams;
```

Use workgroup shared memory for the reduction (same pattern as rmsnorm.wgsl).
Workgroup size: 256. Each thread handles one output element.

## Deliverable 3: Pipeline cache helper (Rust)

Write a Rust module `src/pipeline_cache.rs`:
```rust
/// Save compiled Vulkan pipeline cache to disk.
/// wgpu exposes this via wgpu::Device::create_pipeline_cache (nightly) or
/// via the raw Vulkan handle. Use the available wgpu API.
///
/// Cache path: ~/.cache/cesarops/pipeline_cache_{device_name_hash}.bin
/// On hit: load and pass to pipeline creation → eliminates shader compilation on startup
/// On miss: compile normally, save cache after first run

pub struct PipelineCache {
    path: PathBuf,
    data: Option<Vec<u8>>,
}

impl PipelineCache {
    pub fn load_or_create(device_name: &str) -> Self;
    pub fn save(&self, device: &wgpu::Device);
    // Returns the cache data to pass to pipeline creation if available
    pub fn data(&self) -> Option<&[u8]>;
}
```

Check if wgpu's current stable API exposes pipeline cache. If not, show how to use
`wgpu::Device::create_pipeline_cache` with the `PipelineCacheDescriptor` if available,
or fall back to a no-op stub with a comment explaining when it becomes available.

## OUTPUT FORMAT
```wgsl
// === FILE: shaders/matvec_vec4.wgsl ===
// Full vec4 + thread-coarsened version

// === FILE: shaders/matvec_shared.wgsl ===  
// Shared memory tiled version (for large K)

// === FILE: shaders/rmsnorm_matvec.wgsl ===
// Fused RMSNorm + MatVec

// === FILE: src/pipeline_cache.rs ===
// Pipeline cache module
```

Include performance estimates:
- Scalar matvec: N=1536, K=1536 → X GB/s effective bandwidth
- vec4 matvec: same → Y GB/s (should be ~4x)
- Shared memory: same → Z GB/s (should be ~8x for large K)
- Fused RMSNorm+MatVec: saves 1 global memory round-trip per layer × 28 layers = W MB/token
