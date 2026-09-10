# Blinded Rater Protocol

## Common Procedure

1. Show randomized sample IDs only. Hide metric scores, thresholds, split names,
   seeds, model settings, and other raters' decisions.
2. Each rater records one binary label plus a short reason. No ties or silent
   omissions are allowed; unusable media is escalated, not labeled positive.
3. An adjudicator resolves disagreements using the same claim definition and
   records the final annotation-record hash.
4. Raters must not compare calibration, validation, and test material or infer
   related source/reference families.

## L2 Item: Reference-Style Fidelity

Positive means the candidate visibly follows the reference's palette,
contrast, material treatment, lighting character and graphic rhythm sufficiently
for the frozen style pack. Judge style fidelity, not source identity. Do not
assume Gram/statistical similarity is independent of content.

Negative means the candidate materially misses or contradicts that style. Mark
unreadable, corrupted, or ambiguous evidence unusable for approval.

## L2 Batch: Cohort Consistency

Show the complete ordered four-image cohort at once. Positive means the set
forms one coherent style system without a material outlier. The label belongs
to the complete cohort; never drop a failed member and rescore survivors.

Negative means at least one member breaks the frozen style system or the cohort
cannot be assessed as a complete set. Member order and membership are immutable.

## L3 Item: Structure Fidelity

Show the source and candidate side by side. Positive means the major spatial
layout, silhouette boundaries and edge structure needed by the frozen
`structure_only` domain are preserved.

This judgment does not establish face identity, person identity, brand/SKU
identity, or product-instance identity. A ControlNet-conditioned output is not
automatically positive.
