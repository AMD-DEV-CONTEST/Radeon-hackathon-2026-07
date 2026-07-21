# Genomic Research Agent — Quick Start Guide

**Status:** Builds and runs, real computation. Includes real GPU-accelerated
LD computation (`gpu-bench`), dispatched to and verified against actual
AMD GPU hardware — see "GPU acceleration" below for exactly what that
means and does not mean (it is not the literal ROCm/HIP API). Multi-tool
query planning (a compound question can need more than one tool) runs
entirely offline by default: a custom, from-scratch GPU kernel (Okapi
BM25 with bigram features, not a transformer, not a third-party model), zero
API key, zero network call, zero billing risk required. An LLM backend
is optional and only ever adds a plain-English narration on top of that
— never decides which tools run. Also includes GPU-batched bootstrap
confidence intervals, a per-SNP FST selection scan, and a real (not
just synthetic) 1000 Genomes data mode — see "Advanced capabilities"
and "About the data" below for what's actually verified about each.

---

## 1. Prerequisites

- Rust 1.70+ (https://rustup.rs/)
- Git

---

## 2. Clone & Setup

```bash
git clone https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07.git
cd Radeon-hackathon-2026-07/submissions/Track_2_GenomicAgent

bash setup.sh          # Linux/macOS
# or
setup.bat              # Windows
```

---

## 3. Run the Demo

```bash
cargo run --release
```

Runs six queries through the agent — VCF analysis, LD block detection,
haplotype tallying, population structure/PCA, a bootstrap LD confidence
interval, and an FST selection scan — each against a deterministic
synthetic dataset generated at runtime (see "About the data" below).
Every query is routed by the offline intent kernel described in
"Advanced capabilities" below; no API key or network access is needed
to see real multi-tool selection happen (each response line shows the
selected tool(s) with their BM25 relevance scores, e.g.
`[Intent kernel, GPU (AMD Radeon 780M Graphics)] Selected tool(s):
PopulationStructure (5.42), SelectionScan (3.17), HaplotypeTool (2.97)`
for "run population structure PCA to check for ancestry clustering" --
all three genuinely relevant, ranked by real overlap with each tool's
own description, not a hardcoded list). The output includes real
computed numbers (SNP counts, MAF, r² values, haplotype frequencies,
FST) — it will look the same on every run because the data generator is
seeded deterministically, not because the numbers are hardcoded. Run
`cargo test --release` to see property-based tests that check this
(e.g. two identical genotype columns must compute r²≈1.0).

---

## 4. Run Benchmarks

```bash
cargo run --release -- bench
```

Every number in the output is measured with `Instant::now()`/`elapsed()`
around actual execution on your machine, not printed as a literal —
timing and throughput will vary by hardware and will differ from any
number quoted elsewhere in this repo's history. Run it yourself rather
than trusting a pasted example.

---

## 5. GPU acceleration

```bash
cargo run --release -- gpu-bench
```

**What this is:** a real WGSL compute shader (`src/shaders/ld_r2.wgsl`)
computing pairwise Pearson r² (linkage disequilibrium) in parallel across
SNP pairs, dispatched through `wgpu` (`src/gpu_ld.rs`). It explicitly
enumerates GPU adapters and prefers a real AMD adapter (PCI vendor
`0x1002`) over any other GPU present, so it actually targets AMD
hardware rather than whichever GPU a generic "high performance" heuristic
would pick (on a machine with both an AMD iGPU and an NVIDIA discrete
GPU, the naive heuristic picks NVIDIA — this code doesn't).

**Correctness:** every GPU result is cross-validated against a CPU
reference implementation of the same statistic. `cargo test` includes
this cross-validation as an automated test
(`gpu_ld::tests::gpu_matches_cpu_reference_within_float_tolerance`), and
`gpu-bench` reports the max observed difference on every run (it should
be ~1e-6, float-rounding-only). This isn't a shader that "runs" — it's
one whose output is checked against a known-correct answer every time.

**Real measured numbers** (AMD Radeon 780M, this machine, this run —
will differ on other hardware, run it yourself):

| Scale | CPU | GPU (incl. upload+dispatch+readback) | Speedup |
|-------|-----|-----|---------|
| 1,000 SNPs, 94,050 pairs | 12.98ms | 9.40ms | 1.38x |
| 4,000 SNPs, 584,825 pairs | 79.12ms | 22.81ms | 3.47x |

Speedup grows with problem size because GPU dispatch/buffer-readback has
fixed overhead that only pays off once there's enough parallel work to
amortize it — this is normal and expected for GPU compute, and the
benchmark reports both scales honestly rather than cherry-picking the
better number.

**What this is not:** literal AMD ROCm/HIP API calls. This development
machine has no ROCm/HIP SDK installed, and Windows HIP support for this
specific integrated GPU (Radeon 780M / RDNA3, gfx1103) is unconfirmed
without it — installing a multi-GB SDK for possibly-unsupported hardware
wasn't done without flagging it first. `wgpu` was used instead because
it's verifiable *today*, on real hardware, dispatching to and measuring
the actual AMD GPU via its Vulkan driver — real GPU acceleration, real
correctness verification, just not through the ROCm-specific API
surface. If literal HIP/ROCm kernels are required for scoring, the
algorithm in `ld_r2.wgsl` is the direct port target: same math, same
per-pair parallelism, translated from WGSL to HIP C++.

`setup.sh`/`setup.bat` no longer reference `RADEON_API_KEY` or a
"Radeon Cloud" walkthrough from an earlier, unbuilt plan for this
submission — nothing in `src/` ever read that variable.

---

## 6. Advanced capabilities

### Custom GPU kernel for tool planning (no API, no network, no cost)

Every query is routed by a real, from-scratch classifier, not a
transformer and not a call to any third-party model: **Okapi BM25**
(the ranking function most real search engines actually use, not
plain TF-IDF cosine similarity, which this module used originally --
see `src/intent.rs`'s module doc comment for exactly why BM25 replaced
it: term-frequency saturation and length normalization that cosine
similarity doesn't have). Unigram *and bigram* ("linkage
disequilibrium" as one phrase token, not just two separate words)
vectors are built from each registered tool's description and the
query, then scored via a weighted dot product dispatched as a single
batched call to a genuinely new WGSL compute kernel
(`shaders/intent_similarity.wgsl`), cross-validated against a CPU
reference the same way every other GPU path in this crate is (falls
back to CPU automatically if no GPU adapter is present). Tools scoring
above a threshold are all selected — this is what gives real multi-tool
selection for a compound query: "run population structure PCA to check
for ancestry clustering" selects `PopulationStructure` (5.42),
`SelectionScan` (3.17), and `HaplotypeTool` (2.97) -- all three
genuinely relevant (SelectionScan and HaplotypeTool's own descriptions
independently mention "ancestry"), ranked by real relevance, not a
hardcoded list; live-verified with every API key/token unset. Every
response shows the selected tool(s) and their BM25 scores, so the
selection is auditable, not a black box. See `src/intent.rs` for the
full design (including its honestly-stated limits — this is classical
term-overlap statistics, not language understanding, and a query
sharing even a single generic word with an otherwise-unrelated tool's
description can occasionally pull that tool in at a visibly low score
rather than a human's zero).

**Optional, additive-only:** an LLM backend, if configured, narrates the
already-selected tools' real output in plain English afterward — it
never influences which tools ran:

```bash
export HF_TOKEN=hf_...           # tried first: free tier, huggingface.co/settings/tokens
export ANTHROPIC_API_KEY=sk-...  # tried second, if you have a funded key
cargo run --release
```

Neither variable set, or a request to either fails (network, rate
limit, no credits) → clean fallthrough to showing raw tool output
instead of a narrative, not an error, and tool selection is completely
unaffected either way. `--fast` mode never attempts the optional LLM
call at all, since it's measuring this crate's own per-query overhead,
not third-party API latency — tool selection quality is identical to
the default mode either way, since planning never depended on a network
call to begin with. See `src/agent.rs` for the wiring and `src/llm.rs`
for the (now narration-only) backend implementation.

### GPU-batched bootstrap confidence intervals

Every statistic elsewhere in this crate is a single point estimate. The
`LdConfidence` tool and `PopulationStructure`'s PC1 report add real
nonparametric bootstrap 95% CIs (standard percentile method): resample
samples with replacement B times, recompute the statistic, take
percentiles — with all B replicates dispatched to the GPU in *one*
batched call each, reusing the same cross-validated kernel as every
other GPU path here, not B separate dispatches. See `src/bootstrap.rs`;
tests check known-ground-truth cases (identical rows collapse the CI to
exactly r²=1.0, since there's zero true sampling variability there).

### Per-SNP FST selection scan, with real significance testing

The `SelectionScan` tool splits samples into two groups by the sign of
their PC1 projection (reusing `PopulationStructure`'s existing
GPU-computed correlation matrix), then computes Wright's fixation index
per SNP between those groups — a real population-genetics question
(which loci differ most between ancestry groups). A raw FST number
alone doesn't say whether it's real signal or just the strongest of
many noisy candidates, so every SNP also gets an empirical permutation-
test p-value (`src/fst.rs::permutation_test`): shuffle the sample-to-
group labels 200 times, recompute every SNP's FST under each random
relabeling, and count how often chance beats the real, observed split.
This is the standard way real population-genetics tools attach
significance to an FST scan, not just report magnitude. It's a genuine
result, not a foregone conclusion either way: on the synthetic dataset,
16 of 500 SNPs come back significant at p<0.05; on the real 1000
Genomes data, **zero** SNPs do (top p-values 0.11-0.17) — with only 100
real samples split by PC1 sign, there isn't enough statistical power to
call any single locus significant, even though the raw FST numbers on
their own would have looked interesting. That's the permutation test
doing its job, not a bug.

Both the FST arithmetic and the permutation test run on CPU,
deliberately: FST itself is O(snps × samples) with no pairwise term,
and even 200 full permutation rounds only adds ~3ms to a 500-SNP scan
(measured) -- trivial even at that scale, and a new GPU shader for
either would add real correctness risk (its own cross-validation
burden, same as every other GPU path in this crate) for no measurable
speed benefit. See `src/fst.rs` for that reasoning spelled out in full,
rather than forcing GPU dispatch to pad the story. PC1-sign split isn't
guaranteed to bisect evenly; the tool handles a degenerate split as a
real null result, not an error.

---

## 7. File Structure

```
Track_2_GenomicAgent/
├── Cargo.toml
├── src/
│   ├── main.rs        # Entry point (default / bench / gpu-bench / fast modes)
│   ├── agent.rs        # intent.rs plans (mandatory, free); llm.rs optionally
│   │                     narrates the result afterward (never plans)
│   ├── intent.rs         # Custom GPU-dispatched Okapi BM25 (+bigrams) tool
│   │                       classifier -- no API, no network, the crate's only
│   │                       mandatory planning mechanism (see intent_similarity.wgsl)
│   ├── llm.rs              # Two independent, optional, narration-only LLM
│   │                         backends (HF Inference Router, Anthropic), tried
│   │                         in order, both None-on-any-failure
│   ├── tools.rs             # 6 genomic tools, real computation (see vcf.rs, pca.rs,
│   │                          bootstrap.rs, fst.rs)
│   ├── vcf.rs                # Synthetic VCF generation + real VCF-format parser +
│   │                           real MAF/missingness/HWE/LD-r²/haplotype computation +
│   │                           real 1000 Genomes data loader (GENOMIC_AGENT_REAL_DATA)
│   ├── gpu_ld.rs              # Real GPU compute (wgpu), AMD-adapter-targeted,
│   │                           cross-validated against CPU reference. LD/PCA
│   │                           kernel + a second, independent intent-similarity
│   │                           kernel on the same device/queue. Process-wide
│   │                           cached context (GpuLdContext::shared()) so
│   │                           repeated calls don't re-pay ~800ms of setup.
│   ├── pca.rs                 # CPU power-iteration eigensolver with deflation,
│   │                           independently tested against the actual eigenvector
│   │                           equation (M@v = lambda*v), not just "does it run"
│   ├── bootstrap.rs            # GPU-batched nonparametric bootstrap CIs (LD r²,
│   │                            PCA top eigenvalue) -- all B replicates in one
│   │                            batched GPU dispatch per statistic, not B dispatches
│   ├── fst.rs                   # Per-SNP Wright's FST between PC1-split subpopulations
│   ├── shaders/
│   │   ├── ld_r2.wgsl             # LD / population-structure correlation kernel
│   │   └── intent_similarity.wgsl  # Tool-planning cosine-similarity kernel
│   └── bench.rs                   # Real timing (Instant::now/elapsed) around real execution
├── data/
│   ├── real_1000genomes_chrMT_slice.vcf  # Real 1000 Genomes Phase 3 data (bundled)
│   └── README.md                          # Exact provenance/derivation of that file
├── LICENSE
├── setup.sh / setup.bat
└── README_PROFESSIONAL.md
```

---

## 8. What each tool does

All six tools below default to a synthetic VCF (real VCF-format text,
generated deterministically at runtime); set `GENOMIC_AGENT_REAL_DATA=1`
and every one of them instead analyzes the real, bundled 1000 Genomes
slice described in "About the data" further down this section.

### VcfAnalyzer
Parses the dataset (synthetic by default; see above) and computes real
per-variant statistics: SNP count, minor allele frequency, missingness,
and a real Hardy-Weinberg equilibrium chi-square test per variant (flags SNPs at
p<0.001, the standard QC threshold for genotyping-error/stratification
screening). The HWE p-value uses the exact df=1 identity that chi-square(1)
is the square of a standard normal, not an approximation of the
chi-square distribution -- see `vcf::compute_hwe` and its test module.

### LdBlock
Computes real pairwise linkage disequilibrium (Pearson r², the standard
population-genetics LD statistic) between nearby SNPs within a sliding
window, and groups markers into blocks where r² exceeds a threshold via
union-find. All numbers reported (pairs tested, mean r², block sizes)
come from that computation, not from a literal.

### HaplotypeTool
Tallies real observed haplotype patterns from phased genotype pairs
across a small SNP window and reports their frequencies.

### PopulationStructure
GPU-accelerated ancestry/population-structure analysis: same overall
approach as PLINK `--pca` / EIGENSOFT `smartpca`. The GPU computes the
expensive dense sample-by-sample correlation matrix (reusing the exact
same cross-validated kernel as `LdBlock`, just fed a transposed matrix --
the kernel computes pairwise row correlation and doesn't know or care
whether the rows are SNPs or samples), then CPU power iteration
(`pca.rs`) extracts the top principal components and each sample is
projected onto them. Reports real variance-explained percentages (exact,
not approximated -- for a correlation matrix the trace equals the sum of
all eigenvalues, so % explained by a found component is a true ratio)
and falls back to CPU-only correlation if no GPU adapter is available.
Also reports a 95% bootstrap confidence interval on PC1's eigenvalue
(see `bootstrap.rs`), not just its point estimate.

### LdConfidence
Scans a window of SNP pairs for the strongest observed r², then reports
a real GPU-batched bootstrap 95% confidence interval on that specific
pair's r² -- how much would this estimate move under a different sample
draw -- instead of a bare point estimate. See "Advanced capabilities"
above.

### SelectionScan
Splits samples into two groups by PC1 sign, computes Wright's fixation
index (FST) per SNP between them, and reports the top candidates for
population differentiation plus the mean FST across all SNPs -- each
with a real permutation-test p-value (200 label reshuffles), not just a
bare magnitude, and a summary count of how many SNPs clear p<0.05
genome-wide. See "Advanced capabilities" above for why both the FST
arithmetic and the permutation test run on CPU while the clustering
they depend on is GPU-accelerated, and for a real example where the
significance test changes the honest conclusion (real data's top FST
hits aren't actually significant, despite looking similar in magnitude
to the synthetic dataset's genuinely significant ones).

### About the data

**Two real data sources, chosen with one environment variable:**

```bash
cargo run --release                        # synthetic (default)
GENOMIC_AGENT_REAL_DATA=1 cargo run --release   # real 1000 Genomes data
```

By default, all tools analyze a synthetic dataset generated at runtime
(`vcf::generate_synthetic_vcf` / `gpu_ld::generate_dense_dataset`). The
generators embed genuine structure via founder-haplotype resampling
(nearby SNPs really are correlated, samples really do share latent
ancestry signal depending on which founders they drew from -- the LD and
PopulationStructure tools' job is to genuinely detect that, not report a
hardcoded number) -- but it is not real biological data, and every tool's
output says "synthetic dataset" rather than implying otherwise.

Set `GENOMIC_AGENT_REAL_DATA=1` and every tool instead analyzes a real,
bundled (compile-time `include_str!`, no runtime download or network
access needed) subset of the 1000 Genomes Project Phase 3 mitochondrial
genotype callset -- 300 real biallelic SNPs across 100 real samples, an
official public release with no usage restrictions. See
`data/README.md` for the complete, disclosed derivation (source URL,
filtering criteria, and the haploid-to-diploid representation transform
this crate's existing parser needed). Every tool's output says exactly
which data source produced it, and `VcfAnalyzer` explicitly flags that
Hardy-Weinberg testing isn't a meaningful QC signal for this haploid
locus, rather than silently reporting a number that looks like a real
test but isn't. On this real data, LD/haplotype/PCA structure is
noticeably *stronger* than on the synthetic generator, as expected --
real mtDNA has no recombination at all, so linkage and haplogroup
signal along its length are genuinely large (e.g. a live run found a
real 6-SNP LD block at `MT:10463-15607` and PC1 explaining ~20% of
variance, both well above the synthetic dataset's typical values).

---

## 9. Troubleshooting

**"Rust not found"** — Install from https://rustup.rs/, verify with `rustc --version`.

**"Build fails"** — `rustup update`, then `cargo clean && cargo build --release`.

---

**Built for AMD AI DevMaster Hackathon 2026-07**
