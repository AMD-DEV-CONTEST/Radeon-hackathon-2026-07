# NuclidePath — Submission and Expansion Roadmap

- **Project:** NuclidePath — private, physics-first AI agent for traceable Cs-137 groundwater screening
- **Hackathon:** AMD AI DevMaster Hackathon 2026 · Track 2
- **Current core version:** `transport-prototype-0.3`
- **Submission deadline:** 6 August 2026, 17:59 CEST
- **Current source state:** generalized PHREEQC multicomponent bridge, independent arithmetic oracle, dependency-free traceable Cs calibration/hold-out gate and separate external Cs benchmark registry are merged in PR #24 (merge `2b256e322eaa8ca45a5b939fdecad09d66019b0c`). Its integration gate is run `30993946602` (373 passed, 15 skipped); the current `main` head `df8f028`, after the review-hardening commits `3714bf8`/`1605cc6`, passed run `31111109865` (377 passed, 15 skipped); the calibration/hold-out gate is PR #22 run `30936374478` (370 passed, 15 skipped). A **post-merge AMD/ROCm rerun of `main` at head `b6d4c61e74`** (5 Aug 2026) passed **388 tests, 2 skipped** (only external-PHREEQC), with the FP64 platform benchmark reproducing 1.82 ms median / 132.8× / 7.94e-14 max error under `artifacts/amd-2026-08-05/post-merge/`.

## Guiding principle

NuclidePath is expanded by making evidence, deterministic physics, and reproducibility stronger—not by allowing the LLM to invent physical values. The local LLM plans and explains only; versioned deterministic tools own calculations, parameter validation, uncertainty analysis, and result artifacts.

## Current verified baseline

- [x] Reactive 1-D Ogata–Banks Cs-137 screening model with K+/Cs+ competition, retardation, dispersion, and radioactive decay.
- [x] Strict scenario/result contracts, parameter provenance labels, uncertainty ranges, seeded Monte Carlo, sensitivity analysis, and reproducible reports/manifests.
- [x] Private local-agent workflow: allow-listed planner, Site Agent, local retrieval, deterministic Environment Agent, redacted local memory, permission policy, and localhost-only UI/LLM endpoint.
- [x] CLI, dashboard, scientific documentation, English specification, deck, video, SHA-256 manifests and clean wheel gate. Recorded compatibility checkpoints: 216 pass/13 optional-PyTorch skips dependency-light; 231 pass with CPU PyTorch; 231 pass on AMD ROCm with exact FP64 GCS/platform parity evidence. The latest non-runner source gate is 377 passed/15 skipped (current `main` head `df8f028`, run `31111109865`); the preceding registry gate is 373 passed/15 skipped (PR #24, run `30993946602`); the preceding merged-source bridge gate is 364 passed/15 skipped (PR #15, run `30928408962`).
- [x] `scenario-library-0.4`: three provenance-bearing demonstration families, seeded virtual receptors, deterministic Scenario Validation Agent, and fail-closed Report Safety Gate.
- [x] Opt-in PHREEQC chemistry bridge: declared water composition, CEC, Cs plus one or more K/Na/Ca/Mg exchange coefficients, deterministic multicomponent input compilation, selected-output parsing, bounded execution and replay; still `PROCESS-QUALIFIED ONLY`.
- [x] Offline Cs exchange calibration gate: traceable dataset schema, group-disjoint calibration/hold-out split, transparent apparent-Kd fit, acceptance metrics and fail-closed promotion; no experimental dataset is bundled.
- [x] Historical AMD `0.2` checkpoint: Qwen3.5-9B Q8 with llama.cpp/HIP on `gfx1100`, all layers offloaded; retained as explicitly historical evidence.
- [x] AMD/ROCm evidence: historical 152-test/LLM/surrogate artifacts retained separately; the dated 28 July core-platform snapshot passes 231 tests and records exact FP64 primary-GCS → receptor parity and throughput under `artifacts/amd-2026-07-28/platform-current/`; the **post-merge full-current-`main` rerun (5 Aug) passes 388 tests, 2 skipped** under `artifacts/amd-2026-08-05/post-merge/`.
- [x] Prepared contest fork branch tracks `main`; complete source is copied into the contest package under `submissions/Track2-Physics-First-AI-NuclidePath/source/` with contest-local manifest `nuclidepath-contest-manifest-2.0`. It must be re-synchronized whenever `main` moves; verify the fork head against `main` before opening the official PR.
- [ ] Hosted judge-accessible video link, complete-source accessibility and official submission PR.

## Part I — Submission critical path

### 1. Recover Radeon Cloud access — completed

1. Report the launch issue in the AMD Track Discord with exact error, timestamp/timezone, and redacted screenshot.
2. State that the old template, a new SSH-enabled ROCm template, and provider/default templates all failed; request provisioning/capacity/account-queue review.
3. When capacity recovers, use a general-purpose ROCm image with persistent storage/PVC and SSH enabled.

### 2. Produce final AMD `0.3` evidence — completed

1. Save GPU/ROCm preflight evidence: `rocminfo`, `amd-smi` or `rocm-smi`, `/dev/kfd`, `/dev/dri`, PyTorch HIP availability, real synchronized tensor operation, disk, and version metadata.
2. Check out the released source cleanly and create the environment on persistent storage.
3. Start Qwen through llama.cpp/HIP with confirmed GPU layer offload and a credential-free loopback endpoint.
4. Reproduce the recorded regression gates: latest non-runner source gate 377 passed/15 skipped (current `main` head `df8f028`, run `31111109865`); the preceding gates are 373 passed/15 skipped (PR #24, run `30993946602`), 370 passed/15 skipped (PR #22, run `30936374478`) and 364 passed/15 skipped (PR #15, run `30928408962`). The 216/13 and 231 AMD controller figures remain dated compatibility snapshots.
5. Execute one real LLM-planned end-to-end scenario and retain tool trace, report, JSON, plots, and manifest.
6. Record GPU/VRAM, ROCm, model, quantization, build/backend flags, command, bind address, cold/warm latency, throughput, and memory use.
7. Update README, benchmark documentation, PDF, deck, and video only with measured `0.3` values. Never relabel the historical `0.2` measurement as `0.3` evidence.

### 3. Final release and submission gates

1. Re-run tests, clean-install/wheel smoke, hash validation, link checks, rendered PDF/PPTX inspection, and final video QA.
2. Scan the staged source/submission diff for secrets, keys, model caches, tokens, and runtime state.
3. Verify claim consistency across README, report, specification, deck, video narration, benchmark document, and PR body.
4. Publish the release/video, push the contest submission branch, and open the exact required PR only after the final gate passes and the user authorizes public contest publication.

## Part II — Near-term expansion: `v0.4`

These features add measurable value while preserving the transparent screening-model boundary.

### A. GPU-accelerated scientific analysis

**Goal:** AMD hardware should accelerate both local inference and numerical evidence generation.

- Add an optional ROCm/PyTorch backend for vectorized Monte Carlo and parameter sweeps.
- Preserve NumPy/CPU as the canonical fallback.
- Use identical scenario, seed, sample count, and output contract for CPU and GPU paths.
- Define and test output-parity tolerances before reporting a performance gain.
- Benchmark CPU versus AMD GPU for Monte Carlo/sensitivity workloads, including wall time, samples/s, memory, hardware, backend, and command.

**Acceptance evidence:** deterministic parity tests, performance table, saved benchmark metadata, and a dashboard comparison view.

### B. Versioned scenario library

**Status: implemented (`scenario-library-0.4`).** Three packaged demonstration entries include parameter-source classifications, expected qualitative behaviour, receptor definitions, uncertainty ranges, deterministic tests, report output, and checksummed manifests. See [SCENARIO_LIBRARY.md](SCENARIO_LIBRARY.md).

Add three transparent, screening-only scenario families:

1. **Baseline transport:** homogeneous 1-D Cs-137 breakthrough under declared reference assumptions.
2. **K+ competition stress test:** controlled K+ ranges showing changes in `Kd_eff`, retardation, travel time, and breakthrough.
3. **Conservative uncertainty case:** explicitly pessimistic demonstration ranges with P05/P50/P95 outputs and no regulatory interpretation.

Each scenario must include JSON input, parameter-source classification, expected qualitative behavior, deterministic regression tests, and report/manifest output.

### C. Virtual receptor screening

**Status: implemented (`virtual-receptors-0.4`) for points on the existing homogeneous 1-D path.** Seeded arrival-time and concentration P05/P50/P95 tables and an SVG are emitted; maxima are labelled `sampled_max`. Mapping, path connectivity, and multi-path flow remain future work.

Add versioned receptor locations along the same validated 1-D flow path.

- Report arrival-time and concentration distributions per receptor.
- Label any reported maximum honestly as `sampled_max` unless an actual peak search is performed.
- Do not publish operational or regulatory thresholds in demonstration reports.
- Identify declared-range characterization priorities and missing site-characterization data; do not label input-range span as sensitivity.

**Acceptance evidence:** receiver table, reproducible report, plot, scenario test, and explicit limitations.

## Part III — Scientific expansion: `v0.5+`

### A. Explicit source-term module

Separate source inventory/release history from the maintained boundary concentration model.

- Support finite pulse, finite-duration release, constant-rate release, and validated time-series input.
- Do not convert released mass into `C0` without a documented source, flow, geometry, and dilution contract.
- Keep the current maintained-boundary implementation as a separate validated model mode.

### B. Adsorption and competition hierarchy

Maintain a clear hierarchy rather than silently replacing the existing model:

**Primary-paper GCS implemented:** a provenance-bearing, deterministic Bradbury–Baeyens three-site reference-illite calculation is integrated into the opt-in multispecies v2 contract. K and Na compete on all sites; NH4 is included on FES only where Table 2 provides a coefficient; Ca/Mg/Sr are explicitly noncompetitive within this Cs model. The legacy v0.3 contract and legacy surrogate oracle remain unchanged. See [GCS_FOUNDATION.md](GCS_FOUNDATION.md).

**Opt-in multispecies contract implemented:** Cs-137 and Sr-90 can be evaluated independently against one provenance-bearing K/Na/Ca/Mg/NH4 chemistry record. Cs can use the primary-paper GCS path; Sr requires a sourced linear Kd. Coupled isotope chemistry and a mechanistic Sr sorption model remain unimplemented and fail closed. See [MULTISPECIES_V2.md](MULTISPECIES_V2.md).

**Research-only surrogate implemented and measured:** a guarded PyTorch model approximates the deterministic Cs/K oracle inside an explicit demonstration domain. An independent 100,000-case gate measured 11.37% maximum and 0.96% median relative Kd error against the oracle, within the declared 15% demonstration threshold. A kernel-only ROCm batch measured 121.56× versus the scalar CPU oracle. This validates neither the secondary parameters nor environmental chemistry. See [GCS_SURROGATE.md](GCS_SURROGATE.md).

| Level | Model | Status |
|---|---|---|
| 0 | linear equilibrium `Kd` | implemented |
| 1 | empirical K+/Cs+ competition `Kd_eff` | implemented |
| 2 | two-site / kinetic sorption | future, calibration required |
| 3 | nonlinear competitive isotherm | future, parameter evidence required |
| 4 | mineralogy-resolved reactive model | research track |

Every advanced level requires units, parameter provenance, literature/test support, limiting-case tests, and a comparison to the prior level.

### C. PHREEQC chemistry bridge

**Status: first opt-in compiler, bounded runner, chemistry diagnostics,
compile-only report integration and independent arithmetic oracle implemented;
real-run qualification and calibration remain future work.** The compiler accepts explicit water chemistry,
CEC, Cs plus one or more declared K/Na/Ca/Mg exchange coefficients and
provenance, then maps the existing distance, velocity, dispersion, porosity and
Cs-137 boundary activity into PHREEQC SOLUTION, EXCHANGE and TRANSPORT blocks.
The selected-output contract is dynamic, so K-free Na-Ca-Mg cases are valid.
It records solution-total, aqueous/exchange partition diagnostics and a
side-by-side empirical Kd_eff comparison while leaving the canonical empirical
Kd_eff and radioactive decay path unchanged. The oracle promotes only the
declared unit/mapping/occupancy contract to `NUMERICALLY VERIFIED`. See
[PHREEQC_MULTICOMPONENT_CASES.md](PHREEQC_MULTICOMPONENT_CASES.md).

Next scientific steps:

- perform the trusted real PHREEQC projection on main for both sourced cases
  with fresh executable and database digests;
- add a calibrated multi-cation Cs database or inline species set backed by
  competitive-sorption experiments;
- compare PHREEQC exchange occupancy/apparent retardation with the GCS and
  empirical paths on shared K/Na/Ca/Mg scenarios;
- retain the arithmetic oracle as a software-contract gate;
- add an independent solver/reference comparison and experimental oracle before
  promoting any PHREEQC chemistry result.
- use `SCIENTIFIC_VALIDATION_GATE.md` to ingest only authorized traceable observations; synthetic fixtures remain software-test-only.

### D. Layered flow-path network

Before a full spatial PDE model, implement a transparent chain/network of one-dimensional segments:

- unsaturated zone;
- shallow aquifer;
- deeper aquifer or alternative path;
- path-specific porosity, velocity, dispersivity, and sorption parameters;
- receptor wells connected to declared paths.

This is preferable to an unvalidated 2-D/3-D visualisation. Any future MODFLOW/MT3DMS or equivalent integration must retain solver version, input files, and comparison artifacts.

### E. Calibration and monitoring-data ingestion

The calibration gate infrastructure is now implemented offline. It does not open without measured provenance and a group-disjoint hold-out; the next required input is an authorized dataset, not another placeholder constant.

- Accept validated CSV/JSON observations with units, timestamps, location metadata, detection-limit flags, and provenance.
- Reject invalid numeric values, mixed/unknown units, malformed timestamps, and ambiguous coordinates.
- Provide parameter calibration only with synthetic benchmarks or qualified data; surface non-identifiability instead of fabricating a precise estimate.
- Report observed-versus-modelled comparisons and posterior/range assumptions clearly.

## Part IV — Agentic and evidence expansion

### A. Evidence Agent

A local agent/tool that retrieves bundled evidence and produces a structured parameter table:

`parameter → value/range → unit → source → provenance class → applicability → caveat`.

It may identify gaps and conflicts, but cannot overwrite deterministic model parameters without a user-approved structured scenario input.

### B. Scenario Validation Agent

**Status: implemented (`scenario-validation-0.4`) for versioned library entries.** The fail-closed deterministic preflight retains a structured trace and reports duration/half-life context without applying a decision criterion.

A deterministic preflight layer that checks:

- schemas, units, finite/range constraints, and parameter provenance;
- implied travel time against Cs-137 half-life and selected simulation duration;
- missing site data and unsupported extrapolation;
- incompatible model/source-term combinations.

It must fail closed on invalid inputs and retain a validation trace.

### C. Report Safety Gate

**Status: implemented (`report-safety-0.5`) on the versioned scenario publication path.** Artifacts are written only after the structured report passes. Broader free-form/NLP claim detection remains intentionally out of scope for this deterministic linter.

A deterministic report linter that blocks or flags:

- regulatory/operational claims;
- claims that a site is safe or that protective action is warranted;
- unlabelled demonstrative values;
- results without assumptions/provenance;
- use of `peak` when only a sampled maximum exists.

## Part V — Long-term platform direction

```text
Validated scenarios + monitoring data
                │
                ▼
      deterministic transport models
                │
     ┌──────────┼──────────┐
     ▼          ▼          ▼
GPU sweeps  calibration  receptor paths
     │          │          │
     └──────────┼──────────┘
                ▼
  local evidence/planning agents
                │
                ▼
traceable reports, dashboards, and replayable manifests
```

Potential later integrations: GIS receptor visualisation, external groundwater solvers, validated surrogates benchmarked against deterministic solvers, and controlled multi-user research collaboration. These are research/product features—not substitutes for validated regulatory assessment.

## Non-negotiable quality gates

Reject an expansion/release if:

- deterministic and LLM-planned physical outputs differ for the same valid scenario;
- a new physics model lacks assumptions, units, provenance, and limiting-case tests;
- GPU acceleration has no reproducible CPU comparison and parity tolerance;
- parameter values are presented as site-measured when they are literature/default/demonstration values;
- numerical results lack a model version, tool trace, or manifest;
- the dashboard/LLM endpoint binds publicly without authentication/authorization;
- any result is framed as an operational, regulatory, dose, public-alert, or safety decision.

## Recommended implementation order

1. Freeze the selected source snapshot, refresh the core AMD evidence if the current source changes the claimed workload, and synchronize the contest package only after publication is authorized.
2. GPU Monte Carlo backend with parity tests and benchmark evidence.
3. Scenario library and virtual receptors.
4. Explicit source-term module.
5. Layered flow-path network.
6. Supply an authorized competitive-sorption dataset and run the implemented calibration/hold-out gate before changing the canonical Kd path.
7. Layered flow-path network and receptor connectivity.
8. Kinetic/nonlinear sorption only when parameter evidence and validation data are available.
9. Monitoring-data calibration and broader external-solver integration.
