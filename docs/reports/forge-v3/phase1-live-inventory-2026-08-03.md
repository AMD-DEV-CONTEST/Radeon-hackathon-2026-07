# Forge V3 Phase 1 — Live Execution Inventory (Source-Based)

Date: 2026-08-03  
Repo: `/home/cesarops/cesarops_push`  
Branch: `forge-v3-integration`

## Classification Key
- ImplementedAndWired
- ImplementedNotWired
- LegacyWired
- Mocked
- FixtureBacked
- FrontendOnly
- Broken
- Unknown

## Stage Inventory

### 1) MissionSpec / Operator Entry
- Classification: **LegacyWired**
- Source path: `forge_src/main.rs`
- Function/route: `POST /send` → `send_message`
- Caller: UI (`forge_src/index.html`, `forge_src/cluster_panel.html`)
- Callee: `loop_engine::run_with_context`
- Input type: JSON `{ message: string, lane?: string }`
- Output type: JSON `SendResponse { response, tool_actions, diagnosis }`
- Process/port: Axum service on `0.0.0.0:9100`
- Evidence: `main.rs` router + `send_message`
- Current gap: no explicit MissionSpec schema object; no mission/run IDs generated at entry.

### 2) Mission Control / Orchestrator
- Classification: **ImplementedAndWired**
- Source path: `forge_src/loop_engine.rs`
- Function: `run_with_context` / `run_inner`
- Caller: `send_message`
- Callee: thinker/coder generation endpoints, translator, diagnostics, tools
- Input type: `(AppState, user message, RunContext)`
- Output type: `SendResponse`
- Evidence: tool/action loop, interrupt handling, route-linked lane persistence
- Current gap: loop does not enforce Forge V3 stage contract boundaries or chain-of-custody manifest.

### 3) Context Compiler
- Classification: **LegacyWired**
- Source path: `forge_src/loop_engine.rs` (`get_thinker_preflight`)
- Caller: `run_inner` pre-flight branch
- Callee: thinker endpoint (`/api/v1/generate`)
- Input type: raw operator text + conversation
- Output type: string context injected into prompt
- Evidence: thinker preflight stage and prompt-building
- Current gap: no typed context packet artifact, no authoritative knowledge metadata captured.

### 4) Contract Builder
- Classification: **LegacyWired**
- Source path: `forge_src/loop_engine.rs` + `forge_src/translator.rs`
- Caller: orchestration loop
- Callee: coder endpoint + translator normalization
- Input type: prompt text
- Output type: normalized tool-call/content stream
- Evidence: model generation + normalized tool-call extraction/handling
- Current gap: no explicit Forge contract object with claim/source IDs.

### 5) Contract Validator
- Classification: **ImplementedAndWired** (for endpoint validation), **ImplementedNotWired** (for Forge contract semantics)
- Source path: `forge_src/validator.rs`, `main.rs:/validate`
- Caller: API clients and monitor flow
- Callee: endpoint probes (`/v1/models`, `/v1/completions`)
- Input type: endpoint config/prompt
- Output type: `ValidationResult`, ping, benchmark
- Evidence: `/validate`, `/validate/ping`, token agreement checks
- Current gap: no deterministic contract semantic validator for hard constraints/claim coverage.

### 6) Worker Selection / Routing
- Classification: **ImplementedAndWired**
- Source path: `forge_src/routing.rs`, `forge_src/cluster_store.rs`, `main.rs`
- Caller: `send_message`, `workflow_execute`, worker start APIs
- Callee: role endpoint resolution + worker launch dispatch
- Input type: lane role / routing preset / worker config
- Output type: endpoint URL or worker process launch command
- Evidence: `resolve_lane_coder_url`, `/cluster/routing/preset/{id}`, `/cluster/worker/{name}/start`
- Current gap: qualification scores are not a hard gate in selection decisions.

### 7) Paddler / Inference Backend Dispatch
- Classification: **LegacyWired**
- Source path: `scripts/build_paddler_cuda.sh`, `paddler_deploy/*.service`, `main.rs:/cluster/dispatch/*`
- Caller: dispatch UI and API
- Callee: launched koboldcpp/llama-server workers
- Input type: dispatch assignment JSON
- Output type: launched endpoint list + persisted `/tmp/dispatch_routing.json`
- Evidence: `dispatch_launch`, `dispatch_stop`, service files
- Current gap: mission identity is not propagated through dispatch boundaries.

### 8) Bounded Executor (Test Lab)
- Classification: **FixtureBacked**
- Source path: `core/forge-test-lab/src/worker.rs`, `examples/run_aircraft_fixture_v1.rs`
- Caller: test lab example/tests
- Callee: `TestLabCoordinator` → `SandboxExecutorWorker` → `SkepticalReviewerWorker`
- Input type: `ResearchMission` + fixture-set contract/metrics
- Output type: `EvidenceReport`, `QualificationDecision`, optional `EvidenceLayerCandidate`
- Evidence: explicit `ExecutionMode::DerivedFixtureMetrics`; artifacts written under `reports/test-lab/...`
- Current gap: not wired into `forge_src/main.rs` API path yet.

### 9) Human Review Boundary
- Classification: **ImplementedAndWired** (inside Test Lab), **ImplementedNotWired** (Forge API flow)
- Source path: `core/forge-test-lab/src/worker.rs`
- Caller: `TestLabCoordinator::execute_mission`
- Callee: candidate generation gated on `AcceptForHumanReview`
- Input type: `EvidenceReport`
- Output type: `QualificationDecision` + optional `EvidenceLayerCandidate`
- Evidence: candidate emitted only when decision is `AcceptForHumanReview`
- Current gap: no unified Forge Admin mission trace for this boundary.

### 10) Evidence Reports
- Classification: **ImplementedAndWired** (test-lab local path), **LegacyWired** (forge loop trace)
- Source path: `core/forge-test-lab/src/schemas.rs`, `core/forge-test-lab/src/worker.rs`, `var/missions/forge_loop_trace.jsonl`
- Caller: test lab execution and forge loop runtime
- Callee: filesystem artifact writes
- Input type: mission/contract/metrics/runtime stages
- Output type: JSON artifacts and JSONL trace
- Evidence: generated report files and mission traces present
- Current gap: no single chain-of-custody manifest spanning MissionSpec → Human Review.

### 11) Mission Control / Admin Trace
- Classification: **LegacyWired**
- Source path: `main.rs:/monitor`, `/cluster/*`, `/lanes/activity`
- Caller: web UIs (`cluster_panel.html`, `wall.html`, `dispatch.html`)
- Callee: runtime probes and route handlers
- Input type: HTTP requests
- Output type: live status JSON
- Evidence: extensive route map in router setup
- Current gap: no explicit run_id correlation across all stages.

### 12) Knowledge Repository Integration
- Classification: **ImplementedNotWired**
- Source path: `/var/cesarops/forge-knowledge-repo/` (external), `~/.forge/knowledge` symlink
- Caller: currently manual/auxiliary scripts
- Callee: N/A in main forge runtime
- Input type: markdown + frontmatter + manifest hash
- Output type: retrievable docs by class
- Evidence: repository/hash verified in Phase 0
- Current gap: no bounded in-process `KnowledgeProvider` adapter in `forge_src` yet.

## Intended vs Actual (Condensed)

- Intended V3: MissionSpec → Context Compiler → Contract Builder → Contract Validator → Worker Selection → Dispatch → Bounded Executor → Evidence → Human Review.
- Actual live path:
  - `/send` enters `loop_engine`, does thinker/coder/tool loop and returns response.
  - Test Lab is available and deterministic but mostly separate from `/send` path.
  - Evidence and Human Review gating exist in Test Lab crate, not yet end-to-end wired from MissionSpec route.

## Immediate V3 Slice Candidate

Best bounded vertical-slice insertion point:
- Entry: new admin-safe route in `forge_src/main.rs` (MissionSpec action equivalent)
- Reuse: `core/forge-test-lab` mission schema/executor/reviewer
- Add: mission_id + run_id propagation and chain-of-custody manifest write
- Stop: explicit Human Review boundary (no promotion/deployment mutation)
