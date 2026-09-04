# NuclidePath — Project Specification 1.0

**Track:** AMD AI DevMaster Hackathon 2026, Track 2
**Team:** Physics-First AI
**Application:** NuclidePath
**Status:** implemented current source snapshot; submission package and public contest sync remain gated
**Last updated:** 5 August 2026

## 1. Scenario and problem

Groundwater contaminant-screening workflows combine incomplete site data, scientific literature, numerical models and analyst judgement. A general-purpose LLM is useful for planning and explaining this workflow, but it is not a trustworthy calculator and must not invent physical values.

NuclidePath demonstrates a private local agent that answers a bounded question:

> For a hypothetical maintained Cs-137 boundary concentration in groundwater, how do sorption and dissolved potassium affect retardation, travel time and dissolved-concentration breakthrough at an assessment point?

The product is designed for transparent preliminary screening and education. It is not a regulatory model, dose code or emergency decision system.

## 2. Users

- nuclear/environmental engineers exploring screening assumptions;
- researchers studying contaminant transport and sorption;
- reviewers auditing an AI-assisted technical workflow;
- hackathon judges evaluating private agent deployment on AMD hardware.

## 3. Product modes

### Dashboard

A localhost web interface exposes scenario inputs, deterministic outputs, agent steps, cited evidence, missing site data, uncertainty intervals and downloadable artifacts.

### Full CLI

A composite JSON case runs the complete agent, retrieval, transport, sensitivity, uncertainty and reporting pipeline.

### Offline validation

The deterministic planner exercises the same six workflow steps without an LLM. This is the CI/fallback path and proves that numerical outputs do not depend on generated text.

### AMD-local LLM

Qwen3.5-9B Q8 runs through `llama.cpp`/HIP on the AMD GPU and returns only the allow-listed plan. It cannot modify scenario fields or tool results.

### Optional PHREEQC chemistry bridge

The current source also exposes an opt-in, one-way compiler from an explicitly
validated NuclidePath chemistry block to PHREEQC `SOLUTION`, `EXCHANGE`,
`SELECTED_OUTPUT` and `TRANSPORT` input. Schema
`nuclidepath-phreeqc-chemistry-2` accepts Cs plus one or more declared
competitors from K, Na, Ca and Mg; K-free Na-Ca-Mg cases are supported. The
compiler, dynamic parser, per-ion diagnostics, report bridge and ReplayBundle
path are deterministic and CI-tested. The canonical transport model remains
the authoritative screening result, and ordinary reports mark the external
solver as compile-only/pending.

The bridge is `PROCESS-QUALIFIED ONLY`: the real Example 2 external execution
is a process qualification record, while the paired Central Oklahoma cases
still require a trusted run on `refs/heads/main`, a calibrated multi-cation Cs
parameterization and an independent numerical/experimental oracle. No PHREEQC
result is promoted to the canonical Kd path.

The non-runner remediation includes a dependency-free calibration/hold-out gate
that requires explicit K/Na/Ca/Mg units and provenance, disjoint calibration and
hold-out groups, quantitative acceptance metrics and a canonical report digest.
It remains closed for promotion until an authorized traceable experimental
dataset is supplied.

## 4. Track 2 capabilities

NuclidePath implements all five capabilities listed in the official rules.

### 4.1 Local knowledge retrieval

`LocalKnowledgeBase` indexes bundled Markdown documents and performs transparent TF-IDF ranking. A hit contains:

- document ID and title;
- matching excerpt;
- local path;
- source URL(s);
- numerical ranking score.

Retrieval requires no embedding service, cloud API or network connection.

### 4.2 Tool invocation

The Environment Agent calls `run_transport_contract`, which:

1. validates and normalizes a strict JSON schema;
2. constructs immutable physical parameters;
3. invokes `simulate_transport` for every evaluation time;
4. records derived values, assumptions, warnings and model version.

### 4.3 Multi-step planning

Both planners produce the same required sequence:

1. `validate_permissions`;
2. `site_agent`;
3. `knowledge_retrieval`;
4. `environment_agent`;
5. `store_memory`;
6. `synthesize_report`.

The orchestrator rejects unknown, missing or malformed steps.

### 4.4 Local multi-turn memory

`LocalMemoryStore` writes session-scoped JSONL with mode `0600`. It supports append, recent-context retrieval and explicit session deletion. Metadata is recursively redacted before persistence.

### 4.5 Permission and privacy control

`PermissionPolicy` defines role-specific allowlists. Default mode:

- permits validation, site assessment, local retrieval, physics, analysis, memory and reporting;
- denies external network access;
- always denies equipment control, operational control and public alerts;
- redacts names, emails, exact coordinates, tokens, API keys and passwords;
- binds the dashboard and LLM endpoint to loopback interfaces.

## 5. Functional requirements and evidence

| ID | Requirement | Evidence |
|---|---|---|
| FR-01 | Accept a complete structured scenario | `scenarios/cs137_emergency_full.json` |
| FR-02 | Reject invalid types, ranges, unknown fields and non-finite values | contract/site/analytical tests |
| FR-03 | Identify missing site characterization | `SiteAgent`, `test_site.py` |
| FR-04 | Retrieve local cited scientific context | `knowledge.py`, bundled corpus, retrieval tests |
| FR-05 | Execute a safe multi-step plan | `workflow.py`, workflow tests |
| FR-06 | Produce physical values only through deterministic tools | contract boundary and offline/LLM equality check |
| FR-07 | Compare K+ competition cases | report runs at 0 and the scenario-selected K+ value (20 mg/L in the default case) |
| FR-08 | Propagate declared parameter uncertainty | seeded Monte Carlo and quantiles |
| FR-09 | Preserve private multi-turn context | mode-0600 JSONL memory and redaction tests |
| FR-10 | Generate auditable outputs | JSON, Markdown, CSV, SVG and SHA-256 manifest |
| FR-11 | Provide local CLI and dashboard | installable entry points and HTTP tests |
| FR-12 | Run a private LLM on AMD | Qwen3.5-9B Q8 on ROCm/`gfx1100` |
| FR-13 | Compile declared multicomponent chemistry to an external solver contract | PHREEQC schema 2, deterministic parser/diagnostics, report bridge and replay tests |

## 6. Deterministic model

### Effective sorption under empirical K+ competition

```text
Kd_eff = Kd / (1 + alpha_K × [K+])
```

`alpha_K` is demonstrative unless experimentally calibrated.

### Retardation and travel time

```text
R = 1 + rho_b × Kd_eff / porosity
travel_time = distance × R / pore_water_velocity
```

### Reactive advection–dispersion with a declared source

For `x >= 0`:

```text
R ∂C/∂t = D ∂²C/∂x² − v ∂C/∂x − lambda R C
C(x,0)=0 for x>0 · C(0,t)=C0 · C(infinity,t)=0
A = sqrt(v² + 4 lambda R D)

C/C0 = 0.5 × [
  exp((v−A)x/(2D)) erfc((Rx−At)/(2 sqrt(DRt)))
  + exp((v+A)x/(2D)) erfc((Rx+At)/(2 sqrt(DRt)))
]
```

`v` is pore-water velocity and `C0` is a maintained boundary concentration. The solution reduces to classic Ogata–Banks when decay tends to zero, is bounded by `C0`, and is evaluated with a stable scaled-erfc implementation. The model version is `transport-prototype-0.3`.

## 7. Input contract

Required transport fields:

- `scenario_id`;
- `initial_concentration_bq_m3`;
- `distance_m`;
- `evaluation_times_s`;
- `distribution_coefficient_m3_kg`.

Optional fields have explicit defaults and units:

- `bulk_density_kg_m3`;
- `porosity`;
- `groundwater_velocity_m_s`;
- `dispersion_m2_s`;
- `potassium_mg_l`;
- `competition_coefficient_l_mg`;
- `half_life_years`.

Site context separately records event, radionuclide, pathway, description, provenance, classification and available characterization.

## 8. Parameter provenance and uncertainty

Every uncertainty range includes:

- lower and upper bound;
- distribution (`uniform`, `log_uniform` or `triangular`);
- classification (`site-measured-range`, `literature-range`, `demonstration-range`);
- human-readable source.

The bundled ranges intentionally mix one literature Cs Kd bracket with demonstrative hydraulic, dispersion, K+ and empirical-competition brackets. The report states that these inputs are independent and that reported intervals are not total predictive uncertainty.

## 9. Deployment

```text
AMD Radeon Graphics · gfx1100
ROCm 7.2.1
llama.cpp Release HIP build
unsloth/Qwen3.5-9B-GGUF · Q8_0
8192-token context · all layers offloaded
OpenAI-compatible endpoint · 127.0.0.1:8000
Dashboard · 127.0.0.1:8080
```

No cloud inference is required. Python execution has no mandatory third-party runtime dependency.

## 10. AMD optimization plan and measured evidence

Implemented:

- HIP build targeted to `gfx1100`;
- Q8_0 selected because available VRAM permitted a conservative quantization;
- `-ngl 99` offloads all model layers;
- reasoning mode disabled for a short deterministic planning response;
- context limited to 8192 tokens;
- endpoint and dashboard restricted to localhost.

Measured AMD `transport-prototype-0.2` runtime checkpoint:

- prompt processing: `2861.56 ± 178.91 tokens/s` at 512 tokens;
- generation: `67.77 ± 0.09 tokens/s` at 128 tokens;
- full 128-sample LLM-planned pipeline: `1.007 s`;
- LLM and offline physical `runs`: identical.

The preceding integration gate for the merged multicomponent bridge passed `364` tests, `15` skipped, with workflow policy, wheel and whitespace checks PASS. The current `main` head passed `377` tests, `15` skipped, after the review-hardening commits (atomic memory rewrite, free-text secret redaction, tightened calibration promotion gate); the preceding registry gate passed `373`, and the calibration-gate integration before it passed `370` tests, `15` skipped, with the same technical checks. The AMD ROCm evidence includes the dated 28 July core-platform snapshot at 231 passed with exact FP64 primary-GCS/platform parity, plus a **5 August post-merge rerun of `main` at head `b6d4c61e74`: 388 passed, 2 skipped** (only external-PHREEQC) under `artifacts/amd-2026-08-05/post-merge/`.

## 11. Verification

The dependency-light controller evidence contains 216 passing tests plus 13 optional-PyTorch skips; the PyTorch controller checkpoint passes 231 tests, and the retained AMD ROCm core-platform snapshot passes 231. The preceding bridge gate adds the PHREEQC multicomponent contracts and independent arithmetic oracle and reports 364 passed/15 skipped; the calibration gate after it reports 370 passed/15 skipped, the registry gate 373 passed/15 skipped, and the current `main` head 377 passed/15 skipped. Together these checkpoints cover:

- physical formulas and analytical cases;
- K+ monotonicity and radioactive decay;
- non-finite, negative, missing and unknown inputs;
- strict site metadata;
- retrieval ranking and no-match behaviour;
- permission denial and recursive privacy redaction;
- private memory permissions and session isolation;
- deterministic and mock-LLM planning;
- artifact generation and checksum verification;
- localhost dashboard health, POST execution and artifact serving.

The PHREEQC tests establish contract/schema behaviour, dynamic selected-output
closure, deterministic diagnostics, fail-closed execution and report artefact
integration. They do not establish calibrated chemistry, external scientific
agreement or regulatory validity.

## 12. Safety boundary

NuclidePath must not be used to:

- calculate public dose or regulatory compliance;
- declare a site or water source safe;
- issue protective-action advice or public alerts;
- control equipment or response systems;
- substitute for site measurements, calibrated models or qualified authorities.

The current screening model omits heterogeneous/transient flow, multidimensional transport, nonlinear/kinetic sorption, colloids, preferential pathways, matrix diffusion, daughter products and source-mass calibration.

## 13. Acceptance criteria

All project acceptance criteria are met when:

- offline and local-LLM demos complete from documented commands;
- all tests pass;
- all five Track 2 capability flags are true;
- the same case gives identical physical runs with both planners;
- source URLs, assumptions, classifications, warnings and uncertainty ranges appear in outputs;
- every artifact checksum verifies;
- the dashboard is usable on localhost;
- AMD runtime/model/hash/benchmark evidence is documented with its source revision and workload scope;
- the optional PHREEQC bridge is documented as process/comparative evidence only;
- README, specification, video script and slide deck are in English;
- public contest publication is not marked complete while the source fork is stale or the video URL is a placeholder.

## External Cs benchmark registry checkpoint

The repository includes a separate EPA/Fuller/Dubus external Cs benchmark
registry with source digests, CSV integrity checks and
`calibration_eligible: false`. Its GitHub-hosted CI gate passed with
`373 passed, 15 skipped`, including workflow policy, compilation, wheel and
whitespace checks. Two later review-hardening commits brought the current `main`
head to `377 passed, 15 skipped` with the same gates PASS.
This is not a trusted self-hosted PHREEQC run, an AMD post-merge rerun, or
scientific calibration evidence.
