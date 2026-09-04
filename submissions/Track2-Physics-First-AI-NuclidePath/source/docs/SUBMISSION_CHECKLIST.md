# Submission readiness checklist

**Track:** AMD AI DevMaster Hackathon 2026, Track 2  
**Team:** Physics-First AI  
**Application:** NuclidePath  
**Required PR title:** `Track 2, Physics-First AI, NuclidePath`  
**Deadline:** 6 August 2026, 17:59 CEST  
**Last synchronized:** 6 August 2026
**Current `main` review head:** fetch `main` directly; this checklist intentionally does not pin documentation-only merge commits.

This checklist distinguishes verified repository evidence from actions that
require the participant's explicit publication or eligibility decision.

## Official eligibility — human-gated

- [ ] Participant registered and approved on Luma.
- [ ] AMD Developer Program membership active.
- [ ] Valid Discord and GitHub identities supplied.
- [ ] Legal-name/contact and eligibility requirements confirmed.

## Track 2 implementation — repository evidence

- [x] Core local inference runs on AMD Radeon + ROCm.
- [x] No remote API is required for core inference.
- [x] Scenario-based task execution.
- [x] Tool invocation and orchestration.
- [x] Local knowledge retrieval.
- [x] Multi-step task planning with deterministic fallback.
- [x] Local multi-turn memory with redaction and deletion.
- [x] Permission/privacy controls and denied operational actions.
- [x] Five of five listed capabilities exercised end to end.

## Current source and scientific scope

- [x] `main` contains the merged Phase F bounded PHREEQC path.
- [x] `main` contains the schema-2 multicomponent compiler, dynamic parser,
      per-ion diagnostics and report bridge.
- [x] K-free Central Oklahoma Na-Ca-Mg fixtures are present with provenance.
- [x] Canonical `transport-prototype-0.3` path remains authoritative.
- [x] Global PHREEQC status remains `PROCESS-QUALIFIED ONLY`.
- [x] Preceding merged-bridge integration gate: PR #15 run
      `30928408962`, 364 passed/15 skipped, policy/wheel/whitespace PASS.
- [x] Calibration/hold-out integration: PR #22 run
      `30936374478`, 370 passed/15 skipped, policy/wheel/whitespace PASS.
- [x] Latest code-bearing registry integration: PR #24 run
      `30993946602`, 373 passed/15 skipped, policy/wheel/whitespace PASS.
- [x] Current `main` head `df8f028` after review-hardening commits `3714bf8`/`1605cc6`:
      run `31111109865`, 377 passed/15 skipped, policy/wheel/editorial/whitespace PASS.
- [x] Official PHREEQC Example 2 process qualification is recorded.
- [ ] Trusted real PHREEQC projection of both multicomponent cases on `main`.
- [x] Independent arithmetic oracle for the declared bridge contract is
      present in `main`.
- [x] Offline multi-cation calibration/hold-out contract is implemented in
      `main` and emits machine-readable evidence; no experimental data or
      promotion claim is bundled.
- [ ] Calibrated multi-cation Cs parameterization and experimental agreement.

## Specification and source deliverables

- [x] English README, specification, architecture and limitations.
- [x] Complete private source tree, tests, scenarios and bundled knowledge.
- [x] Install/startup/dependency/offline/LLM/dashboard instructions.
- [x] MIT license and no-secrets policy.
- [x] Specification PDF at
      `submission/NuclidePath_Project_Specification.pdf`.
- [x] Deck at `submission/NuclidePath_Track2_Deck.pptx`.
- [x] Internal artifact manifest at `submission/ARTIFACT_MANIFEST.json`.
- [x] PDF/deck visual QA evidence retained for the core Track 2 package.
- [x] Regenerate/sync the public contest copy from the selected current source
      snapshot.

## AMD and demo evidence

- [x] AMD core-platform snapshot (28 July): 231 tests, exact FP64 parity and recorded
      ROCm/model/source hashes.
- [x] Post-merge AMD/ROCm rerun of `main` at head `b6d4c61e74` (5 August): 388 passed,
      2 skipped (external-PHREEQC only), FP64 benchmark reproduced; evidence under
      `artifacts/amd-2026-08-05/post-merge/`.
- [x] Dependency-light controller checkpoint: 216 passed/13 optional-PyTorch
      skips; PyTorch controller checkpoint: 231 passed.
- [x] Current core video master: 4:36, 1920×1080, 30 fps, H.264/AAC with
      embedded English subtitles.
- [x] Video script explicitly separates recorded core path from current
      PHREEQC source extension.
- [x] Judge-accessible public video URL inserted and verified:
      `https://drive.google.com/file/d/19fHhF9CXuQyX2jn6m9DFrUuHR6EyQD-1/view?usp=drivesdk`
      (SHA-256 `47dc62f419c778d19af5724314a5d3bf3e04c3ee2175349897393162977c0d80`).
- [ ] Re-record video only if the PHREEQC bridge is intended to be part of the
      visual claim; it is not required for the current core-path evidence.

## Repository and publication state

- [x] Private source repository verified: `anakinsuper/NuclidePath`.
- [x] Public contest fork and prepared branch exist; contest artifacts are under
      `submissions/Track2-Physics-First-AI-NuclidePath/`.
- [x] Prepared contest branch synchronized with current `main` documentation head
      `df8f028` (verified byte-identical on 6 August 2026; re-sync required after any further `main` change);
      its contest-local manifest is `nuclidepath-contest-manifest-2.0`.
- [x] Complete current source copied to the contest submission under
      `submissions/Track2-Physics-First-AI-NuclidePath/source/`.
- [ ] Official contest PR opened with the exact title.
- [ ] Official PR checks and final public links reviewed.

## Blocking inputs

Only these decisions/actions remain outside the repository checks:

1. eligibility confirmation;
2. judge-accessible video hosting URL;
3. whether to publish/copy the complete current source;
4. authorization to synchronize the public contest package and open the official PR.
