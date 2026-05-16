// WGSL compute shader for C = A × B^T where:
//   A is [m x k], B_T is [k x n] -> C is [m x n]
// Each thread computes one element of C.

struct MatrixDimensions {
    m: u32,
    k: u32,
    n: u32,
}

@group(0) @binding(0) var<storage, read> bufA: array<f32>;
@group(0) @binding(1) var<storage, read> bufBT: array<f32>;
@group(0) @binding(2) var<storage, read_write> bufC: array<f32>;
@group(0) @binding(3) var<uniform> dims: MatrixDimensions;

@compute @workgroup_size(8, 8)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let col = gid.x; // column index (into N)
    let row = gid.y; // row index (into M)

    if (col >= dims.n || row >= dims.m) {
        return;
    }

    var sum: f32 = 0.0;
    var i: u32 = 0u;
    while (i < dims.k) { 
        // A[row * k + i]
        let a_idx: i32 = i32(row * dims.k + i);
        // B_T[i * n + col]
        let b_idx: i32 = i32(i * dims.n + col);
        sum += bufA[a_idx] * bufBT[b_idx];
        i = i + 1u;
    }

    let c_idx: i32 = i32(col); // note: row-major C[row * n + col], but for simplicity we store at [col][row] mapped linearly as row*n+col
    bufC[row * dims.n + col] = sum;
}
