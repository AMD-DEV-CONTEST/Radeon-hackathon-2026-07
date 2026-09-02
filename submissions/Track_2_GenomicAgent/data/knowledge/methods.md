# Population-genetics method notes

Local knowledge base for the Genomic Research Agent. Each `##` section
below is indexed and retrieved as a single passage. These are concise
method references for the statistics this agent actually computes, so a
user can ask "what does FST mean" or "why would Hardy-Weinberg fail"
and get a grounded answer from local text rather than a model's
recollection.

## Hardy-Weinberg equilibrium (HWE)

Hardy-Weinberg equilibrium describes the expected genotype frequencies
in a large, randomly-mating population with no selection, mutation, or
migration. For a biallelic SNP with allele frequencies p and q = 1 - p,
the expected genotype counts are p^2 for homozygous reference, 2pq for
heterozygous, and q^2 for homozygous alternate.

A chi-square goodness-of-fit test with one degree of freedom compares
observed genotype counts to those expectations. A strong deviation
(commonly p < 0.001 as a quality-control threshold) usually indicates a
genotyping or assay problem rather than real biology: allele dropout,
probe failure, or a variant that is actually multiallelic. It can also
indicate population stratification, where samples come from several
distinct groups rather than one randomly-mating population. HWE testing
is only meaningful for diploid biparental loci; it is not a meaningful
signal for haploid mitochondrial DNA, because no heterozygous call is
possible by construction.

## Linkage disequilibrium (LD) and r squared

Linkage disequilibrium is the non-random association of alleles at
different loci. Two SNPs are in LD when knowing the genotype at one
gives you information about the genotype at the other, typically
because they sit close together on a chromosome and are inherited
together.

The standard measure used here is the squared Pearson correlation
coefficient, r squared, computed between the allele-dosage vectors of
two SNPs across samples. It ranges from 0 (independent) to 1 (perfectly
correlated, meaning one SNP is a perfect proxy for the other). LD decays
with physical distance because recombination breaks up associations
over generations. Mitochondrial DNA does not recombine at all, so
mtDNA shows unusually strong and long-range LD compared with autosomes.

## LD blocks and union-find grouping

An LD block is a run of markers that are all in high mutual linkage
disequilibrium, and therefore tend to be inherited as a unit. Blocks
matter because markers inside one block carry largely redundant
information: for association studies you can often genotype a single
tag SNP per block instead of all of them.

This agent detects blocks by computing pairwise r squared within a
sliding window and then grouping any pair whose r squared exceeds a
threshold using a union-find (disjoint-set) structure. Union-find is
used because block membership is transitive in this construction: if A
groups with B and B groups with C, all three belong to one block.

## Haplotypes

A haplotype is a specific combination of alleles observed together on a
single chromosome copy, inherited as a unit. Where a genotype tells you
which alleles a sample carries, a haplotype tells you how those alleles
are arranged across the two inherited copies.

Tallying observed haplotype patterns across a small window of SNPs
shows which combinations actually occur and at what frequency. In a
region with strong linkage disequilibrium, only a handful of distinct
haplotypes usually account for most of the samples, because
recombination has not had the opportunity to shuffle them apart.

## Principal component analysis for population structure

Principal component analysis on genotype data reveals population
structure: the top principal components typically separate samples by
ancestry, because allele frequencies differ systematically between
ancestral populations. This is the same approach used by standard tools
such as PLINK's --pca and EIGENSOFT's smartpca.

The procedure here builds a dense sample-by-sample correlation matrix
(the expensive step, dispatched to the GPU) and then extracts leading
eigenvectors with CPU power iteration plus deflation. Each sample is
projected onto those components. The variance explained by a component
is its eigenvalue divided by the trace of the correlation matrix, which
is exact for a correlation matrix rather than an approximation.
Correcting for population structure matters because uncorrected
stratification is a classic source of false-positive association
results.

## Wright's fixation index (FST)

Wright's fixation index, FST, measures genetic differentiation between
subpopulations. It is the proportion of total genetic variance that is
attributable to differences between groups rather than variation within
them. FST ranges from 0, meaning the groups are indistinguishable at
that locus, to 1, meaning the groups are fixed for different alleles.

A high per-SNP FST identifies loci that differ sharply between
populations, which can indicate local adaptation or selection. However,
a raw FST value alone does not establish significance: in any scan over
many markers, some loci will show high differentiation by chance alone.

## Permutation testing for significance

A permutation test builds an empirical null distribution by repeatedly
shuffling the group labels and recomputing the statistic under each
random relabeling. The p-value is the fraction of permutations whose
statistic meets or exceeds the real observed value.

This matters for selection scans because it separates real signal from
the strongest of many noisy candidates. Permutation testing makes no
distributional assumption, which is why it is preferred here over a
parametric approximation. Statistical power depends heavily on sample
size: with few samples, even a genuinely differentiated locus may not
reach significance, and reporting that honestly is the correct outcome
rather than a defect.

## Bootstrap confidence intervals

A nonparametric bootstrap estimates the uncertainty of a statistic by
resampling the observed data with replacement many times and
recomputing the statistic on each resample. The percentile method takes
the 2.5th and 97.5th percentiles of those replicate values as a 95%
confidence interval.

The value of a confidence interval is that it answers a question a bare
point estimate cannot: how much would this number move under a
different sample draw? A wide interval signals that an estimate is not
well determined by the available data. When there is no true sampling
variability, for example two perfectly identical genotype rows, the
interval correctly collapses to a single point.

## Minor allele frequency and missingness

The minor allele frequency is the frequency of the less common of the
two alleles at a biallelic site, and by definition never exceeds 0.5.
Very low-frequency variants carry little statistical power in
association analysis and are often filtered before downstream work.

Missingness is the fraction of samples with no genotype call at a site.
High missingness usually indicates a technical failure at that site,
and sites exceeding a missingness threshold are typically dropped
during quality control. Missing calls must be represented distinctly
rather than silently treated as reference homozygotes, since conflating
the two biases allele-frequency estimates.

## VCF format

VCF, the Variant Call Format, is the standard text format for storing
genetic variants. Header lines begin with ##, a single column-header
line begins with #CHROM, and each subsequent line describes one variant
site.

The fixed columns give chromosome, position, identifier, reference
allele, alternate allele, quality, filter status, and an INFO field,
followed by a FORMAT specification and then one column per sample. The
genotype field encodes which alleles a sample carries: 0 refers to the
reference allele and 1 to the first alternate, so 0/0 is homozygous
reference, 0/1 heterozygous, and 1/1 homozygous alternate. A vertical
bar instead of a slash, as in 0|1, indicates the genotype is phased,
meaning the arrangement across chromosome copies is known.
