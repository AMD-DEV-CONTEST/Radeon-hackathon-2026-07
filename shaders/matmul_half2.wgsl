// cesarops-inference/shaders/matmul_half2.wgsl
// P100 Optimized: Packed FP16x2 SIMD vectors for 2:1 throughput
// Pascal SM 6.0 — no tensor cores, uses packed vec2<f16> register lanes

enable f16;

struct MatrixDimensions {
    m: u32,
    k: u32,
    n: u32,
    pad: u32, // Structural memory alignment boundary padding
};

@group(0) @binding(0) var<storage, read> matrix_a: array<vec2<f16>>;
@group(0) @binding(1) var<storage, read> matrix_b_t: array<vec2<f16>>;
@group(0) @binding(2) var<storage, read_write> matrix_c: array<f32>;
@group(0) @binding(3) var<uniform> dims: MatrixDimensions;

// Tiled workgroups matched to Pascal warp boundaries (16x16 lanes = 256 threads)
@compute @workgroup_size(16, 16, 1)
fn main(
    @builtin(global_invocation_id) global_id: vec3<u32>,
    @builtin(local_invocation_id) local_id: vec3<u32>
) {
    let row = global_id.y;
    let col = global_id.x;

    // Boundary check
    if (row >= dims.m || col >= dims.n) {
        return;
    }

    // Initialize accumulation registers
    var accumulator: vec2<f16> = vec2<f16>(0.0h, 0.0h);

    // Stride optimization: K is halved because vec2 packs two f16 per element
    let halved_k = dims.k / 2u;
    let idx_a_base = row * halved_k;
    let idx_b_base = col * halved_k;

    for (var i: u32 = 0u; i < halved_k; i = i + 1u) {
        let val_a = matrix_a[idx_a_base + i];
        let val_b_t = matrix_b_t[idx_b_base + i];

        // Parallel 2-way element-wise multiply on packed register
        accumulator = accumulator + (val_a * val_b_t);
    }

    // Resolve vec2 to single f32 scalar
    let final_scalar_sum = f32(accumulator.x) + f32(accumulator.y);

    // Write back to output buffer
    let out_idx = row * dims.n + col;
    matrix_c[out_idx] = final_scalar_sum;
}
