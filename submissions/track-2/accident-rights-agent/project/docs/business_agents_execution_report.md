# Business Agents Execution Report

Execution date: 2026-07-29 (UTC+8)

## 1. Repository audit

- Repository: `accident-rights-agent`
- Branch at start: `main`
- Worktree at start: clean
- Starting commit: `e36a7e6 Record final local acceptance and contest fork`
- Previous relevant commits:
  - `5bf31df Validate local BGE legal retrieval`
  - `7617712 Implement legal RAG memory and case orchestration`
  - `1926edc Implement case intake and evidence reconstruction`
  - `a8224ad Bootstrap AMD local inference environment`
- Remote configuration: none in this development repository
- Baseline test result: 39 passed, 2 non-blocking environment warnings

The audit confirmed the existing Evidence Graph, `LegalCitation`, Case Capsule,
Fact Memory, `CaseState`, SQLite checkpointer, Verifier, and local-only vLLM
client. No completed module was rebuilt.

The Radeon Cloud Active Instance remained destroyed throughout this phase. No
instance was created, no persistent volume was mounted, and no remote result
was overwritten.

## 2. AGT status mapping

| ID | Status | Implementation and acceptance |
|---|---|---|
| AGT-01 | Complete | Business intake classifies uploaded/missing material, quality and blocking issues, collection actions, and `missing_evidence` routing without rerunning evidence extraction. |
| AGT-02 | Complete | `VehicleNatureResult` implements four classifications, confidence, factors, citations, missing evidence, warnings, and at least two hypotheses. |
| AGT-03 | Complete | Versioned deterministic rule engine compares all requested parameter groups and cannot output legal vehicle nature. |
| AGT-04 | Complete | Liability matrix covers twelve behavior groups for both parties; `confirmed` requires facts, evidence, and law. |
| AGT-05 | Complete | Three comparable liability hypotheses use transparent scoring and softmax; probabilities sum to 1. |
| AGT-06 | Complete | Accident responsibility, civil compensation allocation, and insurance payment estimate are independent schemas. |
| AGT-07 | Complete | Critical missing or disputed evidence blocks a unique responsibility selection and keeps multiple hypotheses. |
| AGT-08 | Complete | Conditional analysis covers surveillance, dashcam, appraisal, signal phase, and collision/braking evidence without inventing outcomes. |

## 3. Schemas and state

Added `app/schemas/business.py` with strict Pydantic models:

- `CaseIntakeResult`
- `EvidenceGap`
- `VehicleNatureResult`
- `ParameterComparison`
- `ViolationFinding`
- `CausationFinding`
- `LiabilityHypothesis`
- `LiabilityResult`
- `AccidentResponsibility`
- `CivilCompensationAllocation`
- `InsurancePaymentEstimate`
- `CounterfactualFinding`

All models use `extra="forbid"`. Free text is limited to explanation,
reasoning, warning, and collection-instruction fields.

`CaseState` now carries separate structured outputs for intake, vehicle nature,
violation, causation, liability, accident responsibility, civil compensation,
insurance payment, counterfactuals, missing evidence, and blocking issues.

## 4. Agent implementation

### 4.1 Business intake

- Recognizes all required material categories from explicit source roles and
  existing fact predicates.
- Separates required and optional material.
- Separates collection gaps from conclusion-blocking issues.
- Writes business intake summary and blocking state into `CaseState`.
- Writes `business_intake_completed` to the existing SQLite audit log.

### 4.2 Vehicle nature and parameter rules

- Ruleset: `CN-E_BICYCLE-GB17761-2024-v1`
- Jurisdiction: People’s Republic of China
- Effective date: 2025-09-01
- Source document ID: `CN-GB-17761-2024`
- Each parameter result includes rule version fields, Fact IDs, Evidence IDs,
  source Law ID, and comparison status.
- Nominal voltage is recorded for combined review; no obsolete threshold is
  silently reused.
- Pedal capability is conditional on drive mode.
- Technical non-compliance alone never returns `motor_vehicle`.
- Conflicts cap confidence and set the result to disputed.
- Vehicle results and hypotheses are saved to the Case Capsule and audit log.

### 4.3 Liability and causation

- Produces 24 violation rows: 12 categories × 2 parties.
- Only facts tied to existing Evidence IDs can be active.
- Only facts plus applicable legal citations can become `confirmed`.
- Causation uses directness and confidence weights, not violation count.
- The scoring trace records party scores, softmax temperature, adapter name,
  and whether the unique conclusion was blocked.
- Civil ranges are produced only when the vehicle classification selects a
  compensation regime.
- Insurance payment stays `insufficient_data` without complete policy, limits,
  terms, losses, exemptions, and prior-payment data.
- Results, probabilities, evidence IDs, and Law IDs are written to Case
  Capsule/Fact Memory events and the existing audit log.

## 5. Model behavior and local-only policy

Added two adapters:

- `DeterministicAgentModelAdapter`: default in local tests; no GPU or network.
- `LocalVLLMAgentModelAdapter`: uses the established
  `LocalVLLMClient` and OpenAI-compatible `/v1/chat/completions` contract.

The local adapter can produce explanation text only. Structured decisions,
probabilities, IDs, and amounts remain controlled by deterministic code and
Pydantic validation.

The existing local policy still accepts only loopback hosts on port 8000. No
public Qwen, DeepSeek, or remote OpenAI-compatible endpoint was added.

## 6. Verifier changes

The Verifier now:

- validates `VehicleNatureResult` and `LiabilityResult`;
- resolves every nested Fact ID and Evidence ID;
- validates nested and global `LegalCitation` objects against the local corpus;
- checks citation effective dates;
- checks vehicle classification/compensation-regime consistency;
- rechecks provenance for every confirmed violation;
- preserves protected-field validation;
- blocks high-risk wording including unsupported vehicle classification,
  responsibility, review-success, and insurer-saving guarantees.

## 7. Fixtures and tests

Three end-to-end fixtures were added:

- Demo A: relatively complete intersection collision materials;
- Demo B: insufficient vehicle-nature evidence;
- Demo C: conflicting determination/registration/trajectory facts.

New requested test files:

```text
tests/agents/test_case_intake.py
tests/agents/test_vehicle_nature.py
tests/agents/test_vehicle_rules.py
tests/agents/test_liability.py
tests/agents/test_counterfactual.py
tests/agents/test_agent_graph_integration.py
```

Vehicle nature has six explicit boundary cases:

1. compliant parameters and non-motor registration;
2. obvious technical non-compliance without registration/appraisal;
3. non-motor registration with modification evidence;
4. motor-vehicle appraisal;
5. conflicting materials;
6. insufficient evidence.

## 8. Commands and final results

```bash
.venv/bin/ruff check app tests
```

Result:

```text
All checks passed!
```

```bash
.venv/bin/mypy app
```

Result:

```text
Success: no issues found in 48 source files
```

```bash
.venv/bin/python -m compileall -q app tests
```

Result: passed with no output.

```bash
.venv/bin/pytest -q
```

Result:

```text
57 passed, 2 warnings in 17.48s
```

The warnings are unchanged environment warnings:

- LangChain Core’s Pydantic V1 layer on local Python 3.14;
- Starlette TestClient’s future httpx2 migration.

The validated Radeon target remains Python 3.10.

## 9. Degraded or deferred work

1. The liability softmax is an interpretable engineering baseline, not a
   calibrated judicial probability. Expert pairwise feedback and held-out case
   calibration remain future work.
2. The new business nodes were tested with the deterministic adapter because
   the Radeon Active Instance no longer exists. Local Qwen3-VL explanation
   latency, ROCm memory, throughput, and stability must be measured when a new
   instance is explicitly approved.
3. The ruleset is nationwide. Provincial/municipal registration-management
   packs and historical standard selection need further expansion.
4. Civil allocation is a qualified range for the competition scenario, not a
   production compensation calculator.
5. Insurance payment deliberately does not calculate an amount until policy,
   limits, terms, loss data, exemptions, and prior payments are complete.
6. Rights Workflow remains the existing placeholder and Human Approval gate.

## 10. Local experience addendum

A loopback-only experience panel is available at `/experience`. It creates a
fresh synthetic case per run and executes all three business agents through the
existing graph, Verifier, and Human Approval node. Demo A/B/C cover complete,
insufficient, and conflicting evidence.

Browser acceptance confirmed:

- Demo A reaches Human Approval with Verifier passed;
- Demo B treats technical non-compliance as suspected rather than automatic
  motor-vehicle classification and blocks a unique liability conclusion;
- Demo C lowers confidence, marks vehicle nature disputed, and blocks a unique
  liability conclusion;
- compliant design speed is excluded from accident-speed violations;
- affirmative braking evidence is marked refuted rather than confirmed as a
  violation;
- no browser console errors were observed.

Liability-law selection now uses explicit document/article mappings for
confirmed findings. Keyword-only legal matching no longer upgrades unrelated
facts to confirmed violations.

Current local acceptance: Ruff passed, Mypy passed, compileall passed, and
`63 passed, 2 non-blocking environment warnings`.

## 11. Rights Workflow handoff

The next phase should consume:

- intake collection actions and blocking issues;
- vehicle-nature missing evidence and alternative hypotheses;
- liability missing evidence and five counterfactual groups;
- selected/pending compensation regime;
- protected delivery dates and Law IDs from the Case Capsule.

The next phase must keep all external submissions at `draft` until explicit
human approval.
