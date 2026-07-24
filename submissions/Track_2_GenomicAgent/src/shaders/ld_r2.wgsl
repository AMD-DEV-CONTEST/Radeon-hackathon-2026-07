// Pairwise Pearson correlation compute shader. Used two ways by this
// crate: (1) LD between SNPs (squared, r^2 -- direction doesn't matter
// for linkage disequilibrium), and (2) sample-by-sample correlation for
// population structure / PCA (signed, r -- direction matters, this
// becomes a covariance-like matrix fed into an eigendecomposition).
// square_output selects between them so both uses share one validated
// kernel instead of duplicating it.
//
// One GPU thread per row-pair. Each thread walks the column dimension to
// compute covariance, using precomputed per-row means/stds (computed
// once on CPU, O(n_rows * n_cols), not worth parallelizing). This is the
// same statistic as vcf::compute_r_squared / gpu_ld::cpu_r2_batch (the
// CPU references) -- gpu_ld.rs cross-validates GPU output against those
// before this kernel is trusted for anything.

struct Params {
    num_samples: u32,
    num_pairs: u32,
    square_output: u32, // 1 = output r^2 (LD use), 0 = output signed r (PCA use)
    _pad: u32,
};

@group(0) @binding(0) var<uniform> params: Params;
@group(0) @binding(1) var<storage, read> dosages: array<f32>;   // [row_idx * num_samples + col_idx]
@group(0) @binding(2) var<storage, read> means: array<f32>;     // [row_idx]
@group(0) @binding(3) var<storage, read> stds: array<f32>;      // [row_idx], population std (sqrt of sum of squared deviations)
@group(0) @binding(4) var<storage, read> pair_i: array<u32>;    // [pair_idx]
@group(0) @binding(5) var<storage, read> pair_j: array<u32>;    // [pair_idx]
@group(0) @binding(6) var<storage, read_write> out_r: array<f32>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let k = gid.x;
    if (k >= params.num_pairs) {
        return;
    }

    let i = pair_i[k];
    let j = pair_j[k];
    let ns = params.num_samples;
    let mean_i = means[i];
    let mean_j = means[j];
    let base_i = i * ns;
    let base_j = j * ns;

    var cov: f32 = 0.0;
    for (var s: u32 = 0u; s < ns; s = s + 1u) {
        let xi = dosages[base_i + s] - mean_i;
        let xj = dosages[base_j + s] - mean_j;
        cov = cov + xi * xj;
    }

    let denom = stds[i] * stds[j];
    if (denom <= 0.0) {
        out_r[k] = 0.0;
    } else {
        let r = cov / denom;
        if (params.square_output != 0u) {
            out_r[k] = r * r;
        } else {
            out_r[k] = r;
        }
    }
}
