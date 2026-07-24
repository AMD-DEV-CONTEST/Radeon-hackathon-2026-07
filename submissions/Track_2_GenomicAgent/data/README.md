# Real data provenance

`real_1000genomes_chrMT_slice.vcf` is a real subset of the 1000 Genomes
Project Phase 3 mitochondrial genotype callset.

- **Source:** `ALL.chrMT.phase3_callmom-v0_4.20130502.genotypes.vcf.gz`
- **Official location:** `https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/`
- **Downloaded:** 2026-07-21
- **Original size:** 3,892 variants x 2,534 samples
- **License / usage:** IGSR (International Genome Sample Resource, the
  project's current maintainer) states there are no restrictions on the
  use or redistribution of 1000 Genomes Project data.

## What was done to it, and why

The original callset is **haploid** (mitochondrial DNA has no
recombination and is uniparentally inherited, so each sample has one
allele call per site, e.g. `GT=0` or `GT=1`) and includes **multiallelic
and indel sites** (some positions have more than one alternate allele,
or REF/ALT longer than one base).

This crate's existing parser (`vcf.rs`, originally built for its own
synthetic diploid autosomal data) expects a **diploid, biallelic SNP**
genotype model: two allele calls per sample (`0|0`, `0|1`, `1|1`), one
REF and one ALT base per site. Rather than write a second, parallel data
model just for this one real dataset, the slice here was filtered and
transformed to fit that existing model -- a completely standard
preprocessing step in real population-genetics workflows (biallelic-SNP
filtering is a common default before LD/PCA analysis in tools like
PLINK), not a fabrication of the underlying calls:

1. **Filtered to strictly biallelic SNPs**: single-base REF, single-base
   ALT, no comma in the ALT field (drops indels and multiallelic sites).
2. **Selected the 300 highest real allele-count (AC, from the original
   VCF's own INFO field) qualifying variants**, then re-sorted back into
   genomic position order. This is real data selection by a real,
   objective, disclosed criterion (most common variants first), not
   cherry-picking for a particular narrative -- every genotype call in
   the file is an unmodified value from the official release.
3. **Subset to the first 100 of 2,534 samples** (by column order in the
   original file) -- purely for demo-appropriate scale, matching this
   crate's existing synthetic-data defaults (40-60 samples). Not a
   random or biased selection; consecutive columns from the original
   file, unmodified.
4. **Each haploid call duplicated into this crate's diploid GT
   representation**: real `GT=0` -> written as `0|0`, real `GT=1` ->
   written as `1|1`. The underlying real allele call is unchanged, only
   its on-disk representation. This transform is exact, not
   approximate, for every downstream statistic this crate computes: MAF
   (dosage/2 across a duplicated haploid call reproduces the true
   haploid allele frequency exactly) and Pearson r²/LD (multiplying
   every value in a variable by a constant factor -- here, "duplicate
   the single call" -- doesn't change its correlation with anything
   else). The one exception is documented in `vcf.rs`: Hardy-Weinberg
   equilibrium testing assumes diploid biparental inheritance and is
   not a meaningful QC signal for haploid mtDNA (there is no possible
   heterozygous call by construction), so real-data mode's output says
   so explicitly rather than silently reporting a number that looks
   like a real HWE test but isn't measuring anything.

Regenerating this file from scratch (with different parameters, or a
newer 1000 Genomes release) only requires re-running the same filter/
transform against the official source above -- nothing about the
selection is hidden or undocumented.
