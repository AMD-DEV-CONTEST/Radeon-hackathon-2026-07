//! Principal component analysis via power iteration with deflation.
//!
//! This is the CPU half of the population-structure pipeline: the GPU
//! computes the expensive part (the dense n_samples x n_samples pairwise
//! correlation matrix, O(n_samples^2 * n_snps), via gpu_ld.rs), and this
//! module extracts the top few eigenvectors of that matrix on CPU --
//! standard practice, since eigendecomposition of a small (tens to a
//! few hundred samples) matrix is cheap relative to building it, and
//! power iteration is simple enough to implement correctly and verify
//! without pulling in an external linear algebra crate.
//!
//! This is the same overall approach real population-genetics tools
//! (PLINK --pca, EIGENSOFT/smartpca) use for ancestry inference: project
//! samples onto the top principal components of their genetic
//! relationship matrix, and clusters in that projection correspond to
//! shared ancestry / population structure.

/// One eigenpair: eigenvalue and its (unit-length) eigenvector.
pub struct EigenPair {
    pub eigenvalue: f64,
    pub eigenvector: Vec<f64>,
}

struct Xorshift64(u64);
impl Xorshift64 {
    fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.0 = x;
        x
    }
    fn next_f64_signed(&mut self) -> f64 {
        (self.next_u64() % 2_000_000) as f64 / 1_000_000.0 - 1.0 // in [-1, 1)
    }
}

fn mat_vec_mul(matrix: &[f64], n: usize, v: &[f64]) -> Vec<f64> {
    let mut out = vec![0f64; n];
    for i in 0..n {
        let row = &matrix[i * n..(i + 1) * n];
        out[i] = row.iter().zip(v.iter()).map(|(a, b)| a * b).sum();
    }
    out
}

fn norm(v: &[f64]) -> f64 {
    v.iter().map(|x| x * x).sum::<f64>().sqrt()
}

fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}

/// Find the top `k` eigenpairs of a symmetric n x n `matrix` (row-major)
/// via power iteration with deflation. `iterations` controls convergence
/// per component (100 is generous for the small, well-separated matrices
/// this crate builds; increase if used on noisier or larger data).
pub fn top_k_eigenpairs(matrix: &[f64], n: usize, k: usize, iterations: usize, seed: u64) -> Vec<EigenPair> {
    let mut working = matrix.to_vec(); // deflated copy; `matrix` itself stays intact for verification by callers
    let mut rng = Xorshift64(seed | 1);
    let mut results = Vec::with_capacity(k);

    for _ in 0..k {
        let mut v: Vec<f64> = (0..n).map(|_| rng.next_f64_signed()).collect();
        let start_norm = norm(&v);
        if start_norm > 0.0 {
            v.iter_mut().for_each(|x| *x /= start_norm);
        }

        for _ in 0..iterations {
            let mut v_next = mat_vec_mul(&working, n, &v);
            let vn = norm(&v_next);
            if vn < 1e-12 {
                break; // matrix (after deflation) is ~zero in remaining directions
            }
            v_next.iter_mut().for_each(|x| *x /= vn);
            v = v_next;
        }

        // Rayleigh quotient: more accurate eigenvalue estimate than the
        // last iteration's norm, for a unit vector v: lambda = v^T M v.
        let mv = mat_vec_mul(&working, n, &v);
        let eigenvalue = dot(&v, &mv);

        // Deflate: remove this component's contribution so the next
        // power iteration converges to the next-largest eigenvalue.
        for i in 0..n {
            for j in 0..n {
                working[i * n + j] -= eigenvalue * v[i] * v[j];
            }
        }

        results.push(EigenPair { eigenvalue, eigenvector: v });
    }

    results
}

/// Project each sample (row `i` of the original correlation matrix) onto
/// the given eigenvectors -- this is what "PC1 = x, PC2 = y" per sample
/// actually means: how much that sample's row aligns with each
/// component. Standard way to visualize/report population structure.
pub fn project(matrix: &[f64], n: usize, eigenpairs: &[EigenPair]) -> Vec<Vec<f64>> {
    (0..n)
        .map(|i| {
            let row = &matrix[i * n..(i + 1) * n];
            eigenpairs.iter().map(|ep| dot(row, &ep.eigenvector)).collect()
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The defining property of an eigenvector: M @ v = lambda * v.
    /// This checks that property directly against the ORIGINAL matrix
    /// (not the deflated working copy), for every component found --
    /// not "did power iteration run without panicking," but "is the
    /// output actually a real eigenpair of the input matrix."
    #[test]
    fn found_eigenpairs_satisfy_the_eigenvector_equation() {
        // A small, real symmetric matrix (not identity, not diagonal --
        // a genuine test of the deflation + convergence logic).
        let n = 5;
        #[rustfmt::skip]
        let matrix = vec![
            4.0, 1.0, 0.5, 0.2, 0.1,
            1.0, 3.0, 0.7, 0.3, 0.2,
            0.5, 0.7, 5.0, 0.4, 0.3,
            0.2, 0.3, 0.4, 2.0, 0.6,
            0.1, 0.2, 0.3, 0.6, 3.5,
        ];

        let eigenpairs = top_k_eigenpairs(&matrix, n, 3, 200, 42);
        assert_eq!(eigenpairs.len(), 3);

        for ep in &eigenpairs {
            let mv = mat_vec_mul(&matrix, n, &ep.eigenvector); // original matrix, not deflated
            let lambda_v: Vec<f64> = ep.eigenvector.iter().map(|x| x * ep.eigenvalue).collect();
            let max_diff = mv.iter().zip(lambda_v.iter()).map(|(a, b)| (a - b).abs()).fold(0.0, f64::max);
            assert!(
                max_diff < 1e-4,
                "M@v should equal lambda*v for a real eigenpair; max diff {max_diff}, eigenvalue {}",
                ep.eigenvalue
            );
            let v_norm = norm(&ep.eigenvector);
            assert!((v_norm - 1.0).abs() < 1e-6, "eigenvector should be unit length, got norm {v_norm}");
        }
    }

    #[test]
    fn eigenvalues_are_returned_in_decreasing_order() {
        let n = 4;
        #[rustfmt::skip]
        let matrix = vec![
            10.0, 1.0, 0.5, 0.2,
            1.0, 6.0, 0.3, 0.1,
            0.5, 0.3, 3.0, 0.2,
            0.2, 0.1, 0.2, 1.0,
        ];
        let eigenpairs = top_k_eigenpairs(&matrix, n, 3, 200, 7);
        for pair in eigenpairs.windows(2) {
            assert!(
                pair[0].eigenvalue >= pair[1].eigenvalue - 1e-6,
                "eigenvalues should be non-increasing: {} then {}",
                pair[0].eigenvalue,
                pair[1].eigenvalue
            );
        }
    }

    #[test]
    fn identity_matrix_has_eigenvalue_one_in_every_direction() {
        // Degenerate but well-defined case: every vector is an
        // eigenvector of the identity matrix, with eigenvalue 1.
        let n = 4;
        let mut matrix = vec![0f64; n * n];
        for i in 0..n {
            matrix[i * n + i] = 1.0;
        }
        let eigenpairs = top_k_eigenpairs(&matrix, n, 2, 50, 99);
        for ep in &eigenpairs {
            assert!((ep.eigenvalue - 1.0).abs() < 1e-4, "identity matrix eigenvalue should be 1.0, got {}", ep.eigenvalue);
        }
    }
}
