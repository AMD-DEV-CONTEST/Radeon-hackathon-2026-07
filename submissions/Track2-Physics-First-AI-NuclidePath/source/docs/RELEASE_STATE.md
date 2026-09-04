# NuclidePath current release state

- **Updated:** 6 August 2026
- **Repository:** `anakinsuper/NuclidePath`
- **Default branch:** `main`
- **Latest code-bearing `main` checkpoint:** review-hardening commit `1605cc6` (atomic memory rewrite, free-text secret redaction, editorial CI gate), preceded by review-hardening commit `3714bf8` (oracle row binding, report numeric-finiteness gate, calibration promotion-gate tightening). Both landed directly on `main` on 6 August 2026 and are covered by GitHub-hosted CI runs `31098025767` and `31093247490`; the current `main` head `df8f028` passed run `31111109865` with `377 passed, 15 skipped`.
- **Preceding code-bearing checkpoint:** PR #24 registry merge `2b256e322eaa8ca45a5b939fdecad09d66019b0c` (PR head `58656141db4a3a17d49a7e0a2f9ffda20f434130`); the post-merge AMD/ROCm evidence commit `c05d13afbf` is documentation/evidence only and does not change the reviewed code path.
- **Documentation-only synchronization follows the last code-bearing checkpoint; fetch `main` directly for the current documentation HEAD.**
- **Artifact-generation source checkpoint:** `a94c76ee078a7bd24feb98965a6682a274781deb` (PR #10 documentation sync)

This file is the compact cross-document release record. `WORK_HANDOFF.md`
contains operational continuity; this file records which claims are current,
which evidence belongs to an earlier checkpoint, and which submission actions
remain human-gated.

## Source state

The verified `main` state contains:

- the Phase F bounded PHREEQC execution and replay contract;
- the opt-in PHREEQC scenario compiler and report bridge;
- schema `nuclidepath-phreeqc-chemistry-2`;
- declared `Cs` plus any non-empty subset of `K`, `Na`, `Ca`, and `Mg`;
- dynamic selected-output parsing and per-ion chemistry diagnostics;
- the independent PHREEQC arithmetic oracle and deterministic replay canonicalization;
- the paired K-free Central Oklahoma brine and recharge fixtures;
- the unchanged canonical `transport-prototype-0.3` empirical K+ screening path;
- the dependency-free traceable Cs exchange calibration/hold-out gate, implemented
  offline with fail-closed promotion and no bundled experimental data.

The latest code-validation checkpoint is the current `main` head `df8f028`, whose
GitHub-hosted CI run [31111109865](https://github.com/anakinsuper/NuclidePath/actions/runs/31111109865)
passed with `377 passed, 15 skipped`, workflow policy PASS, Python compilation PASS,
wheel PASS, editorial toolchain PASS and whitespace PASS. It covers the two
review-hardening commits `3714bf8` (376 passed) and `1605cc6` (377 passed).

The preceding code-validation checkpoint is PR #22 head
`f74943ed12b07080578536e3d8deb0f3831ad310`, merged as
`7c4079ad84812164a4bfd3f4f7b8f24c6708f41b`. Its GitHub-hosted calibration-gate
CI run [30936374478](https://github.com/anakinsuper/NuclidePath/actions/runs/30936374478)
passed with `370 passed, 15 skipped`, workflow policy PASS, Python compilation
PASS, wheel PASS and whitespace PASS. The preceding PHREEQC bridge checkpoint
is PR #15 merge commit `96f31c0e21501cab582ed5600acf2de9f08a5189`, whose final
integration run [30928408962](https://github.com/anakinsuper/NuclidePath/actions/runs/30928408962)
passed with `364 passed, 15 skipped`. PR #14's prerequisite hardening was
validated by run [30895641771](https://github.com/anakinsuper/NuclidePath/actions/runs/30895641771).
These are GitHub-hosted CI checkpoints, not a trusted self-hosted PHREEQC or
AMD post-merge rerun.

## Scientific hierarchy

| Layer | Current status | Permitted claim |
|---|---|---|
| Canonical transport | Implemented | Deterministic 1-D reactive Ogata–Banks screening with empirical K+ competition |
| Primary Cs GCS / multispecies | Implemented opt-in contracts | Reproducible software and analytical evidence within declared domains |
| PHREEQC Example 2 | Process-qualified | Hash-pinned, bounded, repeatable external execution and replay integrity |
| PHREEQC multicomponent bridge | Implemented and CI-tested | Explicit compile/report/replay path for declared chemistry |
| PHREEQC arithmetic contract | Numerically verified on the declared bridge | Independent checks for units, grid mapping, non-negativity and exchange-site occupancy |
| Cs exchange calibration gate | Implemented offline, not promoted | Traceable dataset contract, group-disjoint hold-out and fail-closed promotion; no data bundled |
| PHREEQC multicomponent real run | Pinned local process/integration evidence; trusted workflow pending | Both cases passed locally with 40 shifts/41 rows, parser, oracle and replay; trusted `refs/heads/main` qualification remains separate |
| Cs chemistry calibration | Not complete | No calibrated multi-cation Kd hierarchy or scientific-result qualification |
| Regulatory/site validation | Not performed | No dose, safety, operational or site-specific conclusion |

The global PHREEQC verdict remains **PROCESS-QUALIFIED ONLY**. The offline calibration gate is available for a future authorized dataset but does not change that verdict. The bridge is a
narrow scenario compiler, not a general PHREEQC interface or a replacement for
the canonical screening result. Its Cs selectivity, CEC mapping, source term
and transport pairing remain demonstration inputs pending calibration and
experimental agreement. The arithmetic oracle verifies only the declared
software/unit contract and is not a chemistry calibration oracle.

## Evidence scopes

The AMD/ROCm evidence under
`artifacts/amd-2026-07-28/platform-current/` is a core scientific/platform
snapshot: source revision `5edb8ce24b690810efad703f7550650192598118`, ROCm
7.2.1, exact FP64 GCS-to-transport-to-receptor parity, and 231 passed tests.
It predates the PHREEQC documentation/bridge merges and is retained as the
historical core-platform snapshot.

A **post-merge AMD/ROCm rerun of the `main` tree at head `b6d4c61e74`** was executed
on 2026-08-05 under `artifacts/amd-2026-08-05/post-merge/`: ROCm 7.2.1
(HIP `7.2.53211-e1a6bc5663`), torch `2.9.1+gitff65f5b`, Python 3.12.3,
gfx1100, 51.5 GB VRAM. The complete suite passed **388 tests, 2 skipped**
(the 2 skips are the external-PHREEQC tests requiring the real solver, not
AMD-related). All 13 PyTorch/ROCm tests that are skipped in the dependency-light
CI now pass on the AMD GPU. The FP64 platform benchmark reproduced the July
numbers: 1.82 ms median, **132.8×** speedup versus scalar, **7.94e-14** maximum
relative error, 81.1 M evaluations/s. Primary-GCS batch: 4.88× speedup,
4.44e-16 maximum relative error. SHA-256 digests are recorded in
`SHA256SUMS` inside that directory.

This AMD rerun predates the two review-hardening commits `3714bf8` and `1605cc6`.
Those commits are covered by GitHub-hosted CI only (run `31111109865`, 377 passed,
15 skipped); they were not re-run on the AMD workspace. They touch the arithmetic
oracle, report safety gate, calibration promotion gate, session memory and
redaction policy — none of which is part of the ROCm/FP64 numerical path measured
by the benchmark above, so the reported AMD performance figures remain applicable.

The latest core test counts are:

- **current `main` head `df8f028`: 377 passed, 15 skipped (run `31111109865`)**;
- review-hardening checkpoint `3714bf8`: 376 passed, 15 skipped (run `31093247490`);
- dependency-light controller: 216 passed, 13 optional-PyTorch skips;
- controller with PyTorch: 231 passed;
- AMD ROCm core snapshot (28 July): 231 passed;
- **AMD ROCm post-merge rerun of `main` at `b6d4c61e74` (5 August): 388 passed, 2 skipped** (external-PHREEQC only);
- merged multicomponent bridge integration gate: 364 passed, 15 skipped (run `30928408962`);
- non-runner calibration/hold-out gate integration: 370 passed, 15 skipped (run `30936374478`);
- external Cs registry integration: 373 passed, 15 skipped (run `30993946602`).

Historical counts in the AMD LLM and video records remain valid only for the
checkpoint explicitly named in those documents.

## Submission state

The private source repository is not judge-accessible by itself. The prepared
public contest-fork branch
`anakinsuper/Radeon-hackathon-2026-07:submission/track2-physics-first-ai-nuclidepath`
tracks `main` and was last verified byte-identical to `main` head `df8f028` on
6 August 2026 (source copy differs only by the excluded `.hermes/` planning
directory). It must be re-synchronized whenever `main` moves. Preceding code-bearing
checkpoint `2b256e322eaa8ca45a5b939fdecad09d66019b0c` from PR #24). Its contest
package now contains the complete current source under
`submissions/Track2-Physics-First-AI-NuclidePath/source/`, the updated
specification PDF and deck, and the contest-local manifest
`nuclidepath-contest-manifest-2.0`.

The internal deck/PDF/video package is a core Track 2 evidence package. The
video is 4:36, 1920×1080, 30 fps, H.264/AAC with embedded English subtitles;
the recorded path does not show the later PHREEQC bridge. The public
judge-accessible copy is
`https://drive.google.com/file/d/19fHhF9CXuQyX2jn6m9DFrUuHR6EyQD-1/view?usp=drivesdk`
(SHA-256 `47dc62f419c778d19af5724314a5d3bf3e04c3ee2175349897393162977c0d80`).

The internal deck, specification PDF, contact sheets and current video cards were regenerated from this verified source snapshot; their byte sizes and SHA-256 values are recorded in `submission/ARTIFACT_MANIFEST.json`. The visual package intentionally remains core-path evidence and does not claim to show or execute the PHREEQC bridge.

The remaining human gates are:

1. eligibility and AMD programme confirmation;
2. a judge-accessible public video URL;
3. a decision to make the complete source public or copy the current complete
   source into the contest fork;
4. authorization to open the official contest pull request.

Until those gates are completed, no document may call the contest package
submission-ready or claim that the public fork contains current `main`.

## Update rule

When source or evidence changes:

1. verify `main` and record the exact checkpoint in `WORK_HANDOFF.md`;
2. label CI, AMD, PHREEQC and visual evidence with its scope and commit/run;
3. regenerate PDF, deck and video only from the verified source snapshot;
4. update `submission/ARTIFACT_MANIFEST.json`;
5. keep `PROCESS-QUALIFIED ONLY` until calibrated parameters and experimental
   or otherwise qualified scientific agreement have actually been completed;
   the arithmetic oracle alone does not change the global verdict.

## Current PR #24 registry checkpoint

PR #24 added the separate EPA/Fuller/Dubus external Cs benchmark registry. It merged into `main` as `2b256e322eaa8ca45a5b939fdecad09d66019b0c`; its GitHub-hosted CI run `30993946602` passed with `373 passed, 15 skipped`, including workflow policy, compilation, wheel and whitespace checks. This is not a trusted self-hosted PHREEQC run, an AMD post-merge rerun, or scientific calibration evidence. Two later review-hardening commits `3714bf8` and `1605cc6` landed directly on `main` on 6 August 2026 (oracle row binding, report numeric-finiteness gate, calibration promotion-gate tightening, atomic session-memory rewrite, free-text secret redaction, editorial CI gate). The current `main` head `df8f028` passed GitHub-hosted CI run `31111109865` with `377 passed, 15 skipped`.
