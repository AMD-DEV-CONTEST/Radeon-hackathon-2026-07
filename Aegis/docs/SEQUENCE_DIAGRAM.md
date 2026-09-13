# Sequence diagram — one incident, end to end

```
User/Alert   API (FastAPI)   IncidentService   LangGraph   vLLM/ROCm   Postgres   SRE (approver)
    │              │                │              │            │          │            │
    │ POST         │                │               │            │          │            │
    │ /incidents ─>│                │               │            │          │            │
    │              │  create_incident() ────────────────────────────────────>│            │
    │              │                │  INSERT incidents (status=triggered)   │            │
    │              │<── 202 Accepted (background task scheduled) ────────────│            │
    │              │                │              │            │          │            │
    │              │  run_investigation() (background task)     │          │            │
    │              │                │──build_incident_graph()──>│            │          │            │
    │              │                │              │  Planner ─>│ complete() │          │            │
    │              │                │              │            │<── plan ───│          │            │
    │              │                │              │  fan-out to selected investigators  │            │
    │              │                │              │  LogAnalyst ─> tool: log_query       │            │
    │              │                │              │             ─> complete() ──────────>│            │
    │              │                │              │  MetricsAnalyst ─> tool: metrics_query│            │
    │              │                │              │  (both run concurrently)              │            │
    │              │                │              │  each writes AgentStep + Evidence ────────────────>│            │
    │              │                │              │  Synthesizer ─> complete() (ranks hypotheses) ────>│            │
    │              │                │              │  Remediation ─> complete() (proposes action) ─────>│            │
    │              │                │  UPDATE incidents SET status=remediation_pending_approval ────────>│            │
    │              │                │              │            │          │            │
    │  GET /incidents/{id} (poll or SSE stream) ───>│            │          │            │
    │<── incident detail + agent trace + evidence ──│            │          │            │
    │              │                │              │            │          │            │
    │              │                │              │            │          │  reviews trace, evidence
    │              │                │              │            │          │  POST /remediation/approve
    │              │                │              │            │          │<───────────│
    │              │  approve_and_execute_remediation()          │          │            │
    │              │  RemediationActionsTool.run() ──────────────────────────────────────>│ (writes AuditLog
    │              │                │              │            │          │             │  BEFORE executing)
    │              │  UPDATE incidents SET status=resolved ──────────────────────────────>│            │
    │              │  MemoryService.record_resolved_incident() ─> embed() ─> vLLM ────────>│            │
    │              │                │              │            │  UPSERT memory_records ─>│            │
```
