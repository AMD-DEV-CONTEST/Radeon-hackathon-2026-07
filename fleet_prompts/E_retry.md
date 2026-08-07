Your previous response had pseudo-code stubs in the vec4 matvec and fused RMSNorm+MatVec shaders. I need complete, compilable WGSL. No pseudo-code, no "// omitted", no "// ...".

## What compiled correctly (keep as-is):
- shaders/matvec_shared.wgsl — the shared memory version was fine
- src/pipeline_cache.rs — fine

## What needs to be rewritten completely:

### 1. shaders/matvec_vec4.wgsl — vec4 input + thread coarsening

COMPLETE implementation. Each thread computes 4 output rows (COARSEN=4).
Input is `array<vec4<f32>>` (K/4 elements). Weights are `array<f32>` (N×K row-major).

```wgsl
struct Params { N: u32, K: u32, K_vec4: u32, _pad: u32 }
@group(0) @binding(0) var<storage, read> input: array<vec4<f32>>;   // [K/4]
@group(0) @binding(1) var<storage, read> weights: array<f32>;        // [N × K]
@group(0) @binding(2) var<storage, read_write> output: array<f32>;   // [N]
@group(0) @binding(3) var<uniform> params: Params;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    // Thread gid.x handles rows [gid.x*4 .. gid.x*4+3]
    // For each of 4 rows: dot product with input using vec4 loads
    // Write 4 outputs (with bounds check)
}
```

Key: for row `r`, the dot product is:
```
sum_r = 0
for i in 0..K_vec4:
    v = input[i]  // vec4 of input[i*4..i*4+3]
    w_base = r * K + i*4
    sum_r += v.x * weights[w_base] + v.y * weights[w_base+1] + v.z * weights[w_base+2] + v.w * weights[w_base+3]
output[r] = sum_r
```
Handle K % 4 != 0 with a scalar tail loop.

### 2. shaders/rmsnorm_matvec.wgsl — fused RMSNorm + single MatVec row

This is a 2-phase kernel:
- Phase 1: parallel reduction to compute rms_scale = 1/sqrt(mean(input^2) + eps)
  Uses workgroup shared memory, same pattern as rmsnorm.wgsl
- Phase 2: each thread computes ONE output element:
  output[n] = sum_k( input_vec4[k/4].component * norm_weight_vec4[k/4].component * rms_scale * weights[n*K+k] )

```wgsl
struct FusedParams { N: u32, K: u32, K_vec4: u32, epsilon: f32 }
@group(0) @binding(0) var<storage, read> input: array<vec4<f32>>;       // [K/4]
@group(0) @binding(1) var<storage, read> norm_weight: array<vec4<f32>>; // [K/4]
@group(0) @binding(2) var<storage, read> matrix: array<f32>;             // [N × K]
@group(0) @binding(3) var<storage, read_write> output: array<f32>;       // [N]
@group(0) @binding(4) var<uniform> params: FusedParams;

var<workgroup> shared_ss: array<f32, 256>;  // for reduction

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(local_invocation_id) lid: vec3<u32>, @builtin(global_invocation_id) gid: vec3<u32>) {
    // Phase 1: each thread accumulates partial sum-of-squares
    // Phase 2: reduction tree (same as rmsnorm.wgsl)
    // Phase 3: each thread computes one output element using rms_scale
}
```

OUTPUT: Only output the two files that need fixing. Complete WGSL, no stubs.

// === FILE: shaders/matvec_vec4.wgsl ===
[complete shader]

// === FILE: shaders/rmsnorm_matvec.wgsl ===
[complete shader]
