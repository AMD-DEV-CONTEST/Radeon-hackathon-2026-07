// WGSL RoPE (Rotary Positional Embedding) for Tesla P100
//
// RoPE rotates pairs of elements at positions (d, d + head_dim/2):
//   q[d]            = q[d] * cos(θ) - q[d + half] * sin(θ)
//   q[d + half]     = q[d] * sin(θ) + q[d + half] * cos(θ)
// where θ = pos / 10000^(2d / head_dim)
//
// This shader processes one head at a time. Dispatch one workgroup per head.
// Each thread handles one rotation pair.

struct Params {
    head_dim: u32,      // Dimension per head (e.g. 128)
    pos: u32,           // Token position in sequence
    n_heads: u32,       // Number of heads being processed
    _pad: u32,
}

@group(0) @binding(0) var<storage, read_write> qk: array<f32>;
@group(0) @binding(1) var<uniform> params: Params;

@compute @workgroup_size(64, 1, 1)
fn main(
    @builtin(global_invocation_id) gid: vec3<u32>,
    @builtin(workgroup_id) wid: vec3<u32>,
    @builtin(local_invocation_id) lid: vec3<u32>,
) {
    let head_idx = wid.x;
    let pair_idx = lid.x; // Local thread index within workgroup = pair within head
    let half_dim = params.head_dim / 2u;

    if (pair_idx >= half_dim) { return; }
    if (head_idx >= params.n_heads) { return; }

    // Compute rotation angle
    // θ = pos / 10000^(2 * pair_idx / head_dim)
    let freq_exp = -2.0 * f32(pair_idx) / f32(params.head_dim);
    let theta = f32(params.pos) * pow(1000000.0, freq_exp);
    let cos_t = cos(theta);
    let sin_t = sin(theta);

    // Element indices: (d, d + head_dim/2) within this head
    let base = head_idx * params.head_dim;
    let idx_lo = base + pair_idx;
    let idx_hi = base + pair_idx + half_dim;

    // Load pair
    let x0 = qk[idx_lo];
    let x1 = qk[idx_hi];

    // Apply rotation
    qk[idx_lo] = x0 * cos_t - x1 * sin_t;
    qk[idx_hi] = x0 * sin_t + x1 * cos_t;
}
