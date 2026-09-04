# NuclidePath demo narration

**Target:** 3–5 minutes

NuclidePath is a private, physics-first AI agent for traceable cesium-137 groundwater screening. It was built for Track 2 of the AMD AI DevMaster Hackathon.

Contamination assessment combines incomplete site data, literature, numerical models and human judgment. A local language model can plan and explain, but it must never invent a physical value or silently become the calculator.

NuclidePath enforces that boundary. The local Qwen model plans an allow-listed workflow. Deterministic, versioned Python tools perform every scientific calculation. Retrieval, memory, permissions, provenance and uncertainty remain visible to the reviewer.

This is the live localhost dashboard. No cloud service is required. The analyst can edit the screening inputs: distribution coefficient, dissolved potassium, groundwater velocity, dispersion, porosity, density, distance and source concentration. Pressing Run Analysis executes a six-step workflow: validate, assess the site, retrieve local evidence, plan, simulate, and report.

The result compares two potassium cases. In this demonstration, twenty milligrams per litre of dissolved potassium reduces the effective cesium distribution coefficient. Retardation falls, the breakthrough marker arrives earlier, and the dissolved concentration at the assessment point is higher at the same evaluation time. These are screening results, not site predictions.

The scientific core is transport prototype zero point three. It evaluates the reactive Ogata–Banks analytical solution for a maintained boundary concentration on a homogeneous, saturated, semi-infinite one-dimensional domain. Sorption enters through a retardation factor. Radioactive decay uses the DDEP cesium-137 half-life of thirty point zero one eight years. The implementation states its partial differential equation, initial condition, boundary conditions, units and numerical-stability method.

The model does not represent layered geology, transient flow, nonlinear sorption, colloids or dose. Potassium competition is demonstrative, not a calibrated universal law. The dashboard presents these limitations instead of hiding them.

Uncertainty is also explicit. A seeded Monte Carlo explores declared ranges for K-d, potassium, velocity and dispersion. The chart shows the fifth percentile, median and ninety-fifth percentile. Travel time is presented in years, and every range is classified as literature-informed or demonstration-only. The same seed reproduces the same result.

The provenance tab shows local knowledge citations and missing site measurements. The artifact tab exposes the raw workflow result and ten downloadable outputs. A SHA-256 manifest verifies every runtime artifact. A second manifest verifies the deck, technical PDF, architecture and visual QA evidence.

The recording is a frozen core-path demonstration. Its subtitles preserve the
checkpoint visible in the video and must not be rewritten to imply that it
shows the later PHREEQC bridge. The historical bridge checkpoint is documented
separately: PR #15 integration CI passed 364 tests with 15 skips, while the
latest non-runner calibration-gate checkpoint is PR #22 CI with 370 passed and
15 skips; the later PR #24 registry integration passed 373 tests with 15 skips. The dated AMD core snapshot passed 231 and the dependency-light
controller passed 216 with 13 optional-PyTorch skips. The arithmetic oracle and
calibration gate are software evidence; PHREEQC scientific-result qualification
remains separate.

> **Recording-scope note:** the video does not show the multicomponent PHREEQC
> compiler or a trusted external-solver run.

The dated 28 July AMD core-platform snapshot passed 231 tests using ROCm 7.2.1. Its exact FP64 primary-GCS → transport → receptor pipeline measured 137.09× against scalar with `7.94e-14` maximum relative concentration error. The video must not be presented as footage of every later platform extension or as a full rerun of current `main`.

## Current update appendix (not footage in the historical video)

For a new recording or written update, state that AMD is verified at 231 passed, the controller gates are 216 passed/13 optional-PyTorch skips dependency-light and 231 passed with PyTorch, and the exact FP64 platform path measured 137.09× with `7.94e-14` maximum relative error. The scenario library is `0.4`, multi-species is opt-in `2.0`, and the guarded legacy GCS surrogate remains research-only `v1`. Do not imply that the video demonstrates extensions that are not visible on screen.

For a current written update, describe PHREEQC as an opt-in, schema-2 bridge
that compiles explicitly declared Cs plus K/Na/Ca/Mg chemistry and reports
comparative diagnostics. Mention the dependency-free Cs calibration/hold-out
gate as offline infrastructure only: it requires an authorized traceable
dataset and does not promote the chemistry. Keep the status
`PROCESS-QUALIFIED ONLY`: the paired Central Oklahoma cases are
sourced-composition integration fixtures, not validated transport predictions.

The key idea is not to replace engineering judgment. It is to make an AI-assisted technical workflow private, inspectable and reproducible. NuclidePath gives the language model the role it is good at, and keeps physics inside tools that can be tested, cited and audited.

Private AI without scientific surrender. That is NuclidePath.

## Current PR #24 registry checkpoint

PR #24 added the separate EPA/Fuller/Dubus external Cs benchmark registry. It merged into `main` as `2b256e322eaa8ca45a5b939fdecad09d66019b0c`; its GitHub-hosted CI run `30993946602` passed with `373 passed, 15 skipped`, including workflow policy, compilation, wheel and whitespace checks. This is not a trusted self-hosted PHREEQC run, an AMD post-merge rerun, or scientific calibration evidence. Two later review-hardening commits `3714bf8` and `1605cc6` landed directly on `main` on 6 August 2026 (oracle row binding, report numeric-finiteness gate, calibration promotion-gate tightening, atomic session-memory rewrite, free-text secret redaction, editorial CI gate). The current `main` head `df8f028` passed GitHub-hosted CI run `31111109865` with `377 passed, 15 skipped`.
