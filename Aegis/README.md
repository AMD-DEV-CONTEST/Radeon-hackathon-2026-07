# Aegis — Autonomous Incident Commander

Aegis is a multi-agent, on-prem AI system that autonomously investigates and helps remediate
production incidents. It runs entirely on local AMD Radeon GPUs via ROCm + vLLM — no data,
logs, or secrets ever leave the enterprise network.

## Why Aegis exists

When production breaks, an on-call engineer manually correlates logs, metrics, deploy history,
and tribal knowledge from past postmortems — under pressure, often alone, often at 3am.
Aegis automates that investigation:

1. **Planner Agent** — decomposes an incident into testable hypotheses.
2. **Log Analyst / Metrics Analyst / Deploy Correlator agents** — investigate in parallel.
3. **Runbook Retriever** — RAG over historical postmortems and runbooks.
4. **Synthesizer Agent** — merges evidence into a ranked, cited root-cause hypothesis.
5. **Remediation Agent** — proposes/executes safe actions under RBAC + human-approval gates.
6. **Memory system** — every incident and its resolution is persisted, so future incidents
   retrieve precedent automatically.

Because incident data (logs, secrets, customer data, internal architecture) is some of the
most sensitive data an enterprise has, **cloud LLM inference is a non-starter for this use
case** — making local ROCm inference a hard product requirement, not a marketing checkbox.

## Repository layout

```
aegis/
├── backend/                 # FastAPI application (Clean Architecture)
│   └── app/
│       ├── core/            # config, logging, security, exceptions
│       ├── api/v1/          # versioned REST API
│       ├── db/              # SQLAlchemy models + session management
│       ├── schemas/         # Pydantic request/response contracts
│       ├── services/        # application/business logic layer
│       ├── agents/          # LangGraph agent definitions (Phase 6)
│       ├── inference/       # ROCm/vLLM inference engine client (Phase 10)
│       ├── memory/          # vector + episodic memory (Phase 7)
│       ├── tools/           # agent tool implementations (Phase 8)
│       └── workers/         # background task workers
├── frontend/                 # Next.js UI (Phase 12)
├── benchmarks/               # ROCm performance benchmark scripts + reports
├── deploy/                   # Docker/Compose/K8s deployment manifests
└── docs/                     # architecture, diagrams, ADRs
```

## Current status

All 17 planned phases are implemented and verified:

- [x] Phase 1 — Repository structure
- [x] Phase 2 — Backend infrastructure (FastAPI, config, logging, exceptions, DB session)
- [x] Phase 3 — Database & persistence (7 tables, pgvector, Alembic migration)
- [x] Phase 4 — Authentication & RBAC (JWT, role hierarchy)
- [x] Phase 5 — LangGraph orchestration (conditional multi-agent fan-out)
- [x] Phase 6 — Agent framework (7 specialist agents)
- [x] Phase 7 — Memory system (pgvector similarity + episodic)
- [x] Phase 8 — Tool framework (5 tools, RBAC-gated remediation)
- [x] Phase 9 — Enterprise RAG (chunking + ingestion pipeline)
- [x] Phase 10 — Local inference engine (ROCm/vLLM client, streaming, metrics)
- [x] Phase 11 — REST APIs (incidents, auth, knowledge, benchmarks, SSE)
- [x] Phase 12 — Frontend (Next.js, telemetry-console design, builds clean)
- [x] Phase 13 — Monitoring & observability (structured logs, Prometheus metrics)
- [x] Phase 14 — GPU benchmarking dashboard (script + API + frontend page)
- [x] Phase 15 — Testing (12 passing pytest tests, SQLite-backed, zero infra)
- [x] Phase 16 — Docker & deployment (docker-compose, ROCm vLLM service)
- [x] Phase 17 — Documentation (architecture, sequence diagram, ROCm setup, demo script)

See `docs/ARCHITECTURE.md` for the full system design and judging-criteria mapping,
`docs/DEMO_SCRIPT.md` for the live demo walkthrough, and `docs/ROCM_SETUP.md` to
get a real ROCm/vLLM server running.

## Quickstart

```bash
cp .env.example .env    # set SECRET_KEY
make up                 # builds and starts postgres, redis, vllm, backend, frontend
make migrate             # applies the Alembic schema
```

Frontend: http://localhost:3000 · API docs: http://localhost:8000/docs

## Running tests (no external infra required)

```bash
cd backend
pip install -r requirements.txt
python -m pytest tests/ -v   # 12 tests, SQLite in-memory, ~2s
```
