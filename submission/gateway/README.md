# omima Gateway — UnionAgents communication backbone

> Part of the omima submission (AMD AI DevMaster 2026, Track 2).
> Production-proven agent communication backbone: long-lived WebSocket presence/events/replay, agent registration, task dispatch, IronLaw pre-check — works even on cloud PCs with no port 22 and no public IP.

## Components

| Component | Language | Role |
|-----------|----------|------|
| `streaming_gateway/` | Python (FastAPI) | WebSocket gateway: presence, events, replay, agent registry |
| `orchestrator/` | Python | Task registry, session records, dispatch |
| `worker/` | Python | Hub worker, tool execution |
| `cmd/` | Go | Gateway binaries (`ils` CLI, brain, hermes-bridge) |
| `internal/` | Go | Core gateway logic: handler, uasclient, ironlaw |
| `iron_law/` | Python | Pre-execution permission checks (IronLaw) |
| `rag_service/` | Python | Local RAG for knowledge retrieval |
| `canvas/` `canvas-native/` | TS/React + Rust | Management UI (optional) |

## Dependencies

- **Go**: `github.com/gorilla/websocket`, `github.com/jackc/pgx/v5`, `github.com/xeipuuv/gojsonschema` (see `go.mod`)
- **Python**: `fastapi`, `uvicorn`, `psycopg`, `websockets`, `python-dotenv` (see `pyproject.toml`)
- **DB**: PostgreSQL (state / session / event replay)

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection |
| `GATEWAY_PORT` | Gateway WS/HTTP port (default 8001) |
| `ORCHESTRATOR_PORT` | Orchestrator HTTP port (default 8000) |
| `AUTH_USERNAME` / `AUTH_PASSWORD` / `AUTH_SECRET` | Gateway auth |

> Secrets are **not** committed. Create `.env` from `deploy/brain.env.example`.

## Quick start

```bash
# Python orchestrator + gateway
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
DATABASE_URL="postgresql://<user>:<pass>@127.0.0.1:5432/unionagents" \
  uvicorn orchestrator.main:app --host 127.0.0.1 --port 8000

# Go gateway
go build ./cmd/gateway && ./gateway --port 8001
```

## Notes

- This is the **communication backbone** of the omima star-network (Porphyrion protocol layer).
- Production deployment: ECS hosts; long-lived WS + event callbacks let heterogeneous nodes (different models/hardware/hosts) join one protocol domain even without public IP or port 22.
- For the full system description see `submission/docs/main-paper.en.md`.
