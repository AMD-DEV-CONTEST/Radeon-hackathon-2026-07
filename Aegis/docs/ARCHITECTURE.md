# Aegis — Architecture

## 1. System overview

Aegis is a multi-agent, on-prem incident investigation system. An incident comes in
(alert, log spike, or manual report); a LangGraph-orchestrated team of specialist
agents investigates it in parallel, cites the evidence they find, and a Synthesizer
agent produces a ranked, confidence-scored root cause. A Remediation agent proposes
(never auto-executes) a fix, which a human SRE/admin approves before anything touches
production. Every inference call runs against a local vLLM server on an AMD Radeon
GPU via ROCm — no incident data, logs, or secrets ever leave the host.

## 2. High-level architecture

```
                              ┌─────────────────────┐
                              │   Next.js frontend    │
                              │  (incident stream,     │
                              │   agent trace, GPU      │
                              │   benchmark dashboard)  │
                              └──────────┬───────────┘
                                         │ REST + SSE
                              ┌──────────▼───────────┐
                              │   FastAPI backend      │
                              │  ┌──────────────────┐ │
                              │  │  Auth / RBAC      │ │
                              │  ├──────────────────┤ │
                              │  │  Incident Service │ │
                              │  ├──────────────────┤ │
                              │  │  LangGraph agent  │ │
                              │  │  orchestration    │ │
                              │  ├──────────────────┤ │
                              │  │  Tool framework   │ │
                              │  ├──────────────────┤ │
                              │  │  Memory / RAG     │ │
                              │  └──────────────────┘ │
                              └───┬──────────┬────────┘
                                  │          │
                    ┌─────────────▼──┐   ┌───▼─────────────────┐
                    │  Postgres +      │   │  vLLM on ROCm        │
                    │  pgvector        │   │  (AMD Radeon GPU)     │
                    │  (incidents,     │   │  Qwen2.5-14B-Instruct │
                    │  evidence,       │   │  OpenAI-compatible    │
                    │  agent steps,    │   │  /chat/completions,   │
                    │  long-term       │   │  /embeddings           │
                    │  memory)         │   └───────────────────────┘
                    └──────────────────┘
```

## 3. Multi-agent workflow (LangGraph)

```
   ┌─────────┐
   │ Planner │  reads the incident, decides which investigators to run
   └────┬────┘  and proposes initial hypotheses
        │  (conditional fan-out — only the selected agents run)
   ┌────┼──────────────┬──────────────────┬───────────────────┐
   ▼    ▼              ▼                  ▼                    ▼
┌──────────┐  ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│Log        │  │Metrics          │  │Deploy             │  │Runbook            │
│Analyst    │  │Analyst          │  │Correlator         │  │Retriever (RAG)    │
└─────┬─────┘  └────────┬────────┘  └─────────┬─────────┘  └─────────┬─────────┘
      └─────────────────┴───────────┬──────────┴────────────────────┘
                                     ▼
                            ┌─────────────────┐
                            │  Synthesizer     │  ranks hypotheses, cites
                            │                  │  evidence, sets confidence
                            └────────┬─────────┘
                                     ▼
                            ┌─────────────────┐
                            │  Remediation     │  PROPOSES an action only —
                            │  (propose only)  │  never executes
                            └────────┬─────────┘
                                     ▼
                     [ Human SRE/admin approval gate — service layer ]
                                     ▼
                     RemediationActionsTool executes + writes AuditLog
```

Why this is genuine planning and not a fixed pipeline: the Planner's output
(`investigation_plan`) determines which of the four investigator nodes actually
run via a LangGraph conditional edge — a disk-full alert doesn't need deploy
correlation, a cascading timeout might need all four. The graph topology adapts
per-incident.

## 4. Why each component exists (judging-criteria mapping)

| Component | User problem it solves | Judging criterion |
|---|---|---|
| Planner + conditional fan-out | Avoids wasting GPU cycles investigating irrelevant angles | Planning, GPU efficiency |
| Parallel investigator agents | Cuts wall-clock investigation time vs. sequential | Multi-agent reasoning, autonomous execution |
| Evidence rows (not just LLM prose) | Every claim traces to a citable fact | Explainability |
| Synthesizer confidence scoring | SRE knows how much to trust the conclusion | Explainability, reliability |
| Human approval gate on remediation | The one production-touching action is never fully autonomous | Reliability, enterprise usefulness |
| MemoryService (pgvector) | System gets better at recognizing repeat incidents | Long-term memory |
| RBAC (Role enum + require_role) | Only SREs/admins can approve remediation | Enterprise usefulness, security |
| AuditLog | Every remediation action is attributable and reviewable | Enterprise usefulness, compliance |
| Local vLLM/ROCm inference | Logs/secrets never leave the enterprise network | The entire reason local GPU inference is load-bearing, not decorative |
| Streaming + concurrency semaphore | Bounded VRAM usage under concurrent multi-agent load | ROCm optimization, GPU efficiency |
| Benchmark script + dashboard | Judges can see real tokens/sec and GPU utilization numbers | Performance benchmarking, transparent metrics |

## 5. Data model (ER diagram)

```
users ──< incidents >── agent_runs ──< agent_steps
  │            │
  │            └──< evidence
  │
  └──< audit_logs

memory_records  (standalone — pgvector similarity search, not FK-linked
                 to a single incident; a memory can be cited by many)
```

## 6. Known limitations / honest upgrade paths

- **Remediation approval is service-layer, not LangGraph-checkpointed.** A
  durable Postgres-backed LangGraph checkpointer would let the *entire graph*
  (not just the remediation step) pause and resume across hours/days. The
  current design (remediation only proposes; execution is a separate
  explicitly-approved service call) is simpler and equally safe, but doesn't
  let an approval resume mid-investigation state — acceptable since
  investigation and remediation are conceptually separate steps here.
- **Log/metrics/deploy tools target reference backends** (local JSONL files,
  Prometheus, GitHub Deployments API) as the integration pattern; a real
  deployment swaps these for Splunk/Elasticsearch/Datadog/ArgoCD clients
  behind the same `BaseTool` interface — no agent code changes required.
- **rocm-smi-based GPU sampling in the benchmark script** requires a real
  ROCm host; it degrades gracefully (reports `gpu_metrics_available: false`)
  on non-AMD hosts rather than fabricating numbers.
