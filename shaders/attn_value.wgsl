// WGSL Attention-Value weighted sum with proper KV cache stride.
//
// context[d] = sum_{t=0}^{kv_len-1} probs[t] * V[t][d]
// V cache layout: [pos][n_kv_heads][head_dim]
// V at position t for this head: v_cache[t * kv_stride + kv_head_offset + d]

struct Params {
    kv_len: u32,
    head_dim: u32,
    kv_stride: u32,        // n_kv_heads * head_dim
    kv_head_offset: u32,   // kv_head * head_dim
}

@group(0) @binding(0) var<storage, read> probs: array<f32>;
@group(0) @binding(1) var<storage, read> v_cache: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<f32>;
@group(0) @binding(3) var<uniform> params: Params;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let d = gid.x;
    if (d >= params.head_dim) { return; }

    var sum: f32 = 0.0;

    let kv4 = params.kv_len & ~3u;
    var t: u32 = 0u;
    while (t < kv4) {
        sum += probs[t]      * v_cache[t * params.kv_stride + params.kv_head_offset + d];
        sum += probs[t + 1u] * v_cache[(t + 1u) * params.kv_stride + params.kv_head_offset + d];
        sum += probs[t + 2u] * v_cache[(t + 2u) * params.kv_stride + params.kv_head_offset + d];
        sum += probs[t + 3u] * v_cache[(t + 3u) * params.kv_stride + params.kv_head_offset + d];
        t = t + 4u;
    }
    while (t < params.kv_len) {
        sum += probs[t] * v_cache[t * params.kv_stride + params.kv_head_offset + d];
        t = t + 1u;
    }

    output[d] = sum;
}
