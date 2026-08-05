# InventoryDoc Agent — Enterprise Architecture Document

> Version: v1.1 | Scope: enterprise architecture for a private, locally-deployed inventory audit Agent

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interaction Layer (Gradio)           │
│  ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Analyze  │ │ Mgmt Report  │ │ Chat     │ │ About    │  │
│  │ (input   │ │ (LLM report  │ │ (evidence│ │ (features│  │
│  │ +10 step)│ │ +GPU status) │ │ +FAQ)    │ │ +arch)   │  │
│  └──────────┘ └──────────────┘ └──────────┘ └──────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 Agent Orchestration Layer (src/agent.py)      │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │             10-Step State-Machine Workflow               │  │
│  │  Load → Noise → Baseline → Clean → Count → Variance →   │  │
│  │  Correlation → Location → Category → Deliverables        │  │
│  │  each step: status, duration_ms, summary, blocking       │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────────────┐  │
│  │ Input      │  │ Quality     │  │ Run Metadata +       │  │
│  │ Validator  │  │ Checker     │  │ Audit Log            │  │
│  └────────────┘  └─────────────┘  └──────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    Data Processing Layer                       │
│                                                               │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ RAG Engine │  │ Noise        │  │ Tools                │  │
│  │ (file load)│  │ Detector     │  │ (Excel/compute/report)│ │
│  └────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ Data Contract (data_contracts.yaml) + Ground Truth       │  │
│  │ (ground_truth.yaml) + Consistency Memory (memory.py)     │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   LLM Report Generation Layer                 │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ ReportGenerator (langchain + ChatOpenAI)                 │  │
│  │ LLM ONLY: management summary, risk grading, action plans │  │
│  │ LLM NEVER: fact computation, variance amounts, counts    │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ LLM Service (OpenAI-compatible)                          │  │
│  │ ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │  │
│  │ │ vLLM     │  │ llama.cpp│  │ Mock (testing)       │   │  │
│  │ └──────────┘  └──────────┘  └──────────────────────┘   │  │
│  │   AMD ROCm    AMD ROCm      CPU, no GPU required        │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

## 2. Data Flow

```
Input files (10 business files)
    │
    ▼
┌──────────────────────┐
│ Input validation      │ ← checks required files, identifies noise files
│ (contract check)      │
└─────────┬────────────┘
          │ passed
          ▼
┌──────────────────────┐
│ 10-step deterministic │ ← pure pandas, zero LLM, auditable
│ workflow              │
│ each step: status+time│
│ critical steps: gates │
└─────────┬────────────┘
          │
          ▼
┌──────────────────────┐
│ Quality checks (7)    │ ← severity=critical blocks the report
└─────────┬────────────┘
          │
          ├──→ Output: Excel (6 sheets) + analysis report (8 ch.) + JSON
          │
          ▼
┌──────────────────────┐
│ LLM management report │ ← LLM expression layer over deterministic facts
│ (real / mock / demo)  │ ← failure does not block core outputs
└──────────────────────┘
          │
          ▼
    Management approval → adjustment execution (human review, outside system)
```

## 3. LLM Safety Boundary

The Agent strictly follows the design principle **LLM never computes facts**:

| Agent Responsibility | Implementation | Safety Measure |
|---|---|---|
| Fact computation | 10-step deterministic pandas workflow | every step auditable & traceable |
| Number consistency | `ConsistencyMemory` | cross-deliverable numeric checks |
| Quality validation | `QualityChecker` (7 rules) | critical failures block report |
| Report expression | LLM writes text from structured metrics | prompt bounds facts; no fabrication |
| Chat answers | rule-based routing + evidence citations | no LLM dependency, cited answers |

## 4. Enterprise Governance Architecture

### 4.1 Input Governance

```
data_contracts.yaml
  ├── required_files: [01-06, 08, 09]  ← required
  ├── optional_files: [07, 10]          ← noise candidates
  └── purpose: business purpose of each file
```

`InputValidator` validates file completeness before the workflow starts; missing required files block execution.

### 4.2 Audit Log Structure

Each run produces one audit record:

```json
{
  "run_id": "RUN-20260729-143022",
  "started_at": "...",
  "finished_at": "...",
  "duration_seconds": 8.2,
  "input_files": [
    {"name": "01_stock_snapshot.csv", "sha256": "...", "size_bytes": 123456}
  ],
  "workflow_trace": [
    {"step": "Step 1: Load all files", "status": "success", "duration_ms": 1200}
  ],
  "quality_checks": {"passed": true, "critical_failed": 0},
  "report_generation": {"mode": "demo", "model": "...", "elapsed_seconds": 1.2}
}
```

### 4.3 Quality Gates

| Gate | Trigger | Blocking Behavior |
|---|---|---|
| Input validation | missing required file | workflow does not run |
| Step 1 load | total_files = 0 or error | Steps 2-10 do not continue |
| Step 3 baseline | selected is empty | Steps 4-10 do not continue |
| Step 5 count | error | Steps 6-10 do not continue |
| Step 6 amount calc | error | Steps 7-10 do not continue |
| Quality checks | severity=critical failed | management report not generated |

## 5. Deployment Architecture

### 5.1 Current (Hackathon MVP)

```
┌──────────────────────────────────────────────┐
│  Single-machine Python deployment             │
│  - pip install -r requirements.txt            │
│  - python3 start_ui.py / run_full_workflow.py │
│  - Gradio UI on :7860                         │
│  (optional) LLM service on :8000              │
└──────────────────────────────────────────────┘
```

### 5.2 Target (Enterprise)

```
┌─────────────┐  ┌──────────────┐  ┌─────────────┐
│  Web front  │  │ Agent API    │  │ LLM service │
│  (Gradio)   │→│  (FastAPI)   │→│  (vLLM/llama)│
│  :8080      │  │  :8000       │  │  :8001       │
└─────────────┘  └──────────────┘  └─────────────┘
                      │
                      ▼
                 ┌──────────────┐
                 │ Persistence  │
                 │ (SQLite/Postg)│
                 │ audit_log    │
                 │ chat_history │
                 └──────────────┘
```

## 6. Observability

| Dimension | Implementation |
|---|---|
| Run monitoring | run_metadata (run_id, duration, status) |
| Step tracing | workflow_trace (per-step status + duration) |
| LLM monitoring | benchmark_llm.py (latency, chars/sec) |
| Quality monitoring | quality_checks (7 detailed checks) |
| Report metadata | report_generation_metadata.json (mode, model, elapsed) |
| Error monitoring | error steps in workflow_trace |

## 7. Risks & Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| LLM service unreachable | management report fails | --demo / --mock fallback |
| Malformed input files | workflow interrupted | schema validation + friendly errors |
| Stale ground truth | quality-check false alarms | config-driven GT, dataset versioning |
| Dataset changes | compatibility drops | data contracts support multiple templates |

## 8. 2026 Forward Directions

- **Agent Governance**: full trace per run; key conclusions traceable
- **Evidence-grounded Generation**: LLM reports cite structured facts
- **Human-in-the-loop**: Agent suggests → human approves → system executes
- **Data Contract Agent**: auto-detect file templates and missing fields
- **ERP Connector Ready**: reserved boundaries for SAP/Kingdee/Yonyou/WMS
- **Model Observability**: record model, endpoint, latency, tokens/sec, fallback
- **Role-based Review**: warehouse / finance / management see different views and approval actions

---

> Doc version: v1.1 | Last updated: 2026-07-31 | Author: Architecture Team
