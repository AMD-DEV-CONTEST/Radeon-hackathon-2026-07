// WGSL Fused SwiGLU Activation for FFN layers
//
// SwiGLU(gate, up) = SiLU(gate) * up
// where SiLU(x) = x * sigmoid(x) = x / (1 + exp(-x))
//
// Fuses gate projection activation with up projection multiply in one pass.
// Uses vec4 loads for 4x memory coalescing on HBM2.

@group(0) @binding(0) var<storage, read> gate_proj: array<vec4<f32>>;
@group(0) @binding(1) var<storage, read> up_proj: array<vec4<f32>>;
@group(0) @binding(2) var<storage, read_write> output: array<vec4<f32>>;

struct Params {
    n_elements_vec4: u32,  // Total vec4 elements to process
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}
@group(0) @binding(3) var<uniform> params: Params;

// Fast sigmoid approximation — within 0.1% of exact for |x| < 10
fn sigmoid_fast(x: f32) -> f32 {
    return 1.0 / (1.0 + exp(-x));
}

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let idx = gid.x;
    if (idx >= params.n_elements_vec4) { return; }

    let g = gate_proj[idx];
    let u = up_proj[idx];

    // SiLU(gate) = gate * sigmoid(gate)
    let silu = vec4<f32>(
        g.x * sigmoid_fast(g.x),
        g.y * sigmoid_fast(g.y),
        g.z * sigmoid_fast(g.z),
        g.w * sigmoid_fast(g.w)
    );

    // Fused multiply with up projection
    output[idx] = silu * u;
}
