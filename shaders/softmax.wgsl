// WGSL Stable Softmax with aggressive tail masking and better numerical stability for older GPUs
// Optimized for short-to-medium sequences (kv_len up to a few thousand)

struct Params {
    seq_len: u32,      // actual number of valid positions
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

@group(0) @binding(0) var<storage, read> scores: array<f32>;
@group(0) @binding(1) var<storage, read_write> probs: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;

var<workgroup> shared_max: array<f32, 256>;
var<workgroup> shared_sum: array<f32, 256>;

@compute @workgroup_size(256, 1, 1)
fn main(
    @builtin(local_invocation_id) lid: vec3<u32>,
    @builtin(workgroup_id) wid: vec3<u32>,
) {
    let tid = lid.x;
    let head_offset = wid.x * params.seq_len;
    let seq_len = params.seq_len;

    // Phase 1: Find max with strict masking
    var local_max: f32 = -3.40282347e38;  // -inf approx
    for (var i: u32 = tid; i < seq_len; i = i + 256u) {
        let val = scores[head_offset + i];
        if (val > local_max) {
            local_max = val;
        }
    }
    shared_max[tid] = local_max;
    workgroupBarrier();

    // Parallel reduction for max
    if (tid < 128u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 128u]); }
    workgroupBarrier();
    if (tid < 64u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 64u]); }
    workgroupBarrier();
    if (tid < 32u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 32u]); }
    workgroupBarrier();
    if (tid < 16u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 16u]); }
    workgroupBarrier();
    if (tid < 8u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 8u]); }
    workgroupBarrier();
    if (tid < 4u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 4u]); }
    workgroupBarrier();
    if (tid < 2u) { shared_max[tid] = max(shared_max[tid], shared_max[tid + 2u]); }
    workgroupBarrier();
    if (tid == 0u) { shared_max[0] = max(shared_max[0], shared_max[1]); }
    workgroupBarrier();

    let row_max = shared_max[0];

    // Phase 2: exp(score - max) + sum with hard cutoff for stability
    var local_sum: f32 = 0.0;
    for (var i: u32 = tid; i < seq_len; i = i + 256u) {
        let shifted = scores[head_offset + i] - row_max;
        // Very important for old GPUs: prevent underflow/denormals exploding
        let exp_val = select(0.0, exp(shifted), shifted > -70.0);
        probs[head_offset + i] = exp_val;
        local_sum += exp_val;
    }
    shared_sum[tid] = local_sum;
    workgroupBarrier();

    // Parallel reduction for sum
    if (tid < 128u) { shared_sum[tid] += shared_sum[tid + 128u]; }
    workgroupBarrier();
    if (tid < 64u) { shared_sum[tid] += shared_sum[tid + 64u]; }
    workgroupBarrier();
    if (tid < 32u) { shared_sum[tid] += shared_sum[tid + 32u]; }
    workgroupBarrier();
    if (tid < 16u) { shared_sum[tid] += shared_sum[tid + 16u]; }
    workgroupBarrier();
    if (tid < 8u) { shared_sum[tid] += shared_sum[tid + 8u]; }
    workgroupBarrier();
    if (tid < 4u) { shared_sum[tid] += shared_sum[tid + 4u]; }
    workgroupBarrier();
    if (tid < 2u) { shared_sum[tid] += shared_sum[tid + 2u]; }
    workgroupBarrier();
    if (tid == 0u) { shared_sum[0] += shared_sum[1]; }
    workgroupBarrier();

    let row_sum = shared_sum[0];
    let inv_sum = select(0.0, 1.0 / row_sum, row_sum > 1e-12);

    // Phase 3: Normalize
    for (var i: u32 = tid; i < seq_len; i = i + 256u) {
        probs[head_offset + i] *= inv_sum;
    }
}
