# Multi-Objective Alignment Execution Contract V1

This contract implements the non-runtime mechanics for canonical TODO
0751–0800 while leaving every unobserved RL result open.

## Reuse and falsifiable research boundary

The four training arms remain non-interchangeable: ORPO supplies a
reference-free preference-aligned SFT control, SimPO supplies a
length-normalized margin control, MDPO supplies the multimodal conditional
preference arm, and a bounded micro-GRPO arm tests group-relative online
optimization. TextGrad informs the conversion of visible, located critique
into executable repair feedback. These sources are design inputs; none of
their reported gains are claimed reproduced.

## Executable mechanisms

- The reward vector contains exactly thirteen independently located
  dimensions: evidence, strategy, creative, copy, identity, brand, OCR,
  temporal, channel, safety, efficiency, diversity and stop.
- Safety, evidence, identity and correct stopping are hard lexicographic
  floors. Unsafe candidates are rejected before Pareto comparison. Scalar
  flattening is prohibited, so creative strength cannot buy back a safety or
  evidence failure.
- Frozen per-dimension bounds perform normalization; monotonic held-out
  calibration curves map raw values to calibrated probabilities.
- Audit findings, tool errors and approved human critiques become typed,
  locator-bearing repair tokens. Hidden reasoning is neither required nor
  persisted.
- Five independent monitors detect reward hacking, length hacking, invalid
  tool-call gain, judge gaming and visual-metric gaming.
- Adversarial, held-out and human spot-check verifiers use distinct datasets,
  require independent observed receipts and must all pass. Human review covers
  at least five percent of rollouts.
- Each method has an exact two-hour hard budget. Missing artifacts, any
  monitor failure or any measured regression makes promotion ineligible.

## Truth boundary

The planned card leaves policy, trajectory, visual and calibration gains,
inference cost, rollouts, reward traces, verifier traces, reports and selected
adapter as `null`.

TODO 0774–0775, 0789–0793 and 0795–0800 remain open until rights-approved
rollouts, real Radeon training, verifier/human observations, measured gains,
negative experiments, reports and a selected Alignment Adapter exist.

