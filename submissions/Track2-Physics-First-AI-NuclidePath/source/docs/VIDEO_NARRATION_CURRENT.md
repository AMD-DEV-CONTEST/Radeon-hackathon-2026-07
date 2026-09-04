# NuclidePath — current source narration

**Target:** 3–5 minutes  
**Recording scope:** canonical Track 2 core path; the optional PHREEQC bridge is
not shown in the existing video.

NuclidePath is a private, physics-first AI workflow for traceable Cs-137
groundwater screening. The language model may plan an allow-listed workflow,
but it never calculates transport, invents parameters or changes a scientific
result. Deterministic versioned tools own the equations, uncertainty,
provenance and SHA-256 artifacts.

The current source contains two deliberately separated scientific paths.

First, the canonical `transport-prototype-0.3` model solves the reactive
one-dimensional Ogata–Banks constant-source screening problem with dispersion,
retardation, radioactive decay and the empirical K+ comparison. This is the
path demonstrated by the current AMD video and platform evidence. It is not a
dose code, calibrated site model, regulatory tool or emergency decision system.

Second, the opt-in PHREEQC bridge compiles an explicitly declared chemistry
block into PHREEQC `SOLUTION`, `EXCHANGE`, `SELECTED_OUTPUT` and
`TRANSPORT` sections. Schema `nuclidepath-phreeqc-chemistry-2` accepts Cs
plus one or more declared competitors from K, Na, Ca and Mg, including the
K-free Central Oklahoma brine and recharge fixtures. The compiler, dynamic
parser, per-ion diagnostics, report bridge and replay path are deterministic.

PHREEQC does not silently replace the canonical Kd path. Its status remains
**PROCESS-QUALIFIED ONLY**. The official Example 2 process qualification is
recorded; the new multicomponent cases still require a trusted run on
`refs/heads/main`, fresh executable/database digests and a calibrated
multi-cation Cs parameterization. The independent arithmetic oracle now verifies
the declared unit, grid, non-negativity and exchange-capacity contract. The
Central Oklahoma water compositions are sourced contexts, while the Cs source,
CEC/transport mapping and pairing are demonstration inputs.

The preceding merged-bridge integration evidence is PR #15 run 30928408962:
364 passed, 15 skipped, with workflow policy, wheel and whitespace checks
passing. The latest non-runner calibration-gate evidence is PR #22 run
30936374478: 370 passed, 15 skipped, with the same technical checks passing.
The later PR #24 external-registry integration passed 373 tests with 15 skips;
this registry is not shown in the existing recording.
AMD evidence is scoped separately to the 28 July core snapshot: 231 AMD tests,
216 dependency-light controller passes plus 13 optional-PyTorch skips, and exact
FP64 GCS/transport/receptor parity. Do not call these checkpoints a fresh
post-merge AMD rerun of every current-main feature.

The video closes on the project boundary: local AI coordinates the work, while
deterministic and explicitly qualified tools own the numbers. The source,
assumptions, tests, external-solver boundaries and human submission gates
remain inspectable.

## Current PR #24 registry checkpoint

PR #24 added the separate EPA/Fuller/Dubus external Cs benchmark registry. It merged into `main` as `2b256e322eaa8ca45a5b939fdecad09d66019b0c`; its GitHub-hosted CI run `30993946602` passed with `373 passed, 15 skipped`, including workflow policy, compilation, wheel and whitespace checks. This is not a trusted self-hosted PHREEQC run, an AMD post-merge rerun, or scientific calibration evidence. Two later review-hardening commits `3714bf8` and `1605cc6` landed directly on `main` on 6 August 2026 (oracle row binding, report numeric-finiteness gate, calibration promotion-gate tightening, atomic session-memory rewrite, free-text secret redaction, editorial CI gate). The current `main` head `df8f028` passed GitHub-hosted CI run `31111109865` with `377 passed, 15 skipped`.
