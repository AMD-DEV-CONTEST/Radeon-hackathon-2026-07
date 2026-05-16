// WGSL Attention QK^T with proper KV cache stride for multi-head layout.
//
// KV cache layout: [pos][n_kv_heads][head_dim]
// For a specific kv_head, key at position i is at:
//   key_cache[i * kv_stride + kv_head_offset + j]
// where kv_stride = n_kv_heads * head_dim, kv_head_offset = kv_head * head_dim

struct Params {
    kv_len: u32,           // Number of positions to attend to
    head_dim: u32,         // Dimension per head (128 for Qwen 1.5B)
    cur_pos: u32,          // Current position (for causal mask)
    scale: f32,            // 1.0 / sqrt(head_dim)
    kv_stride: u32,        // Stride between positions in KV cache (n_kv_heads * head_dim)
    kv_head_offset: u32,   // Byte offset to this KV head within each position
    _pad0: u32,
    _pad1: u32,
}

@group(0) @binding(0) var<storage, read> query: array<f32>;      // [head_dim]
@group(0) @binding(1) var<storage, read> key_cache: array<f32>;  // Full KV cache
@group(0) @binding(2) var<storage, read_write> scores: array<f32>; // [kv_len]
@group(0) @binding(3) var<uniform> params: Params;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.kv_len) { return; }

    // Causal mask
    if (i > params.cur_pos) {
        scores[i] = -3.40282347e38;
        return;
    }

    // Key for position i, this kv_head:
    // key_cache[i * kv_stride + kv_head_offset + j]
    let k_base = i * params.kv_stride + params.kv_head_offset;

    var dot: f32 = 0.0;
    let hd4 = params.head_dim & ~3u;
    var j: u32 = 0u;
    while (j < hd4) {
        dot += query[j]      * key_cache[k_base + j];
        dot += query[j + 1u] * key_cache[k_base + j + 1u];
        dot += query[j + 2u] * key_cache[k_base + j + 2u];
        dot += query[j + 3u] * key_cache[k_base + j + 3u];
        j = j + 4u;
    }
    while (j < params.head_dim) {
        dot += query[j] * key_cache[k_base + j];
        j = j + 1u;
    }

    scores[i] = dot * params.scale;
}
