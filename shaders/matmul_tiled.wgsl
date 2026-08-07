// WGSL Tiled Matrix Multiplication for Tesla P100
// 16×16 workgroup with shared memory tiling for HBM2 bandwidth optimization.
//
// C[M×N] = A[M×K] × B[K×N]
//
// Each workgroup computes a 16×16 output tile.
// Tiles are loaded cooperatively into workgroup shared memory,
// then the inner dot product runs entirely from the fast local cache.
//
// Memory access pattern:
//   - A is row-major: A[row][k] = matrix_a[row * K + k]
//   - B is row-major: B[k][col] = matrix_b[k * N + col]
//   - Coalesced reads: threads in a row read consecutive K elements (A)
//     and threads in a column read consecutive N elements (B)
//
// P100 specifics:
//   - 48KB shared memory per SM → can fit 16×16×4×2 = 2KB (trivial)
//   - 60 SMs × (16×16 = 256 threads/workgroup) = up to 60 concurrent workgroups
//   - HBM2 732 GB/s — tiling reduces global memory reads by 16× vs naive

struct Params {
    M: u32,
    K: u32,
    N: u32,
    _pad: u32,
}

@group(0) @binding(0) var<storage, read> matrix_a: array<f32>;
@group(0) @binding(1) var<storage, read> matrix_b: array<f32>;
@group(0) @binding(2) var<storage, read_write> matrix_c: array<f32>;
@group(0) @binding(3) var<uniform> params: Params;

// Shared memory tiles — 16×16 f32 each = 1024 bytes per tile
var<workgroup> tile_a: array<array<f32, 16>, 16>;
var<workgroup> tile_b: array<array<f32, 16>, 16>;

@compute @workgroup_size(16, 16, 1)
fn main(
    @builtin(local_invocation_id) lid: vec3<u32>,
    @builtin(global_invocation_id) gid: vec3<u32>,
) {
    let row = gid.y;  // Output row (into M)
    let col = gid.x;  // Output col (into N)
    let lr = lid.y;   // Local row within tile
    let lc = lid.x;   // Local col within tile

    var acc: f32 = 0.0;
    let num_tiles = (params.K + 15u) / 16u;

    for (var t: u32 = 0u; t < num_tiles; t = t + 1u) {
        // Cooperative tile load: each thread loads one element of each tile

        // Load A tile: A[row][t*16 + lc]
        let a_col = t * 16u + lc;
        if (row < params.M && a_col < params.K) {
            tile_a[lr][lc] = matrix_a[row * params.K + a_col];
        } else {
            tile_a[lr][lc] = 0.0;
        }

        // Load B tile: B[t*16 + lr][col]
        let b_row = t * 16u + lr;
        if (b_row < params.K && col < params.N) {
            tile_b[lr][lc] = matrix_b[b_row * params.N + col];
        } else {
            tile_b[lr][lc] = 0.0;
        }

        // Barrier: ensure entire tile is loaded before computation
        workgroupBarrier();

        // Inner product from shared memory — 16 multiply-adds, zero global reads
        acc += tile_a[lr][0u]  * tile_b[0u][lc];
        acc += tile_a[lr][1u]  * tile_b[1u][lc];
        acc += tile_a[lr][2u]  * tile_b[2u][lc];
        acc += tile_a[lr][3u]  * tile_b[3u][lc];
        acc += tile_a[lr][4u]  * tile_b[4u][lc];
        acc += tile_a[lr][5u]  * tile_b[5u][lc];
        acc += tile_a[lr][6u]  * tile_b[6u][lc];
        acc += tile_a[lr][7u]  * tile_b[7u][lc];
        acc += tile_a[lr][8u]  * tile_b[8u][lc];
        acc += tile_a[lr][9u]  * tile_b[9u][lc];
        acc += tile_a[lr][10u] * tile_b[10u][lc];
        acc += tile_a[lr][11u] * tile_b[11u][lc];
        acc += tile_a[lr][12u] * tile_b[12u][lc];
        acc += tile_a[lr][13u] * tile_b[13u][lc];
        acc += tile_a[lr][14u] * tile_b[14u][lc];
        acc += tile_a[lr][15u] * tile_b[15u][lc];

        // Barrier: prevent next tile load from overwriting current computation
        workgroupBarrier();
    }

    // Write result to global memory
    if (row < params.M && col < params.N) {
        matrix_c[row * params.N + col] = acc;
    }
}
