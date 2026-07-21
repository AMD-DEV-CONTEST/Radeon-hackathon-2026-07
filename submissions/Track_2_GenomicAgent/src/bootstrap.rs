//! GPU-batched nonparametric bootstrap confidence intervals.
//!
//! Every statistic this crate reported before this module was a single
//! point estimate (one r², one eigenvalue) with no indication of how
//! much that number would move if the cohort had been sampled slightly
//! differently. This module adds real sampling-variability estimates via
//! the standard nonparametric bootstrap: resample samples with
//! replacement, recompute the statistic, repeat, and take percentiles of
//! the resulting distribution as the confidence interval. This is a
//! textbook technique (Efron & Tibshirani), not a novel one -- what's
//! real about this implementation is that all B replicates for a given
//! statistic are dispatched to the GPU in a *single* batched call
//! (reusing the exact same cross-validated kernel as `gpu_ld.rs`'s LD
//! and PCA-correlation paths, just handed more rows), rather than paying
//! per-replicate dispatch overhead B times.
//!
//! Both functions here fall back to the CPU reference implementation if
//! no GPU adapter is available, same as the rest of this crate -- a
//! bootstrap CI computed on CPU is still a real bootstrap CI, just
//! slower.

use crate::{gpu_ld, pca};
use anyhow::Result;

pub struct BootstrapCi {
    pub point_estimate: f64,
    pub ci_low: f64,
    pub ci_high: f64,
    pub n_replicates: usize,
    pub compute_path: String,
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
}

/// 95% percentile bootstrap interval from a sorted-in-place sample of
/// replicate statistics. Standard percentile method: sort, take the
/// 2.5th/97.5th percentile. Simple and adequate for the roughly
/// symmetric statistics used here (r², top eigenvalue); more advanced
/// bootstrap variants (BCa, studentized) correct skew/bias this doesn't,
/// which is a real limitation worth stating rather than glossing over.
fn percentile_ci(mut values: Vec<f64>) -> (f64, f64) {
    values.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = values.len();
    let lo_idx = ((n as f64) * 0.025).floor() as usize;
    let hi_idx = (((n as f64) * 0.975).ceil() as usize).min(n - 1);
    (values[lo_idx], values[hi_idx])
}

/// Bootstrap 95% CI on the Pearson r² between two dosage rows (same
/// `num_samples` length), resampling samples with replacement.
/// `row_i`/`row_j` should come from the same real (unresampled) dataset
/// -- the point estimate is computed from them directly, and bootstrap
/// replicates resample the *pairing* of (sample i's value in row_i,
/// sample i's value in row_j) together, which is what preserves
/// whatever real correlation exists between the two rows.
pub fn bootstrap_r2_ci(
    row_i: &[f32],
    row_j: &[f32],
    num_samples: usize,
    n_replicates: usize,
    seed: u64,
) -> Result<BootstrapCi> {
    assert_eq!(row_i.len(), num_samples);
    assert_eq!(row_j.len(), num_samples);

    let mut point_dosages = Vec::with_capacity(2 * num_samples);
    point_dosages.extend_from_slice(row_i);
    point_dosages.extend_from_slice(row_j);
    let point_estimate =
        gpu_ld::cpu_r2_batch(&point_dosages, num_samples, &[(0, 1)])[0] as f64;

    let mut rng = Xorshift64(seed | 1);
    let mut boot_dosages = Vec::with_capacity(2 * n_replicates * num_samples);
    let mut boot_pairs = Vec::with_capacity(n_replicates);
    for b in 0..n_replicates {
        let idx: Vec<usize> = (0..num_samples)
            .map(|_| (rng.next_u64() as usize) % num_samples)
            .collect();
        boot_dosages.extend(idx.iter().map(|&k| row_i[k]));
        boot_dosages.extend(idx.iter().map(|&k| row_j[k]));
        boot_pairs.push((2 * b as u32, 2 * b as u32 + 1));
    }

    let (values, compute_path) = match gpu_ld::GpuLdContext::shared() {
        Ok(ctx) => {
            let r = ctx.compute_r2_batch(&boot_dosages, num_samples, 2 * n_replicates, &boot_pairs)?;
            (r, format!("GPU ({})", ctx.adapter_name))
        }
        Err(_) => {
            let r = gpu_ld::cpu_r2_batch(&boot_dosages, num_samples, &boot_pairs);
            (r, "CPU (no GPU adapter available)".to_string())
        }
    };

    let (ci_low, ci_high) = percentile_ci(values.iter().map(|v| *v as f64).collect());

    Ok(BootstrapCi {
        point_estimate,
        ci_low,
        ci_high,
        n_replicates,
        compute_path,
    })
}

/// Bootstrap 95% CI on the top (PC1) eigenvalue of the sample x sample
/// correlation matrix, resampling *samples* (rows of `sample_major`,
/// which must be [sample][snp] layout -- see
/// `gpu_ld::transpose_dosage_matrix`) with replacement. All B
/// replicates' pairwise correlations are dispatched in one GPU call:
/// each replicate's resampled sample rows are concatenated into one
/// larger dosage buffer, with a `pairs` list restricted to within-
/// replicate index blocks (never cross-replicate), so the existing
/// kernel does all the expensive correlation work in a single dispatch
/// and only the (cheap, small-matrix) eigendecomposition loops B times
/// on CPU.
pub fn bootstrap_top_eigenvalue_ci(
    sample_major: &[f32],
    num_samples: usize,
    num_snps: usize,
    n_replicates: usize,
    seed: u64,
) -> Result<BootstrapCi> {
    let all_pairs: Vec<(u32, u32)> = (0..num_samples as u32)
        .flat_map(|i| ((i + 1)..num_samples as u32).map(move |j| (i, j)))
        .collect();

    let point_estimate = top_eigenvalue_from_correlations(
        sample_major,
        num_samples,
        num_snps,
        &all_pairs,
        seed,
    )?;

    let mut rng = Xorshift64(seed.wrapping_add(1) | 1);
    let mut boot_dosages = Vec::with_capacity(n_replicates * num_samples * num_snps);
    let mut boot_pairs = Vec::with_capacity(n_replicates * all_pairs.len());
    for b in 0..n_replicates {
        let base = (b * num_samples) as u32;
        let idx: Vec<usize> = (0..num_samples)
            .map(|_| (rng.next_u64() as usize) % num_samples)
            .collect();
        for &k in &idx {
            boot_dosages.extend_from_slice(&sample_major[k * num_snps..(k + 1) * num_snps]);
        }
        boot_pairs.extend(all_pairs.iter().map(|&(i, j)| (base + i, base + j)));
    }

    let (correlations, compute_path) = match gpu_ld::GpuLdContext::shared() {
        Ok(ctx) => {
            let r = ctx.compute_correlation_batch(
                &boot_dosages,
                n_replicates * num_samples,
                num_snps,
                &boot_pairs,
            )?;
            (r, format!("GPU ({})", ctx.adapter_name))
        }
        Err(_) => {
            let r = gpu_ld::cpu_correlation_batch(&boot_dosages, num_snps, &boot_pairs);
            (r, "CPU (no GPU adapter available)".to_string())
        }
    };

    let pairs_per_rep = all_pairs.len();
    let mut eigenvalues = Vec::with_capacity(n_replicates);
    for b in 0..n_replicates {
        let slice = &correlations[b * pairs_per_rep..(b + 1) * pairs_per_rep];
        let matrix = build_symmetric_matrix(slice, &all_pairs, num_samples);
        let ep = pca::top_k_eigenpairs(&matrix, num_samples, 1, 150, seed.wrapping_add(b as u64 + 2));
        eigenvalues.push(ep[0].eigenvalue);
    }

    let (ci_low, ci_high) = percentile_ci(eigenvalues);

    Ok(BootstrapCi {
        point_estimate,
        ci_low,
        ci_high,
        n_replicates,
        compute_path,
    })
}

fn top_eigenvalue_from_correlations(
    sample_major: &[f32],
    num_samples: usize,
    num_snps: usize,
    pairs: &[(u32, u32)],
    seed: u64,
) -> Result<f64> {
    let correlations = match gpu_ld::GpuLdContext::shared() {
        Ok(ctx) => ctx.compute_correlation_batch(sample_major, num_samples, num_snps, pairs)?,
        Err(_) => gpu_ld::cpu_correlation_batch(sample_major, num_snps, pairs),
    };
    let matrix = build_symmetric_matrix(&correlations, pairs, num_samples);
    let ep = pca::top_k_eigenpairs(&matrix, num_samples, 1, 150, seed);
    Ok(ep[0].eigenvalue)
}

fn build_symmetric_matrix(values: &[f32], pairs: &[(u32, u32)], n: usize) -> Vec<f64> {
    let mut matrix = vec![0f64; n * n];
    for i in 0..n {
        matrix[i * n + i] = 1.0;
    }
    for (&(i, j), &r) in pairs.iter().zip(values.iter()) {
        let (i, j) = (i as usize, j as usize);
        matrix[i * n + j] = r as f64;
        matrix[j * n + i] = r as f64;
    }
    matrix
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_rows_give_a_tight_ci_around_r_squared_one() {
        // Zero sampling variability possible here: every bootstrap
        // resample of two IDENTICAL rows still has r²=1.0 exactly, no
        // matter which samples get drawn -- this is a known-ground-truth
        // case, not just "does it run."
        let num_samples = 30;
        let row: Vec<f32> = (0..num_samples).map(|i| (i % 3) as f32).collect();
        let ci = bootstrap_r2_ci(&row, &row, num_samples, 100, 42).unwrap();
        assert!((ci.point_estimate - 1.0).abs() < 1e-3, "point estimate should be ~1.0, got {}", ci.point_estimate);
        assert!((ci.ci_low - 1.0).abs() < 1e-3, "CI should collapse to ~1.0 for a zero-variance statistic, got low={}", ci.ci_low);
        assert!((ci.ci_high - 1.0).abs() < 1e-3, "CI should collapse to ~1.0 for a zero-variance statistic, got high={}", ci.ci_high);
    }

    #[test]
    fn unrelated_rows_give_a_ci_that_spans_low_r_squared() {
        let num_samples = 40;
        let dosages = gpu_ld::generate_dense_dataset(2, num_samples, 999);
        let row_i = &dosages[0..num_samples];
        let row_j = &dosages[num_samples..2 * num_samples];
        let ci = bootstrap_r2_ci(row_i, row_j, num_samples, 200, 7).unwrap();
        // Not asserting a specific value (these two SNPs' true correlation
        // depends on the synthetic generator's founder resampling and
        // isn't hand-picked here) -- just that the CI is a real interval
        // containing the point estimate, not a degenerate single value.
        assert!(ci.ci_low <= ci.point_estimate + 1e-6, "low={} point={}", ci.ci_low, ci.point_estimate);
        assert!(ci.ci_high >= ci.point_estimate - 1e-6, "high={} point={}", ci.ci_high, ci.point_estimate);
        assert!(ci.ci_high > ci.ci_low, "CI should have nonzero width for a real (non-degenerate) pair");
    }

    #[test]
    fn eigenvalue_ci_contains_the_point_estimate_on_structured_data() {
        let num_snps = 150;
        let num_samples = 25;
        let snp_major = gpu_ld::generate_dense_dataset(num_snps, num_samples, 20260721);
        let sample_major = gpu_ld::transpose_dosage_matrix(&snp_major, num_snps, num_samples);

        let ci = bootstrap_top_eigenvalue_ci(&sample_major, num_samples, num_snps, 60, 11).unwrap();
        assert!(ci.point_estimate > 0.0, "top eigenvalue of a real correlation matrix should be positive, got {}", ci.point_estimate);
        assert!(ci.ci_low <= ci.point_estimate + 1e-6, "low={} point={}", ci.ci_low, ci.point_estimate);
        assert!(ci.ci_high >= ci.point_estimate - 1e-6, "high={} point={}", ci.ci_high, ci.point_estimate);
    }
}
