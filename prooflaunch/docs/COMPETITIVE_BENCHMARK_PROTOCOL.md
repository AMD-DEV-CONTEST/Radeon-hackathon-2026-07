# Competitive Benchmark Protocol

## Decision

ProofLaunch must not claim it is “better than CapCut” or “better than LTX”
without matched-task evidence. The release gate is a reproducible, blinded
comparison, not a feature-count table.

## Frozen task

Each candidate receives the same product PNG, source specification, target
market, platform, aspect ratio, and prompt budget. The candidate must produce
one ready-to-review launch asset. No candidate receives hidden manual cleanup.
The evaluator records every manual intervention.

## Candidates

1. ProofLaunch competition-2X with the local Radeon generation adapters,
   mechanical gates, SigLIP2, GroundingDINO→SAM2, decoded-video identity,
   CLAP, A/V alignment, and cross-media gates.
2. ProofLaunch one-shot ablation: same generator and seed, audits and repair off.
3. CapCut workflow available on the test date.
4. LTX workflow available on the test date.

Product/version, date, paid tier, settings, seed availability, and export
settings must be recorded. If a product does not expose a seed, that limitation
is reported rather than normalized away.

## Dataset

- 30 frozen products that the team has permission to use.
- Three aspect ratios: 9:16, 4:5, and 1:1.
- Five seeds per product for systems that expose seeds.
- At least six hard cases: transparent edges, reflective surfaces, dense
  specifications, long brand names, low-contrast products, and right-to-left
  copy.
- Inputs are split before testing; prompt writers cannot see preference labels.

## Mechanical gates

- Unsupported-claim release rate: required target **0%**.
- Source product SHA-256 retention: ProofLaunch protected layer target **100%**.
- Cross-media and encoded-delivery pass within two repairs: target **≥95%**.
- Pre-encode exact identity: **100%**; decoded identity: **≥95%** at the
  precommitted normalized-MAE tolerance.
- Timestamped A/V semantic-event alignment: **≥95%**.
- Completion rate, crash rate, p50/p95 wall time, and peak VRAM.
- Diversity: 90 product/ratio groups × five seeds. A group passes when every
  output retains product identity and median pairwise 64-bit perceptual-hash
  distance is within the precommitted `[0.08, 0.45]` interval. The release bar
  is ≥95% passing groups, so copying a seed and identity-destroying drift both
  fail.

## Human evaluation

At least five raters view randomized, brand-masked pairs. They answer binary
questions separately:

1. Is every visible factual claim supported by the supplied source?
2. Is the supplied product visually preserved?
3. Is the output immediately usable on the target platform?
4. Which output would you choose to publish?

Raters may choose “tie / neither.” Candidate A/B order is randomized and bound
to artifact SHA-256 values; system labels are resolved only during compilation.
Every counted rater covers all 30 products. Report counts, Wilson 95%
confidence intervals, disagreements, and exclusions. Do not collapse the four
questions into one uncalibrated “quality score.”

## Ship bar

ProofLaunch ships a superiority statement only if it has:

- zero unsupported claims;
- ≥95% five-gate pass within two repairs;
- 100% protected product-layer hash retention;
- ≥60% publish preference against the named baseline, with the lower bound of
  the 95% confidence interval above 50%; and
- no worse completion rate than the baseline.

Until those bars are met, public language is limited to architecture and
measured results. “Designed to outperform” is allowed; “outperforms” is not.

The V7 compiler enforces the same 450 case IDs for ProofLaunch and the
baseline. Missing rows, duplicate rows, manifest-hash mismatches, unblinded
human rows, and candidate hashes not present in the paired outputs are hard
errors rather than failed-but-averaged-away samples.

## Truth boundary

Local deterministic compositor results do not count as Radeon generative-model
quality evidence. Screenshots do not count as latency evidence. An unblinded
team review does not count as a market or human-preference study.
