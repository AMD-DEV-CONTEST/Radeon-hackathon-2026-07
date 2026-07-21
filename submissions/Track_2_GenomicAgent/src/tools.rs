use std::collections::HashMap;
use crate::vcf::{self, VcfData};
use crate::{bootstrap, gpu_ld, pca};

pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    fn execute(&self, query: &str) -> anyhow::Result<String>;
}

/// Shared synthetic dataset generation. Same seed/size across tools so
/// they're analyzing the same (clearly synthetic) cohort. Previously
/// each tool ignored its input and returned a hardcoded canned string;
/// this generates real VCF text and parses it with the real parser in
/// `vcf.rs` every time a tool executes.
fn load_dataset() -> anyhow::Result<VcfData> {
    let text = vcf::generate_synthetic_vcf(400, 40, 20260720);
    vcf::parse_vcf(&text)
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

        let result = format!(
            "VCF Analysis Summary (synthetic dataset, {} samples):\n\
             - Total SNPs: {}\n\
             - Common SNPs (MAF > 0.05): {}\n\
             - Rare SNPs (MAF <= 0.05): {}\n\
             - Mean MAF: {:.3}\n\
             - Missing data: {:.2}%\n\
             - Hardy-Weinberg QC: {}/{} SNPs tested, {} fail at p<0.001 (real chi-square test, df=1)\n\
             - Mean HWE chi-square: {:.3}\n\
             - Processing time: {:.3}ms (measured)",
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
            "Linkage Disequilibrium Analysis (synthetic dataset, real pairwise r², window={}):\n\n",
            WINDOW
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
            "Haplotype Patterns (synthetic dataset, {}-SNP window, {} phased haplotype observations):\n\n",
            window_end, total_haps
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

        const NUM_SNPS: usize = 500;
        const NUM_SAMPLES: usize = 60;
        const NUM_COMPONENTS: usize = 2;

        // Sample-major dosage matrix: each "row" is one sample's genotype
        // vector across all SNPs. Reuses gpu_ld's founder-haplotype
        // synthetic generator (real embedded structure), then transposes
        // from the SNP-major layout that generator produces.
        let snp_major = gpu_ld::generate_dense_dataset(NUM_SNPS, NUM_SAMPLES, 20260720);
        let sample_major = gpu_ld::transpose_dosage_matrix(&snp_major, NUM_SNPS, NUM_SAMPLES);

        let mut pairs = Vec::with_capacity(NUM_SAMPLES * (NUM_SAMPLES - 1) / 2);
        for i in 0..NUM_SAMPLES {
            for j in (i + 1)..NUM_SAMPLES {
                pairs.push((i as u32, j as u32));
            }
        }

        let (correlations, compute_path) = match gpu_ld::GpuLdContext::shared() {
            Ok(ctx) => {
                let r = ctx.compute_correlation_batch(&sample_major, NUM_SAMPLES, NUM_SNPS, &pairs)?;
                (r, format!("GPU ({}, AMD={})", ctx.adapter_name, ctx.adapter_is_amd))
            }
            Err(_) => {
                let r = gpu_ld::cpu_correlation_batch(&sample_major, NUM_SNPS, &pairs);
                (r, "CPU (no GPU adapter available)".to_string())
            }
        };

        // Build the dense symmetric n x n correlation matrix (f64 for
        // PCA's numerical stability) from the pairwise results. Diagonal
        // is exactly 1.0 (a sample perfectly correlates with itself),
        // not computed -- computing self-correlation would divide by
        // zero variance in exactly the degenerate way you'd expect.
        let mut matrix = vec![0f64; NUM_SAMPLES * NUM_SAMPLES];
        for i in 0..NUM_SAMPLES {
            matrix[i * NUM_SAMPLES + i] = 1.0;
        }
        for (idx, &(i, j)) in pairs.iter().enumerate() {
            let r = correlations[idx] as f64;
            matrix[i as usize * NUM_SAMPLES + j as usize] = r;
            matrix[j as usize * NUM_SAMPLES + i as usize] = r;
        }

        let eigenpairs = pca::top_k_eigenpairs(&matrix, NUM_SAMPLES, NUM_COMPONENTS, 150, 20260720);
        let projections = pca::project(&matrix, NUM_SAMPLES, &eigenpairs);

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
            NUM_SAMPLES,
            NUM_SNPS,
            N_BOOTSTRAP,
            20260720,
        )
        .ok();

        // For a correlation matrix, the trace (sum of diagonal = n,
        // since diagonal is all 1.0) equals the sum of ALL n eigenvalues
        // -- so % variance explained by a found component is exact, not
        // an approximation, even though only the top few were computed.
        let total_variance = NUM_SAMPLES as f64;

        let elapsed = start.elapsed();

        let mut result = format!(
            "Population Structure Analysis (synthetic dataset, {} samples x {} SNPs, compute: {}):\n\n",
            NUM_SAMPLES, NUM_SNPS, compute_path
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
        for i in 0..5.min(NUM_SAMPLES) {
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

        const NUM_SNPS: usize = 200;
        const NUM_SAMPLES: usize = 60;
        const WINDOW: usize = 20;
        const N_BOOTSTRAP: usize = 300;

        let dosages = gpu_ld::generate_dense_dataset(NUM_SNPS, NUM_SAMPLES, 20260720);
        let pairs = gpu_ld::windowed_pairs(NUM_SNPS, WINDOW);

        // Real point-estimate scan to find the strongest pair worth
        // putting a confidence interval on, rather than an arbitrary one.
        let (r2_values, compute_path) = match gpu_ld::GpuLdContext::shared() {
            Ok(ctx) => {
                let r = ctx.compute_r2_batch(&dosages, NUM_SAMPLES, NUM_SNPS, &pairs)?;
                (r, format!("GPU ({})", ctx.adapter_name))
            }
            Err(_) => (gpu_ld::cpu_r2_batch(&dosages, NUM_SAMPLES, &pairs), "CPU (no GPU adapter available)".to_string()),
        };

        let (best_idx, &best_r2) = r2_values
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
            .expect("windowed_pairs is non-empty for NUM_SNPS > WINDOW");
        let (i, j) = pairs[best_idx];

        let row_i = &dosages[i as usize * NUM_SAMPLES..(i as usize + 1) * NUM_SAMPLES];
        let row_j = &dosages[j as usize * NUM_SAMPLES..(j as usize + 1) * NUM_SAMPLES];
        let ci = bootstrap::bootstrap_r2_ci(row_i, row_j, NUM_SAMPLES, N_BOOTSTRAP, 20260720)?;

        let elapsed = start.elapsed();

        let result = format!(
            "LD Confidence Interval (synthetic dataset, {} SNPs x {} samples, window={}, compute: {}):\n\n\
             Strongest pair in window scan: SNP_{} <-> SNP_{}\n\
             Point estimate r²: {:.3} (matches bootstrap point estimate: {:.3})\n\
             95% bootstrap CI: [{:.3}, {:.3}] ({} resamples)\n\
             Pairs scanned: {}\n\
             Processing time: {:.3}ms (measured)",
            NUM_SNPS, NUM_SAMPLES, WINDOW, compute_path,
            i, j,
            best_r2, ci.point_estimate,
            ci.ci_low, ci.ci_high, ci.n_replicates,
            pairs.len(),
            elapsed.as_secs_f64() * 1000.0,
        );

        Ok(result)
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
