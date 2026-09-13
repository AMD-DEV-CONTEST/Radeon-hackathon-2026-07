# Aegis — Presentation Outline

**Slide 1 — Title**
Aegis: the autonomous incident commander that never leaves your network.
Team name · AMD AI DevMaster Hackathon

**Slide 2 — The problem**
When production breaks, engineers manually correlate logs, metrics, deploys,
and tribal knowledge — under pressure, alone. Existing tools alert; none investigate.
*(Visual: a paged engineer at 3am juggling five dashboards)*

**Slide 3 — Why this hasn't been solved with cloud LLMs**
Incident data — logs, secrets, architecture — is too sensitive to send to a
cloud API for regulated industries (finance, healthcare, defense). This is
the one incident-response product category where local inference isn't a
nice-to-have; it's the entire unlock.

**Slide 4 — What Aegis does**
Planner → parallel investigator agents (logs, metrics, deploys, runbook
precedent) → Synthesizer with cited, confidence-scored root cause →
human-approved remediation. Fully autonomous investigation, human-gated action.
*(Visual: the agent graph diagram from docs/ARCHITECTURE.md)*

**Slide 5 — Live demo**
(Follow docs/DEMO_SCRIPT.md)

**Slide 6 — Explainability is structural, not bolted on**
Every claim traces to an Evidence row from a specific agent. Every remediation
action writes an AuditLog entry before executing. This isn't a chat transcript
— it's an audit trail.

**Slide 7 — AMD ROCm architecture**
vLLM on ROCm, fp16, prefix caching, bounded concurrency semaphore, streaming
tokens. Show the benchmark dashboard: real tokens/sec and GPU utilization
across concurrency levels — not claimed numbers.

**Slide 8 — Long-term memory**
pgvector-backed memory grows with every resolved incident. Show the Runbook
Retriever citing precedent found via cosine similarity search, not keyword match.

**Slide 9 — Enterprise readiness**
RBAC, audit logging, human approval gates, Clean Architecture, 12 passing
tests, Docker Compose deployment, Alembic migrations. This is a system a team
could adopt Monday, not a hackathon toy.

**Slide 10 — What's next**
Postgres-backed LangGraph checkpointing for multi-day approval flows;
production-vendor tool integrations (Splunk, Datadog, ArgoCD) behind the
existing `BaseTool` interface; fine-tuning the synthesis model on an
org's own historical postmortems.

**Slide 11 — Close**
Aegis: multi-agent reasoning, planning, tool orchestration, long-term memory,
and full explainability — running entirely on an AMD Radeon GPU.
