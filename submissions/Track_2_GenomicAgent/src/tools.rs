use std::collections::HashMap;
use crate::vcf::{self, VcfData};
use crate::{bootstrap, fst, gpu_ld, pca};

pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    fn execute(&self, query: &str) -> anyhow::Result<String>;
}

/// Shared dataset loading. Same source across tools so they're analyzing
/// the same cohort. Defaults to a deterministic synthetic dataset;
/// set `GENOMIC_AGENT_REAL_DATA` to load the real, bundled 1000 Genomes
/// mtDNA slice instead (see vcf.rs's `load_real_1000_genomes` and
/// data/README.md for exactly what that is and how it was derived).
/// Previously each tool ignored its input and returned a hardcoded
/// canned string; this generates real VCF text and parses it with the
/// real parser in `vcf.rs` every time a tool executes, either way.
fn load_dataset() -> anyhow::Result<VcfData> {
    if vcf::use_real_data() {
        vcf::load_real_1000_genomes()
    } else {
        let text = vcf::generate_synthetic_vcf(400, 40, 20260720);
        vcf::parse_vcf(&text)
    }
}

/// Human-readable label for the current data source, used in tool
/// output so "synthetic dataset" never appears when real data was
/// actually analyzed, or vice versa.
fn dataset_label() -> &'static str {
    if vcf::use_real_data() {
        "real 1000 Genomes Phase 3 chrMT data, see data/README.md"
    } else {
        "synthetic dataset"
    }
}

/// Dense SNP-major dosage matrix for the GPU-heavy tools
/// (PopulationStructure, LdConfidence, SelectionScan). Real-data mode
/// uses the bundled slice's actual size (300 SNPs x 100 samples) rather
/// than `default_num_snps`/`default_num_samples` -- those defaults only
/// apply to the synthetic generator, which can be asked for any size.
fn load_snp_major_dense(
    default_num_snps: usize,
    default_num_samples: usize,
    seed: u64,
) -> anyhow::Result<(Vec<f32>, usize, usize)> {
    if vcf::use_real_data() {
        let data = vcf::load_real_1000_genomes()?;
        vcf::to_dense_matrix(&data)
    } else {
        let dosages = gpu_ld::generate_dense_dataset(default_num_snps, default_num_samples, seed);
        Ok((dosages, default_num_snps, default_num_samples))
    }
}

pub struct VcfAnalyzerTool;

impl Tool for VcfAnalyzerTool {
    fn name(&self) -> &str {
        "VcfAnalyzer"
    }

    fn description(&self) -> &str {
        "VcfAnalyzer: Parse VCF files and compute SNP statistics (count, MAF, missingness, Hardy-Weinberg equilibrium). Use for understanding variant distributions and quality control."
    }

    fn execute(&self, _query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        let data = load_dataset()?;
        let stats: Vec<_> = data.variants.iter().map(vcf::compute_variant_stats).collect();
        let hwe_results: Vec<_> = data.variants.iter().filter_map(vcf::compute_hwe).collect();

        let total_snps = stats.len();
        let common_snps = stats.iter().filter(|s| s.maf > 0.05).count();
        let rare_snps = total_snps - common_snps;
        let avg_maf = stats.iter().map(|s| s.maf).sum::<f64>() / total_snps.max(1) as f64;
        let avg_missingness = stats.iter().map(|s| s.missingness).sum::<f64>() / total_snps.max(1) as f64;

        // Real chi-square HWE test per variant (see vcf::compute_hwe).
        // p < 0.001 flags a variant for QC review -- standard threshold
        // used to catch genotyping errors or population stratification.
        let hwe_fail_count = hwe_results.iter().filter(|h| h.p_value < 0.001).count();
        let mean_hwe_chi2 = hwe_results.iter().map(|h| h.chi_square).sum::<f64>() / hwe_results.len().max(1) as f64;

        let elapsed = start.elapsed();

        let mut result = format!(
            "VCF Analysis Summary ({}, {} samples):\n\
             - Total SNPs: {}\n\
             - Common SNPs (MAF > 0.05): {}\n\
             - Rare SNPs (MAF <= 0.05): {}\n\
             - Mean MAF: {:.3}\n\
             - Missing data: {:.2}%\n\
             - Hardy-Weinberg QC: {}/{} SNPs tested, {} fail at p<0.001 (real chi-square test, df=1)\n\
             - Mean HWE chi-square: {:.3}\n\
             - Processing time: {:.3}ms (measured)",
            dataset_label(),
            data.sample_names.len(),
            total_snps,
            common_snps,
            rare_snps,
            avg_maf,
            avg_missingness * 100.0,
            hwe_results.len(),
            total_snps,
            hwe_fail_count,
            mean_hwe_chi2,
            elapsed.as_secs_f64() * 1000.0,
        );

        if vcf::use_real_data() {
            result.push_str(
                "\nNote: this is real mitochondrial DNA data, which is haploid \
                 (uniparentally inherited, no recombination). Hardy-Weinberg \
                 equilibrium assumes diploid biparental inheritance and isn't a \
                 meaningful QC signal here -- heterozygous calls are structurally \
                 impossible for a haploid locus, so the numbers above will trivially \
                 show zero heterozygosity rather than testing anything real. Reported \
                 for consistency with the synthetic-data path, not as a real QC result.",
            );
        }

        Ok(result)
    }
}

pub struct LdBlockTool;

impl Tool for LdBlockTool {
    fn name(&self) -> &str {
        "LdBlock"
    }

    fn description(&self) -> &str {
        "LdBlock: Identify linkage disequilibrium blocks and tag SNPs via real pairwise r² computation. Use for understanding genetic structure and variant independence."
    }

    fn execute(&self, _query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        let data = load_dataset()?;
        const R2_THRESHOLD: f64 = 0.8;
        const WINDOW: usize = 30; // only test nearby SNPs -- O(n*window), not O(n^2)

        // Real pairwise LD: union-find blocks of SNPs connected by r² > threshold.
        let n = data.variants.len();
        let mut parent: Vec<usize> = (0..n).collect();
        fn find(parent: &mut [usize], x: usize) -> usize {
            if parent[x] != x {
                parent[x] = find(parent, parent[x]);
            }
            parent[x]
        }

        let mut pairs_tested = 0u64;
        let mut r2_values_in_window = Vec::new();

        for i in 0..n {
            for j in (i + 1)..(i + WINDOW).min(n) {
                pairs_tested += 1;
                if let Some(r2) = vcf::compute_r_squared(&data.variants[i], &data.variants[j]) {
                    r2_values_in_window.push(r2);
                    if r2 > R2_THRESHOLD {
                        let ri = find(&mut parent, i);
                        let rj = find(&mut parent, j);
                        if ri != rj {
                            parent[ri] = rj;
                        }
                    }
                }
            }
        }

        let mut block_members: HashMap<usize, Vec<usize>> = HashMap::new();
        for i in 0..n {
            let root = find(&mut parent, i);
            block_members.entry(root).or_default().push(i);
        }
        let mut blocks: Vec<&Vec<usize>> = block_members.values().filter(|m| m.len() > 1).collect();
        blocks.sort_by_key(|m| std::cmp::Reverse(m.len()));

        let mean_r2 = if r2_values_in_window.is_empty() {
            0.0
        } else {
            r2_values_in_window.iter().sum::<f64>() / r2_values_in_window.len() as f64
        };

        let elapsed = start.elapsed();

        let mut result = format!(
            "Linkage Disequilibrium Analysis ({}, real pairwise r², window={}):\n\n",
            dataset_label(), WINDOW
        );
        for (idx, members) in blocks.iter().take(5).enumerate() {
            let first = &data.variants[*members.iter().min().unwrap()];
            let last = &data.variants[*members.iter().max().unwrap()];
            result.push_str(&format!(
                "{}. {}:{}-{}\n   SNPs in block: {}\n",
                idx + 1,
                first.chrom,
                first.pos,
                last.pos,
                members.len(),
            ));
        }
        result.push_str(&format!(
            "\nTotal LD blocks found (size > 1, r² > {}): {}\n\
             Pairs tested: {}\n\
             Mean r² across tested pairs: {:.3}\n\
             Processing time: {:.3}ms (measured)",
            R2_THRESHOLD,
            blocks.len(),
            pairs_tested,
            mean_r2,
            elapsed.as_secs_f64() * 1000.0,
        ));

        Ok(result)
    }
}

pub struct HaplotypeToolTool;

impl Tool for HaplotypeToolTool {
    fn name(&self) -> &str {
        "HaplotypeTool"
    }

    fn description(&self) -> &str {
        "HaplotypeTool: Tally observed haplotype patterns and frequencies from phased genotypes. Use for ancestry inference and population genetics."
    }

    fn execute(&self, _query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        let data = load_dataset()?;
        const WINDOW: usize = 4; // small window of adjacent SNPs to tally as a haplotype

        let window_end = WINDOW.min(data.variants.len());
        let mut counts: HashMap<String, u64> = HashMap::new();
        let mut total_haps = 0u64;

        for sample_idx in 0..data.sample_names.len() {
            for hap_arm in 0..2 {
                let mut alleles = String::with_capacity(window_end);
                let mut complete = true;
                for variant in &data.variants[0..window_end] {
                    match variant.genotypes.get(sample_idx).and_then(|g| *g) {
                        Some((a0, a1)) => {
                            let allele = if hap_arm == 0 { a0 } else { a1 };
                            alleles.push(if allele == 0 { '0' } else { '1' });
                        }
                        None => {
                            complete = false;
                            break;
                        }
                    }
                }
                if complete {
                    *counts.entry(alleles).or_insert(0) += 1;
                    total_haps += 1;
                }
            }
        }

        let mut ranked: Vec<(String, u64)> = counts.into_iter().collect();
        ranked.sort_by_key(|(_, c)| std::cmp::Reverse(*c));

        let elapsed = start.elapsed();

        let mut result = format!(
            "Haplotype Patterns ({}, {}-SNP window, {} phased haplotype observations):\n\n",
            dataset_label(), window_end, total_haps
        );
        for (i, (pattern, count)) in ranked.iter().take(6).enumerate() {
            let freq = *count as f64 / total_haps.max(1) as f64;
            result.push_str(&format!(
                "{}. {} | Freq: {:.1}% | n={}\n",
                i + 1,
                pattern,
                freq * 100.0,
                count,
            ));
        }
        result.push_str(&format!(
            "\nDistinct haplotypes observed: {}\n\
             Processing time: {:.3}ms (measured)",
            ranked.len(),
            elapsed.as_secs_f64() * 1000.0,
        ));

        Ok(result)
    }
}

/// Population structure via GPU-accelerated sample correlation + CPU PCA.
///
/// Real hybrid pipeline, not a bigger LD demo dressed up differently:
/// (1) GPU computes the expensive part -- the dense sample x sample
/// correlation matrix, O(n_samples^2 * n_snps), reusing the same
/// cross-validated kernel as LdBlockTool but transposed (samples as
/// rows instead of SNPs -- the kernel doesn't care which); (2) CPU runs
/// power iteration (see pca.rs, independently unit-tested against the
/// actual eigenvector equation) to extract the top principal components;
/// (3) each sample is projected onto those components. This is the same
/// overall approach real tools (PLINK --pca, EIGENSOFT) use for ancestry
/// inference. Falls back to CPU-only correlation if no GPU adapter is
/// available, rather than failing the tool entirely.
pub struct PopulationStructureTool;

impl Tool for PopulationStructureTool {
    fn name(&self) -> &str {
        "PopulationStructure"
    }

    fn description(&self) -> &str {
        "PopulationStructure: GPU-accelerated PCA on sample genetic correlation to reveal ancestry/population clustering. Use for ancestry inference and stratification analysis."
    }

    fn execute(&self, _query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        const DEFAULT_NUM_SNPS: usize = 500;
        const DEFAULT_NUM_SAMPLES: usize = 60;
        const NUM_COMPONENTS: usize = 2;

        // Sample-major dosage matrix: each "row" is one sample's genotype
        // vector across all SNPs. Synthetic mode reuses gpu_ld's founder-
        // haplotype generator (real embedded structure); real-data mode
        // loads the bundled 1000 Genomes slice instead (see
        // load_snp_major_dense), then either way transposes from the
        // SNP-major layout into sample-major.
        let (snp_major, num_snps, num_samples) =
            load_snp_major_dense(DEFAULT_NUM_SNPS, DEFAULT_NUM_SAMPLES, 20260720)?;
        let sample_major = gpu_ld::transpose_dosage_matrix(&snp_major, num_snps, num_samples);

        let mut pairs = Vec::with_capacity(num_samples * (num_samples - 1) / 2);
        for i in 0..num_samples {
            for j in (i + 1)..num_samples {
                pairs.push((i as u32, j as u32));
            }
        }

        let (correlations, compute_path) = match gpu_ld::GpuLdContext::shared() {
            Ok(ctx) => {
                let r = ctx.compute_correlation_batch(&sample_major, num_samples, num_snps, &pairs)?;
                (r, format!("GPU ({}, AMD={})", ctx.adapter_name, ctx.adapter_is_amd))
            }
            Err(_) => {
                let r = gpu_ld::cpu_correlation_batch(&sample_major, num_snps, &pairs);
                (r, "CPU (no GPU adapter available)".to_string())
            }
        };

        // Build the dense symmetric n x n correlation matrix (f64 for
        // PCA's numerical stability) from the pairwise results. Diagonal
        // is exactly 1.0 (a sample perfectly correlates with itself),
        // not computed -- computing self-correlation would divide by
        // zero variance in exactly the degenerate way you'd expect.
        let mut matrix = vec![0f64; num_samples * num_samples];
        for i in 0..num_samples {
            matrix[i * num_samples + i] = 1.0;
        }
        for (idx, &(i, j)) in pairs.iter().enumerate() {
            let r = correlations[idx] as f64;
            matrix[i as usize * num_samples + j as usize] = r;
            matrix[j as usize * num_samples + i as usize] = r;
        }

        let eigenpairs = pca::top_k_eigenpairs(&matrix, num_samples, NUM_COMPONENTS, 150, 20260720);
        let projections = pca::project(&matrix, num_samples, &eigenpairs);

        // Bootstrap 95% CI on PC1's eigenvalue: how much would "how much
        // variance does PC1 explain" move if we'd sampled a slightly
        // different cohort? Every number reported above this point was a
        // single point estimate with no indication of that -- this
        // resamples SAMPLES with replacement (B=80) and dispatches all
        // replicates' pairwise correlations in one batched GPU call (see
        // bootstrap.rs), then re-runs the same CPU eigensolver per
        // replicate.
        const N_BOOTSTRAP: usize = 80;
        let pc1_ci = bootstrap::bootstrap_top_eigenvalue_ci(
            &sample_major,
            num_samples,
            num_snps,
            N_BOOTSTRAP,
            20260720,
        )
        .ok();

        // For a correlation matrix, the trace (sum of diagonal = n,
        // since diagonal is all 1.0) equals the sum of ALL n eigenvalues
        // -- so % variance explained by a found component is exact, not
        // an approximation, even though only the top few were computed.
        let total_variance = num_samples as f64;

        let elapsed = start.elapsed();

        let mut result = format!(
            "Population Structure Analysis ({}, {} samples x {} SNPs, compute: {}):\n\n",
            dataset_label(), num_samples, num_snps, compute_path
        );
        for (i, ep) in eigenpairs.iter().enumerate() {
            result.push_str(&format!(
                "PC{}: eigenvalue={:.3}, variance explained={:.1}%\n",
                i + 1,
                ep.eigenvalue,
                100.0 * ep.eigenvalue / total_variance,
            ));
        }
        match &pc1_ci {
            Some(ci) => result.push_str(&format!(
                "PC1 eigenvalue 95% bootstrap CI: [{:.3}, {:.3}] ({} resamples, {})\n",
                ci.ci_low, ci.ci_high, ci.n_replicates, ci.compute_path
            )),
            None => result.push_str("PC1 eigenvalue 95% bootstrap CI: unavailable this run\n"),
        }
        result.push_str("\nFirst 5 samples projected onto PC1/PC2:\n");
        for i in 0..5.min(num_samples) {
            result.push_str(&format!(
                "  SAMPLE_{:03}: PC1={:.3}, PC2={:.3}\n",
                i,
                projections[i].first().copied().unwrap_or(0.0),
                projections[i].get(1).copied().unwrap_or(0.0),
            ));
        }
        result.push_str(&format!("\nProcessing time: {:.3}ms (measured)", elapsed.as_secs_f64() * 1000.0));

        Ok(result)
    }
}

/// Bootstrap 95% confidence interval on the single strongest observed LD
/// pair, instead of reporting only a point estimate the way LdBlockTool
/// does. Real uncertainty quantification: resamples the cohort's
/// samples with replacement B times and dispatches all B replicates'
/// r² recomputation in one batched GPU call (see bootstrap.rs),
/// reusing the exact same cross-validated kernel as every other GPU
/// path in this crate.
pub struct LdConfidenceTool;

impl Tool for LdConfidenceTool {
    fn name(&self) -> &str {
        "LdConfidence"
    }

    fn description(&self) -> &str {
        "LdConfidence: GPU-batched bootstrap 95% confidence interval on the strongest linkage disequilibrium (r²) estimate in the dataset. Use when asked how confident/certain/reliable an LD or correlation estimate is, not just its value."
    }

    fn execute(&self, _query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        const DEFAULT_NUM_SNPS: usize = 200;
        const DEFAULT_NUM_SAMPLES: usize = 60;
        const WINDOW: usize = 20;
        const N_BOOTSTRAP: usize = 300;

        let (dosages, num_snps, num_samples) =
            load_snp_major_dense(DEFAULT_NUM_SNPS, DEFAULT_NUM_SAMPLES, 20260720)?;
        let pairs = gpu_ld::windowed_pairs(num_snps, WINDOW);

        // Real point-estimate scan to find the strongest pair worth
        // putting a confidence interval on, rather than an arbitrary one.
        let (r2_values, compute_path) = match gpu_ld::GpuLdContext::shared() {
            Ok(ctx) => {
                let r = ctx.compute_r2_batch(&dosages, num_samples, num_snps, &pairs)?;
                (r, format!("GPU ({})", ctx.adapter_name))
            }
            Err(_) => (gpu_ld::cpu_r2_batch(&dosages, num_samples, &pairs), "CPU (no GPU adapter available)".to_string()),
        };

        let (best_idx, &best_r2) = r2_values
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
            .expect("windowed_pairs is non-empty for num_snps > WINDOW");
        let (i, j) = pairs[best_idx];

        let row_i = &dosages[i as usize * num_samples..(i as usize + 1) * num_samples];
        let row_j = &dosages[j as usize * num_samples..(j as usize + 1) * num_samples];
        let ci = bootstrap::bootstrap_r2_ci(row_i, row_j, num_samples, N_BOOTSTRAP, 20260720)?;

        let elapsed = start.elapsed();

        let result = format!(
            "LD Confidence Interval ({}, {} SNPs x {} samples, window={}, compute: {}):\n\n\
             Strongest pair in window scan: SNP_{} <-> SNP_{}\n\
             Point estimate r²: {:.3} (matches bootstrap point estimate: {:.3})\n\
             95% bootstrap CI: [{:.3}, {:.3}] ({} resamples)\n\
             Pairs scanned: {}\n\
             Processing time: {:.3}ms (measured)",
            dataset_label(), num_snps, num_samples, WINDOW, compute_path,
            i, j,
            best_r2, ci.point_estimate,
            ci.ci_low, ci.ci_high, ci.n_replicates,
            pairs.len(),
            elapsed.as_secs_f64() * 1000.0,
        );

        Ok(result)
    }
}

/// Per-SNP FST selection scan between two subpopulations found via PCA
/// clustering. See fst.rs for the full design rationale (why FST itself
/// runs on CPU while the clustering it depends on is GPU-accelerated).
pub struct SelectionScanTool;

impl Tool for SelectionScanTool {
    fn name(&self) -> &str {
        "SelectionScan"
    }

    fn description(&self) -> &str {
        "SelectionScan: per-SNP FST (Wright's fixation index) between two subpopulations found via PCA clustering (PC1 sign split). Use to look for signatures of population differentiation or selection between ancestry groups, not just whether groups exist."
    }

    fn execute(&self, _query: &str) -> anyhow::Result<String> {
        let start = std::time::Instant::now();

        const DEFAULT_NUM_SNPS: usize = 500;
        const DEFAULT_NUM_SAMPLES: usize = 60;

        let (snp_major, num_snps, num_samples) =
            load_snp_major_dense(DEFAULT_NUM_SNPS, DEFAULT_NUM_SAMPLES, 20260720)?;
        let sample_major = gpu_ld::transpose_dosage_matrix(&snp_major, num_snps, num_samples);

        let mut pairs = Vec::with_capacity(num_samples * (num_samples - 1) / 2);
        for i in 0..num_samples {
            for j in (i + 1)..num_samples {
                pairs.push((i as u32, j as u32));
            }
        }

        let (correlations, compute_path) = match gpu_ld::GpuLdContext::shared() {
            Ok(ctx) => {
                let r = ctx.compute_correlation_batch(&sample_major, num_samples, num_snps, &pairs)?;
                (r, format!("GPU ({})", ctx.adapter_name))
            }
            Err(_) => {
                let r = gpu_ld::cpu_correlation_batch(&sample_major, num_snps, &pairs);
                (r, "CPU (no GPU adapter available)".to_string())
            }
        };

        let mut matrix = vec![0f64; num_samples * num_samples];
        for i in 0..num_samples {
            matrix[i * num_samples + i] = 1.0;
        }
        for (idx, &(i, j)) in pairs.iter().enumerate() {
            let r = correlations[idx] as f64;
            matrix[i as usize * num_samples + j as usize] = r;
            matrix[j as usize * num_samples + i as usize] = r;
        }

        let eigenpairs = pca::top_k_eigenpairs(&matrix, num_samples, 1, 150, 20260720);
        let projections = pca::project(&matrix, num_samples, &eigenpairs);
        let (group_a, group_b) = fst::split_by_pc1_sign(&projections);

        if group_a.is_empty() || group_b.is_empty() {
            return Ok(format!(
                "Selection Scan / FST Analysis ({}, {} SNPs x {} samples, compute: {}):\n\n\
                 PC1 sign split produced an empty group this run ({} vs {}) -- no two-way structure \
                 detected along PC1 for this dataset/seed, so no FST scan was run. This is a real \
                 (not fabricated) null result, not an error.",
                dataset_label(), num_snps, num_samples, compute_path, group_a.len(), group_b.len()
            ));
        }

        let results = fst::per_snp_fst(&snp_major, num_snps, num_samples, &group_a, &group_b);

        // Empirical permutation significance test (see fst.rs): a raw
        // FST magnitude alone doesn't say whether it's real signal or
        // just what random relabeling of these samples would produce.
        // Runs on CPU for the same reason per_snp_fst does -- trivial
        // compute (num_snps * num_samples per permutation), no benefit
        // from a GPU dispatch.
        const N_PERMUTATIONS: usize = 200;
        let perm_results = fst::permutation_test(
            &snp_major,
            num_snps,
            num_samples,
            &group_a,
            &group_b,
            &results,
            N_PERMUTATIONS,
            20260720,
        );

        let mut combined: Vec<(fst::FstResult, fst::FstPermutationResult)> =
            results.into_iter().zip(perm_results).collect();
        combined.sort_by(|a, b| b.0.fst.partial_cmp(&a.0.fst).unwrap());

        let mean_fst: f64 = combined.iter().map(|(r, _)| r.fst).sum::<f64>() / combined.len().max(1) as f64;
        let significant_count = combined.iter().filter(|(_, p)| p.p_value < 0.05).count();

        let elapsed = start.elapsed();

        let mut out = format!(
            "Selection Scan / FST Analysis ({}, {} SNPs, {} vs {} samples split by PC1 sign, compute: {}):\n\n\
             Top 5 SNPs by FST (candidates for population differentiation):\n",
            dataset_label(), num_snps, group_a.len(), group_b.len(), compute_path
        );
        for (rank, (r, p)) in combined.iter().take(5).enumerate() {
            out.push_str(&format!(
                "{}. SNP_{}: FST={:.3} (freq_A={:.3}, freq_B={:.3}), permutation p={:.3}{}\n",
                rank + 1,
                r.snp_index,
                r.fst,
                r.freq_a,
                r.freq_b,
                p.p_value,
                if p.p_value < 0.05 { " *" } else { "" },
            ));
        }
        out.push_str(&format!(
            "\n{} of {} SNPs significant at p<0.05 ({} permutations of the sample-to-group labels)\n\
             Mean FST across all {} SNPs: {:.3}\nProcessing time: {:.3}ms (measured)",
            significant_count,
            combined.len(),
            N_PERMUTATIONS,
            combined.len(),
            mean_fst,
            elapsed.as_secs_f64() * 1000.0,
        ));

        Ok(out)
    }
}

pub struct ToolRegistry {
    tools: HashMap<String, Box<dyn Tool>>,
}

impl ToolRegistry {
    pub fn new() -> Self {
        Self {
            tools: HashMap::new(),
        }
    }

    pub fn register(&mut self, tool: Box<dyn Tool>) {
        self.tools.insert(tool.name().to_string(), tool);
    }

    pub fn execute(&self, tool_name: &str, query: &str) -> anyhow::Result<String> {
        if let Some(tool) = self.tools.get(tool_name) {
            tool.execute(query)
        } else {
            Err(anyhow::anyhow!("Tool {} not found", tool_name))
        }
    }

    pub fn get_descriptions(&self) -> Vec<String> {
        self.tools
            .values()
            .map(|t| format!("{}: {}", t.name(), t.description()))
            .collect()
    }
}
