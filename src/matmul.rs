// src/matmul.rs
// Pure CPU matrix multiply kernels.
// Cache-friendly loop order (i, k, j) for sequential memory stride.
// TODO: Replace with wgpu shader dispatch for GPU acceleration.

/// Standard C = A × B where A is [m, k], B is [k, n], output is [m, n].
pub fn matmul_f32(a: &[f32], b: &[f32], m: usize, k: usize, n: usize) -> Vec<f32> {
    let mut c = vec![0.0f32; m * n];
    for i in 0..m {
        let idx_a_row = i * k;
        let idx_c_row = i * n;
        for l in 0..k {
            let val_a = a[idx_a_row + l];
            let idx_b_row = l * n;
            for j in 0..n {
                c[idx_c_row + j] += val_a * b[idx_b_row + j];
            }
        }
    }
    c
}

/// Standard C = A × B in f64 precision (for Xeon AVX-512 curvelet math).
pub fn matmul_f64(a: &[f64], b: &[f64], m: usize, k: usize, n: usize) -> Vec<f64> {
    let mut c = vec![0.0f64; m * n];
    for i in 0..m {
        let idx_a_row = i * k;
        let idx_c_row = i * n;
        for l in 0..k {
            let val_a = a[idx_a_row + l];
            let idx_b_row = l * n;
            for j in 0..n {
                c[idx_c_row + j] += val_a * b[idx_b_row + j];
            }
        }
    }
    c
}

/// C = A × B^T where B is stored transposed [n, k].
/// Used for attention score computation (Q × K^T).
pub fn matmul_f32_transposed_b(a: &[f32], b_t: &[f32], m: usize, k: usize, n: usize) -> Vec<f32> {
    let mut c = vec![0.0f32; m * n];
    for i in 0..m {
        let idx_a_row = i * k;
        let idx_c_row = i * n;
        for j in 0..n {
            let idx_b_row = j * k;
            let mut dot_product = 0.0f32;
            for l in 0..k {
                dot_product += a[idx_a_row + l] * b_t[idx_b_row + l];
            }
            c[idx_c_row + j] = dot_product;
        }
    }
    c
}
