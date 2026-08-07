// WGSL RMSNorm Kernel for Tesla P100
// Proper parallel reduction tree (log2 steps, not sequential barriers).
//
// RMSNorm(x) = x * weight / sqrt(mean(x^2) + epsilon)
//
// One workgroup processes one row (one token's hidden state).
// Workgroup size 256 — gives 8 warps per workgroup, good occupancy on P100's 60 SMs.
// Uses vec4 loads for 4x memory coalescing on HBM2.

struct Params {
    hidden_dim: u32,       // Full hidden dimension (e.g. 5120)
    hidden_dim_vec4: u32,  // hidden_dim / 4
    epsilon: f32,
    _pad: u32,
}

@group(0) @binding(0) var<storage, read> input: array<vec4<f32>>;
@group(0) @binding(1) var<storage, read> weight: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> output: array<vec4<f32>>;
@group(0) @binding(3) var<uniform> params: Params;

// Shared memory for parallel reduction (256 f32 slots)
var<workgroup> shared_sum: array<f32, 256>;

@compute @workgroup_size(256, 1, 1)
fn main(
    @builtin(local_invocation_id) lid: vec3<u32>,
    @builtin(workgroup_id) wid: vec3<u32>,
) {
    let tid = lid.x;
    let row = wid.x;
    let row_offset = row * params.hidden_dim_vec4;

    // Phase 1: Each thread accumulates sum-of-squares over its stride
    var local_ss: f32 = 0.0;
    for (var i: u32 = tid; i < params.hidden_dim_vec4; i = i + 256u) {
        let v = input[row_offset + i];
        local_ss = local_ss + dot(v, v);
    }

    // Store to shared memory
    shared_sum[tid] = local_ss;
    workgroupBarrier();

    // Phase 2: Parallel reduction tree (log2(256) = 8 steps)
    if (tid < 128u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 128u]; }
    workgroupBarrier();
    if (tid < 64u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 64u]; }
    workgroupBarrier();
    if (tid < 32u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 32u]; }
    workgroupBarrier();
    if (tid < 16u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 16u]; }
    workgroupBarrier();
    if (tid < 8u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 8u]; }
    workgroupBarrier();
    if (tid < 4u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 4u]; }
    workgroupBarrier();
    if (tid < 2u) { shared_sum[tid] = shared_sum[tid] + shared_sum[tid + 2u]; }
    workgroupBarrier();
    if (tid == 0u) { shared_sum[0] = shared_sum[0] + shared_sum[1]; }
    workgroupBarrier();

    // Phase 3: Compute RMS scale factor (broadcast from shared_sum[0])
    let mean_sq = shared_sum[0] / f32(params.hidden_dim);
    let rms_scale = 1.0 / sqrt(mean_sq + params.epsilon);

    // Phase 4: Apply normalization and weight scaling
    for (var i: u32 = tid; i < params.hidden_dim_vec4; i = i + 256u) {
        let idx = row_offset + i;
        let x = input[idx];
        let w = weight[i];
        output[idx] = (x * rms_scale) * w;
    }
}
