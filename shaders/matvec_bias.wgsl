// Fused Matrix-Vector Multiply + Bias Add
// output[n] = sum_k(W[n*K + k] * input[k]) + bias[n]
// Eliminates staging buffer + copy_buffer_to_buffer hazard on P100.

struct Params {
    N: u32,
    K: u32,
    _pad0: u32,
    _pad1: u32,
}

@group(0) @binding(0) var<storage, read> input: array<f32>;
@group(0) @binding(1) var<storage, read> weights: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<f32>;
@group(0) @binding(3) var<uniform> params: Params;
@group(0) @binding(4) var<storage, read> bias: array<f32>;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let n = gid.x;
    if (n >= params.N) { return; }

    var sum: f32 = 0.0;
    let w_base = n * params.K;

    let k8 = params.K & ~7u;
    var k: u32 = 0u;
    while (k < k8) {
        sum += weights[w_base + k]      * input[k];
        sum += weights[w_base + k + 1u] * input[k + 1u];
        sum += weights[w_base + k + 2u] * input[k + 2u];
        sum += weights[w_base + k + 3u] * input[k + 3u];
        sum += weights[w_base + k + 4u] * input[k + 4u];
        sum += weights[w_base + k + 5u] * input[k + 5u];
        sum += weights[w_base + k + 6u] * input[k + 6u];
        sum += weights[w_base + k + 7u] * input[k + 7u];
        k = k + 8u;
    }
    while (k < params.K) {
        sum += weights[w_base + k] * input[k];
        k = k + 1u;
    }

    output[n] = sum + bias[n];
}
