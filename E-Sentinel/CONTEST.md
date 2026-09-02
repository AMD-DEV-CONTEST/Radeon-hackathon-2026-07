# E-Sentinel Contest Showcase

## One-line identity

E-Sentinel is an AI quality auditor that explains decisions, admits uncertainty,
and turns human corrections into governed improvements.

## Three-minute story

1. Obvious abuse makes the value immediately legible.
2. An implicit overpromise demonstrates why keyword-only rules miss semantic risk.
3. A keyword/full-system comparison makes the AI contribution inspectable.
4. A privacy leak demonstrates safety enforcement.
5. A normal reply demonstrates that the system does not over-block.
6. Insufficient context demonstrates that uncertainty is sent to a human.

## Evidence boundary

The repository currently contains a 15-case deterministic fixture dataset and a
10-case deterministic red-team smoke set. These are not a human-labelled Gold
Set and must not be presented as one. A release candidate needs 100–150
independently labelled cases, plus a catastrophic-risk set of at least 200 when
the natural prevalence is below 10%.

For each labelling batch, limit one annotator to 20 cases, record independent
labels and disagreement, include a batch identifier, report Cohen's kappa and
Wilson confidence intervals recomputed from the per-case annotation rows, and
checksum both cases and annotations. Keep the frozen set out of Few-shot prompts. Boundary cases should
retain disaggregated disagreement instead of forcing false consensus.

## Public URL and licence

- Licence: **MIT License** (see `LICENSE`). Source is public for the AMD AI
  DevMaster Hackathon Track 2 submission.

## Known limitations

- Fixture evaluation is not production LLM accuracy evidence.
- Playwright requires a browser binary; k6 and the pinned Promptfoo CLI require
  their own CI installations. The exact Promptfoo CLI is locally verified at
  15/15 with a non-empty artifact; a separate Ubuntu CI artifact is still a
  release preflight item.
