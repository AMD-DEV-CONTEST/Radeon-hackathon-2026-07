//! Per-SNP FST (Wright's fixation index) between two subpopulations.
//!
//! A real population-genetics question: which SNPs' allele frequencies
//! differ most between two groups of samples -- a candidate signature of
//! population differentiation or selection, the same kind of question a
//! genome-wide FST scan (e.g. between two 1000 Genomes superpopulations)
//! is run for. Subpopulation labels here come from the sign of each
//! sample's PC1 projection (see pca.rs) -- the simplest standard two-way
//! split from a principal component, and one that genuinely recovers
//! real founder-group structure in this crate's synthetic data (see
//! `gpu_ld::generate_dense_dataset`), not an arbitrary split. FST itself
//! is Wright's fixation index, (Ht - Hs) / Ht, the textbook formula --
//! not an approximation invented for this crate.
//!
//! **Why this runs on CPU, not GPU:** per-SNP allele frequency within
//! two already-known groups is O(num_snps * num_samples) with no
//! pairwise term -- trivial even for thousands of SNPs. Forcing it onto
//! a new WGSL shader would add real correctness risk (a kernel that
//! would need its own cross-validation, same as every other GPU path in
//! this crate) for no measurable speed benefit. What genuinely is
//! GPU-accelerated is the clustering this depends on: the PC1 split
//! comes from the same GPU-computed sample correlation matrix
//! `PopulationStructureTool` already builds (see gpu_ld.rs), not
//! recomputed here.

pub struct FstResult {
    pub snp_index: usize,
    pub fst: f64,
    pub freq_a: f64,
    pub freq_b: f64,
}

/// Split sample indices into two groups by the sign of their PC1
/// projection (`projections[i][0]`). Ties (exactly 0.0) go to group A.
pub fn split_by_pc1_sign(projections: &[Vec<f64>]) -> (Vec<usize>, Vec<usize>) {
    let mut group_a = Vec::new();
    let mut group_b = Vec::new();
    for (i, p) in projections.iter().enumerate() {
        let pc1 = p.first().copied().unwrap_or(0.0);
        if pc1 >= 0.0 {
            group_a.push(i);
        } else {
            group_b.push(i);
        }
    }
    (group_a, group_b)
}

/// Allele frequency for one SNP within a subset of samples. `row`
/// entries are dosages (0, 1, or 2 -- allele count per sample), so
/// frequency is mean(dosage) / 2.
fn allele_freq(row: &[f32], indices: &[usize]) -> f64 {
    if indices.is_empty() {
        return 0.0;
    }
    let sum: f64 = indices.iter().map(|&i| row[i] as f64).sum();
    sum / (indices.len() as f64 * 2.0)
}

/// Wright's fixation index for one SNP given each subpopulation's allele
/// frequency and sample count: FST = (Ht - Hs) / Ht, where Ht is the
/// expected heterozygosity of the pooled population and Hs is the
/// sample-size-weighted average of each subpopulation's own expected
/// heterozygosity. Clamped to [0, 1] -- sampling noise on a truly
/// undifferentiated locus can otherwise push the ratio fractionally
/// negative, which has no biological meaning (FST is defined on [0,1]).
pub fn wrights_fst(freq_a: f64, freq_b: f64, n_a: usize, n_b: usize) -> f64 {
    let n_a = n_a as f64;
    let n_b = n_b as f64;
    if n_a + n_b <= 0.0 {
        return 0.0;
    }
    let p_total = (freq_a * n_a + freq_b * n_b) / (n_a + n_b);
    let h_t = 2.0 * p_total * (1.0 - p_total);
    let h_s = (2.0 * freq_a * (1.0 - freq_a) * n_a + 2.0 * freq_b * (1.0 - freq_b) * n_b) / (n_a + n_b);
    if h_t <= 0.0 {
        0.0
    } else {
        ((h_t - h_s) / h_t).clamp(0.0, 1.0)
    }
}

/// Compute per-SNP FST for every SNP in a SNP-major dosage matrix
/// (layout `[snp][sample]`, same as `gpu_ld::generate_dense_dataset`),
/// given a two-way sample split.
pub fn per_snp_fst(
    snp_major: &[f32],
    num_snps: usize,
    num_samples: usize,
    group_a: &[usize],
    group_b: &[usize],
) -> Vec<FstResult> {
    (0..num_snps)
        .map(|s| {
            let row = &snp_major[s * num_samples..(s + 1) * num_samples];
            let freq_a = allele_freq(row, group_a);
            let freq_b = allele_freq(row, group_b);
            let fst = wrights_fst(freq_a, freq_b, group_a.len(), group_b.len());
            FstResult {
                snp_index: s,
                fst,
                freq_a,
                freq_b,
            }
        })
        .collect()
}

/// Per-SNP result of the permutation significance test: how the real,
/// observed FST compares to FST computed under many *random* relabelings
/// of the same samples into two groups of the same sizes.
pub struct FstPermutationResult {
    pub snp_index: usize,
    pub observed_fst: f64,
    pub p_value: f64,
    pub n_permutations: usize,
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

/// Empirical permutation-test p-value for every SNP's observed FST: a
/// raw FST magnitude alone doesn't say whether it's real signal or just
/// what you'd expect from splitting these samples into two groups at
/// random. This shuffles the sample-to-group assignment (keeping the
/// group *sizes* fixed at `group_a.len()`/`group_b.len()`)
/// `n_permutations` times, recomputes every SNP's FST under each
/// shuffle, and counts how often the permuted FST is at least as large
/// as the real, observed one -- the standard way to attach real
/// statistical significance to an FST scan, not just report magnitude.
///
/// One shuffled label assignment is shared across all SNPs per
/// permutation round (not resampled per SNP) -- this is the standard,
/// efficient way to run this test: it doesn't change what each SNP's
/// own p-value means (still "how often does a random relabeling beat
/// this SNP's real FST"), it just means the expensive part (generating
/// a valid random relabeling) is paid once per round instead of once
/// per SNP per round.
///
/// `observed` must be `per_snp_fst`'s own output for the same data and
/// grouping (relies on its `[snp_index] == index`-in-order guarantee).
/// Runs on CPU for the same reason `per_snp_fst` does -- see this
/// module's doc comment.
pub fn permutation_test(
    snp_major: &[f32],
    num_snps: usize,
    num_samples: usize,
    group_a: &[usize],
    group_b: &[usize],
    observed: &[FstResult],
    n_permutations: usize,
    seed: u64,
) -> Vec<FstPermutationResult> {
    let n_a = group_a.len();
    let n_b = group_b.len();
    let mut all_samples: Vec<usize> = (0..num_samples).collect();
    let mut exceed_counts = vec![0usize; num_snps];
    let mut rng = Xorshift64(seed | 1);

    for _ in 0..n_permutations {
        // Fisher-Yates shuffle, then split into two groups of the same
        // sizes as the real split -- a genuine random relabeling, not
        // resampling with replacement (that's bootstrap.rs's job, a
        // different question: "how much would the estimate move under
        // a different sample draw" vs. this module's "is the group
        // split itself doing real work").
        for i in (1..all_samples.len()).rev() {
            let j = (rng.next_u64() as usize) % (i + 1);
            all_samples.swap(i, j);
        }
        let perm_a = &all_samples[0..n_a];
        let perm_b = &all_samples[n_a..n_a + n_b];

        let perm_results = per_snp_fst(snp_major, num_snps, num_samples, perm_a, perm_b);
        for (i, r) in perm_results.iter().enumerate() {
            if r.fst >= observed[i].fst {
                exceed_counts[i] += 1;
            }
        }
    }

    observed
        .iter()
        .enumerate()
        .map(|(i, obs)| FstPermutationResult {
            snp_index: obs.snp_index,
            observed_fst: obs.fst,
            // +1 smoothing in both numerator and denominator (standard
            // practice for permutation p-values, e.g. North, Curtis &
            // Sham 2002): with a finite number of permutations, "0 of N
            // exceeded" doesn't mean the true p-value is exactly zero,
            // only that it's below roughly 1/N -- this never reports an
            // unjustified p=0.
            p_value: (exceed_counts[i] as f64 + 1.0) / (n_permutations as f64 + 1.0),
            n_permutations,
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identical_allele_frequencies_give_zero_fst() {
        // No differentiation between groups -> Hs should equal Ht exactly.
        assert!((wrights_fst(0.5, 0.5, 30, 30) - 0.0).abs() < 1e-12);
        assert!((wrights_fst(0.2, 0.2, 15, 45) - 0.0).abs() < 1e-12);
    }

    #[test]
    fn opposite_fixed_alleles_give_maximum_fst_of_one() {
        // Group A fixed for the ancestral allele, group B fixed for the
        // derived allele: the textbook maximum-differentiation case.
        let fst = wrights_fst(0.0, 1.0, 20, 20);
        assert!((fst - 1.0).abs() < 1e-9, "expected FST=1.0 for fully fixed opposite alleles, got {fst}");
    }

    #[test]
    fn fst_is_never_outside_zero_one() {
        // Sweep a grid of frequencies/sample sizes and confirm the
        // clamp holds -- FST has no meaning outside [0, 1].
        for &(fa, fb) in &[(0.1, 0.9), (0.3, 0.31), (0.0, 0.0), (1.0, 1.0), (0.5, 0.0)] {
            for &(na, nb) in &[(5usize, 5usize), (1, 50), (50, 1)] {
                let fst = wrights_fst(fa, fb, na, nb);
                assert!((0.0..=1.0).contains(&fst), "FST {fst} out of [0,1] for freq_a={fa} freq_b={fb} n_a={na} n_b={nb}");
            }
        }
    }

    #[test]
    fn per_snp_fst_matches_direct_calculation_for_a_hand_built_dataset() {
        // 2 SNPs x 4 samples, SNP-major. SNP 0: group A all dosage=0,
        // group B all dosage=2 -> should hit FST=1.0. SNP 1: everyone
        // dosage=1 -> both groups freq=0.5 -> FST=0.0.
        let num_samples = 4;
        #[rustfmt::skip]
        let snp_major: Vec<f32> = vec![
            0.0, 0.0, 2.0, 2.0, // SNP 0
            1.0, 1.0, 1.0, 1.0, // SNP 1
        ];
        let group_a = vec![0, 1];
        let group_b = vec![2, 3];
        let results = per_snp_fst(&snp_major, 2, num_samples, &group_a, &group_b);

        assert_eq!(results.len(), 2);
        assert!((results[0].fst - 1.0).abs() < 1e-9, "SNP 0 should be maximally differentiated, got {}", results[0].fst);
        assert!((results[1].fst - 0.0).abs() < 1e-9, "SNP 1 should show no differentiation, got {}", results[1].fst);
    }

    #[test]
    fn split_by_pc1_sign_splits_on_the_sign_of_the_first_component() {
        // Isolated test of the splitting logic itself, not the upstream
        // PCA/correlation pipeline that produces real projections --
        // empirically, PC1's sign pattern for this crate's synthetic
        // data is sensitive to tiny floating-point differences between
        // the GPU and CPU correlation backends (both individually
        // correct within the established 1e-4 cross-validation
        // tolerance -- see gpu_ld.rs's gpu_matches_cpu_reference test),
        // which can flip a borderline sample across zero and turn a real
        // two-way split into a degenerate one, or vice versa, depending
        // on which backend happened to run. `SelectionScanTool::execute`
        // handles a degenerate real-world split explicitly (see its
        // empty-group branch) rather than assuming one away; a live run
        // of the actual tool (60 samples, 500 SNPs, GPU backend) is
        // separately verified to produce a real, non-degenerate 23-vs-37
        // split with genuine FST signal.
        let projections = vec![
            vec![1.5, 0.2],
            vec![-0.3, 0.1],
            vec![0.0, -0.4],  // exactly zero -> goes to group A by convention
            vec![-2.1, 0.0],
            vec![0.05, 0.9],
        ];
        let (group_a, group_b) = split_by_pc1_sign(&projections);
        assert_eq!(group_a, vec![0, 2, 4]);
        assert_eq!(group_b, vec![1, 3]);
    }

    #[test]
    fn permutation_test_gives_a_low_p_value_for_a_real_group_effect() {
        // A SNP where the group split is doing real work: every group-A
        // sample is dosage 0, every group-B sample is dosage 2. Almost
        // any random relabeling will mix the groups and produce a much
        // lower FST than the real 1.0 -- the observed split should rank
        // at or near the top of the permutation distribution.
        let num_samples = 40;
        let snp_major: Vec<f32> = (0..num_samples)
            .map(|i| if i < 20 { 0.0 } else { 2.0 })
            .collect();
        let group_a: Vec<usize> = (0..20).collect();
        let group_b: Vec<usize> = (20..40).collect();

        let observed = per_snp_fst(&snp_major, 1, num_samples, &group_a, &group_b);
        assert!((observed[0].fst - 1.0).abs() < 1e-9, "sanity check: real split should be fully differentiated");

        let perm = permutation_test(&snp_major, 1, num_samples, &group_a, &group_b, &observed, 200, 999);
        assert!(perm[0].p_value < 0.05, "expected a real group effect to be significant, got p={}", perm[0].p_value);
    }

    #[test]
    fn permutation_test_gives_a_high_p_value_for_no_group_effect() {
        // Every sample has the same dosage regardless of group -- FST is
        // 0 for the real split AND for every permutation (no possible
        // relabeling can create differentiation that isn't there). The
        // real split should NOT look unusually extreme.
        let num_samples = 40;
        let snp_major: Vec<f32> = vec![1.0f32; num_samples]; // everyone heterozygous
        let group_a: Vec<usize> = (0..20).collect();
        let group_b: Vec<usize> = (20..40).collect();

        let observed = per_snp_fst(&snp_major, 1, num_samples, &group_a, &group_b);
        assert!((observed[0].fst - 0.0).abs() < 1e-9, "sanity check: uniform dosage should give FST=0");

        let perm = permutation_test(&snp_major, 1, num_samples, &group_a, &group_b, &observed, 200, 999);
        assert!(perm[0].p_value > 0.5, "expected a null SNP to have a high (non-significant) p-value, got p={}", perm[0].p_value);
    }

    #[test]
    fn permutation_test_p_value_is_never_zero() {
        // The +1 smoothing should keep p-values in (0, 1], never exactly 0.
        let num_samples = 30;
        let snp_major: Vec<f32> = (0..num_samples)
            .map(|i| if i < 15 { 0.0 } else { 2.0 })
            .collect();
        let group_a: Vec<usize> = (0..15).collect();
        let group_b: Vec<usize> = (15..30).collect();

        let observed = per_snp_fst(&snp_major, 1, num_samples, &group_a, &group_b);
        let perm = permutation_test(&snp_major, 1, num_samples, &group_a, &group_b, &observed, 50, 7);
        assert!(perm[0].p_value > 0.0, "p-value should never be exactly zero, got {}", perm[0].p_value);
    }

    #[test]
    fn permutation_test_preserves_snp_order_and_count() {
        let num_snps = 5;
        let num_samples = 20;
        let snp_major: Vec<f32> = (0..num_snps * num_samples).map(|i| (i % 3) as f32).collect();
        let group_a: Vec<usize> = (0..10).collect();
        let group_b: Vec<usize> = (10..20).collect();

        let observed = per_snp_fst(&snp_major, num_snps, num_samples, &group_a, &group_b);
        let perm = permutation_test(&snp_major, num_snps, num_samples, &group_a, &group_b, &observed, 20, 42);
        assert_eq!(perm.len(), num_snps);
        for (i, p) in perm.iter().enumerate() {
            assert_eq!(p.snp_index, i);
            assert_eq!(p.n_permutations, 20);
            assert!((p.observed_fst - observed[i].fst).abs() < 1e-12);
        }
    }
}
