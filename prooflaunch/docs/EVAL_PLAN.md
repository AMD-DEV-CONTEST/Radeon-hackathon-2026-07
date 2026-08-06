# Eval Plan: ProofLaunch Evidence-Grounded Campaign Studio

## 1. What we are measuring

The system turns a source product image and source specification into a
platform-ready creative pack. A good run preserves the product, uses only
verbatim approved claims, obeys layout constraints, repairs bounded failures,
and exports an inspectable pack. A bad run silently publishes drift, invented
claims, unreadable copy, unsafe layout, or unverifiable files.

## 2. Eval dataset

The smoke dataset contains 250 synthetic orchestration cases, 50 for each of
five named failure modes. It is generated with fixed seeds and explicitly does
not represent human preference or model quality. The Radeon visual set is
precommitted at 30 permitted products × three aspect ratios × five seeds.
Human labels and real operator traces are currently absent and are a release
blocker, not a score to estimate.

Named failure modes:

1. happy path fails to deliver;
2. empty evidence silently passes;
3. missing product silently passes;
4. injected unapproved claim reaches creation;
5. persistent critic failure escapes the two-repair budget.

## 3. Metrics and rubric

Level 1 code assertions run on every change: media signature/type validation,
rights and dedupe, immutable mission graph/resume, schema/state validity, exact claim
spans, protected source/layer hashes, opaque-product pixel mismatch, WCAG
contrast, text fit, safe-zone intersections, repair budget, ledger hash chain,
file existence, archive readability, deterministic-seed image hash, exact
pre-encode video identity pixels, decoded-video identity error and coverage,
timestamped A/V event alignment, GroundingDINO/SAM2 contracts, local model
routing, LoRA tower isolation, Wilson confidence derivation, and fail-closed
semantic findings.

Subjective image quality uses four binary human questions defined in
`COMPETITIVE_BENCHMARK_PROTOCOL.md`. No LLM judge is a release signal until it
is calibrated on at least 100 human-labelled examples with both TPR and TNR
above 80%.

## 4. Baselines

- same local visual model and seed with audit/repair disabled;
- previous tagged ProofLaunch release;
- dated, configured CapCut and LTX matched-task runs.

## 5. Ship bar

The local control-plane gate includes all 76 unit/integration tests plus exactly
250/250 expected orchestration outcomes with zero
silent release. The Radeon visual gate is ≥95% pass across four mechanical
checks plus the SigLIP2 semantic gate within two repairs, zero unsupported
claims, and 100% protected-layer hash retention. Encoded video additionally
needs ≥95% decoded-frame identity and A/V alignment passes. The safe Gemma adapter must
also retain ≥75% on the four frozen visual fixtures and lose no more than five
percentage points versus its pre-fine-tuning result. Any miss blocks release.

## 6. Regression gate

Unit and Level 1 integration tests run on every change. The 250-case synthetic
suite runs before packaging and on Radeon after upload. The 30-product visual
suite runs on model, prompt, compositor, or ROCm dependency changes. A new
failure becomes a permanent case. A score drop is not averaged away and must
be fixed or explicitly documented before release.
