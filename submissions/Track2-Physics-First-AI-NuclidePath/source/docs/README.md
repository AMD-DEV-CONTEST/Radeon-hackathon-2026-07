# NuclidePath documentation index

This directory contains the stable technical documentation for NuclidePath.
Current branch, pull-request, review, and next-session state belongs in
[`WORK_HANDOFF.md`](../WORK_HANDOFF.md), not in the long-lived technical
contracts listed below.

## Start here

1. [Project README](../README.md) — project purpose, quick start, architecture,
   capabilities, and scientific limitations.
2. [Current work handoff](../WORK_HANDOFF.md) — authoritative active branch,
   pull request, checkpoint, evidence, constraints, and next action.
3. [Current release state](RELEASE_STATE.md) — cross-document evidence scope,
   current PHREEQC boundary and submission blockers.
4. [Specification](SPECIFICATION.md) — intended project scope and requirements.
5. [Architecture](ARCHITECTURE.md) — components, data flow, and execution model.
6. [Tool contracts](CONTRACTS.md) — deterministic interfaces and schemas.

## Scientific model and evidence

- [Scientific validation](VALIDATION.md)
- [Cs exchange calibration gate](SCIENTIFIC_VALIDATION_GATE.md)
- [Uncertainty and parameter provenance](UNCERTAINTY.md)
- [Parameters and sources](PARAMETERS.md)
- [Deterministic Cs/K GCS foundation](GCS_FOUNDATION.md)
- [Multi-isotope contract v2](MULTISPECIES_V2.md)
- [Guarded GCS surrogate](GCS_SURROGATE.md)
- [Versioned scenario library](SCENARIO_LIBRARY.md)

These documents describe screening, modelling, provenance, and numerical
contracts. None of them implies regulatory validation unless explicitly stated.
The current evidence scope and submission blockers are summarized in
[RELEASE_STATE.md](RELEASE_STATE.md).

## External solver and PHREEQC qualification

- [External solver adapters](EXTERNAL_SOLVER_ADAPTERS.md) — generic bounded
  process, artifact-integrity, stream, timeout, and containment contract.
- [PHREEQC bounded qualification](PHREEQC_QUALIFICATION.md) — checksum-pinned
  Example 2 qualification, provenance, parser boundary, replay, and scientific
  limitations.
- [PHREEQC scenario compiler](PHREEQC_SCENARIO_COMPILER.md) — opt-in
  narrow NuclidePath-to-PHREEQC water chemistry, declared multicomponent exchange,
  transport mapping, bounded execution, selected-output parsing, and replay.
- [PHREEQC multicomponent cases](PHREEQC_MULTICOMPONENT_CASES.md) — sourced
  K-free Na-Ca-Mg Central Oklahoma projections and their scientific boundary.
- [PHREEQC numerical oracle](PHREEQC_NUMERICAL_ORACLE.md) — independent,
  machine-readable arithmetic checks for the declared bridge contract.
- [CI and runner trust boundary](CI_SECURITY.md) — GitHub-hosted automatic CI,
  trusted manual self-hosted qualification, exact workflow policy, Action pins,
  and lock maintenance.
- [PHREEQC fixture provenance](../tests/fixtures/phreeqc/README.md)

The Phase F verdict is **PROCESS-QUALIFIED ONLY**. The schema-2 bridge now has a
separate `NUMERICALLY VERIFIED` arithmetic evidence layer, but this does not
establish experimental agreement, multi-cation Cs qualification, general PHREEQC
compatibility, GCS equivalence, or regulatory validity.

## Supporting modules without a dedicated document

These modules are part of the shipped package and are covered by the test suite,
but they support the contracts above rather than defining one of their own. They
are listed here so the documented surface matches the delivered code.

| Module | Purpose | Tests |
|---|---|---|
| `nuclear_agent.gpu_analysis` | Optional PyTorch backend for batched transport evaluation; falls back to the canonical scalar path when torch is absent | `tests/test_gpu_analysis.py` |
| `nuclear_agent.gcs_primary_accelerated` | Exact batched PyTorch backend for the primary Bradbury GCS — an exact reformulation, not a learned approximation | `tests/test_gcs_primary_accelerated.py` |
| `nuclear_agent.gcs_validation` | Source-faithful Bradbury (2000) validation scenarios and acceptance envelopes | `tests/test_gcs_validation.py` |
| `nuclear_agent.likelihood` | Validated Gaussian and left-censored log-likelihoods; no sampler and no inference claim | `tests/test_phase_d2_d3.py` |
| `nuclear_agent.recovery` | Deterministic bounded-grid parameter recovery, explicitly not a Bayesian posterior | `tests/test_phase_d2_d3.py` |
| `nuclear_agent.model_selection` | Deterministic fail-closed model eligibility and selection behind the dashboard endpoint | `tests/test_phase_e4_dashboard.py` |
| `nuclear_agent.observations` | Strict immutable ingestion of scientific observations | `tests/test_analytical_validation.py` |
| `nuclear_agent.path_network` | Immutable acyclic directed 1-D segment networks | `tests/test_receptors.py` |
| `nuclear_agent.replay_cli` | `nuclear-emergency-replay` entry point over the ReplayBundle contract | `tests/test_external_adapters.py` |

The phase notes [PHASE_B.md](PHASE_B.md), [PHASE_C_SOURCE_AND_PATHS.md](PHASE_C_SOURCE_AND_PATHS.md),
[PHASE_D2_D3.md](PHASE_D2_D3.md), [PHASE_E4_DASHBOARD.md](PHASE_E4_DASHBOARD.md) and
[phase-e.md](phase-e.md) record how these increments were introduced. They are
historical development records, not current contracts.

## Reproducing the editorial package

The deck, specification PDF, contact sheets and video assets are generated, not
hand-authored. [`scripts/README.md`](../scripts/README.md) maps each script to the
artifact it produces and lists the exact regeneration order. Every generated
artifact is hash-tracked in `submission/ARTIFACT_MANIFEST.json`.

## AMD and local-AI evidence

- [AMD environment](AMD_ENVIRONMENT.md)
- [LLM deployment benchmark](AMD_LLM_BENCHMARK.md)
- [AMD scientific transport benchmark](AMD_SCIENTIFIC_BENCHMARK.md)
- [AMD exact GCS and platform benchmark](AMD_PLATFORM_BENCHMARK.md)

## Privacy and operational boundaries

- [Privacy and permissions](PRIVACY.md)
- [CI and runner trust boundary](CI_SECURITY.md)

NuclidePath is a private-agent screening prototype. Network isolation,
operating-system sandboxing, host cleanup, and regulatory decision authority are
external responsibilities unless a document explicitly defines otherwise.

## Demo and submission material

- [Demo scenario and recording script](DEMO_SCENARIO.md)
- [Final English video narration](VIDEO_NARRATION.md) — the script matching the
  recorded core video.
- [Current narration appendix](VIDEO_NARRATION_CURRENT.md) — written updates that
  are **not** footage in the recorded video.
- [Hackathon setup and human gates](HACKATHON_SETUP.md)
- [Official submission checklist](SUBMISSION_CHECKLIST.md)
- [Private video deliverables](../private-deliverables/README.md) — video masters,
  narration audio, subtitle tracks and their checksums, including which file is
  the intended submission master.

## Documentation conventions

- Stable contracts belong under `docs/`.
- Active operational state belongs in `WORK_HANDOFF.md`.
- Checksums, commit SHAs, run IDs, and test counts must identify the exact
  checkpoint they support.
- Build-specific executable hashes must never be presented as universal release
  identifiers.
- Replay internal consistency must not be described as author authentication.
- A self-hosted runner must not be described as ephemeral or sandboxed unless
  that property has been independently established.
- Historical checkpoints may remain documented, but current-state sections must
  not contain obsolete open-work claims.

## Updating documentation

When implementation changes affect a documented contract:

1. update the relevant stable technical document;
2. update tests that enforce the contract;
3. update `WORK_HANDOFF.md` with the new checkpoint and next action;
4. verify links and terminology;
5. run the locked suite and the relevant opt-in external test;
6. keep the pull request Draft until the required independent review is complete.
