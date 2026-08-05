# Local Development Guide

This guide starts the complete XiangLens application locally. The web UI and FastAPI application
run on the development machine; visual inference may run either on a remote user-controlled Radeon
server or on the same Radeon machine.

For the competition environment, see [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md).

## 1. Architecture

```text
Nuxt web UI                 http://127.0.0.1:3000
    -> XiangLens FastAPI    http://127.0.0.1:8080
        -> Milvus Lite      runtime/xianglens_milvus.db
        -> SQLite           runtime/xianglens.sqlite3
        -> Private Lens     optional external file, runtime-only
        -> llama-server     remote Radeon URL or http://127.0.0.1:8000/v1
```

The browser must connect to **XiangLens FastAPI**, not directly to `llama-server`.

## 2. Prerequisites

- Python 3.11, 3.12, or 3.13;
- [uv](https://docs.astral.sh/uv/);
- Node.js 20 or newer;
- pnpm 11;
- a running OpenAI-compatible `llama-server` with the multimodal model and projection loaded.

Verify the local tools:

```bash
python3 --version
uv --version
node --version
pnpm --version
```

The expected model is:

```text
mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K
```

See [REPRODUCE.md](REPRODUCE.md) for the Radeon/ROCm `llama.cpp` build and server commands.

## 3. First-Time Setup

Run these commands from the repository root:

```bash
uv sync --extra dev
cp .env.example .env
pnpm --dir apps/web install --frozen-lockfile
```

Generate a permanent application key. It stays in the local `.env` file and is never sent to the
browser:

```bash
openssl rand -hex 32
```

Edit `.env` and replace at least these values:

```env
XIANG_AUTH_ENABLED=true
XIANG_APP_API_KEY=paste-the-64-character-openssl-output-here
XIANG_PUBLIC_SESSIONS_ENABLED=true
XIANG_ACCESS_TOKEN_TTL_MINUTES=20

# Remote Radeon development:
XIANG_LLM_BASE_URL=https://YOUR-RADEON-TUNNEL.example/v1
XIANG_LLM_API_KEY=
XIANG_LLM_MODEL=mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K

# The local Nuxt origin must be present.
XIANG_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

The real hostname should be a normal `https://...` URL and must end in `/v1`.

If `llama-server` runs on the same Radeon machine, use:

```env
XIANG_DEPLOYMENT_MODE=submission-local
XIANG_LLM_BASE_URL=http://127.0.0.1:8000/v1
```

Check that the model endpoint is alive before starting XiangLens:

```bash
curl -fsS https://YOUR-RADEON-TUNNEL.example/v1/models
```

Use the model ID returned by `/v1/models` as `XIANG_LLM_MODEL` if it differs from the value above.

### Optional private Lens Tool

The existing 24-lesson, 108-technique distillation can be mounted directly from its external
TypeScript file. Do not copy it into this repository. Add the following to the local `.env`:

```env
XIANG_PRIVATE_LENS_ENABLED=true
XIANG_PRIVATE_LENS_PATH=/absolute/path/to/avatarKnowledge.ts
XIANG_PRIVATE_LENS_NAME=Private 108-Technique Lens
```

After startup, `/api/v1/system/status` should report `private_lens_available: true`. The UI exposes
an unchecked per-run opt-in. See [PRIVATE_LENS_TOOL.md](PRIVATE_LENS_TOOL.md) for the output and
copyright boundaries.

## 4. Build the Local Knowledge Database

The default hashing embedder requires no model download and is the fastest development option:

```bash
uv run python scripts/build_knowledge_db.py --provider hash
uv run python scripts/run_rag_smoke.py
```

Expected output includes:

```text
Built 32 cards in .../runtime/xianglens_milvus.db
All 8 RAG smoke queries passed.
```

For the final semantic configuration, install the optional embedder and rebuild once:

```bash
uv sync --extra semantic --extra dev
XIANG_EMBEDDING_PROVIDER=fastembed \
  uv run python scripts/build_knowledge_db.py --provider fastembed
```

The first FastEmbed build downloads the embedding model. Runtime retrieval is local afterward.

## 5. Start XiangLens

Open two terminals at the repository root.

Terminal 1 — FastAPI:

```bash
./scripts/start_api.sh
```

Terminal 2 — Nuxt:

```bash
./scripts/start_web.sh
```

Open:

- Web UI: <http://127.0.0.1:3000>
- API health: <http://127.0.0.1:8080/health>
- API schema: <http://127.0.0.1:8080/docs>

The web UI automatically calls `POST /api/v1/session`, stores only the short-lived Bearer token in
the current browser tab, and then checks the FastAPI/model status. The permanent application key
does not enter the frontend.

## 6. Command-Line Smoke Test

With FastAPI running:

```bash
curl -fsS http://127.0.0.1:8080/health

TOKEN="$(curl -fsS -X POST http://127.0.0.1:8080/api/v1/session \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')"

curl -fsS \
  -H "Authorization: Bearer $TOKEN" \
  'http://127.0.0.1:8080/api/v1/system/status?probe_model=true'
```

The status response should report:

- `model_configured: true`;
- `model_reachable: true`;
- `milvus_ready: true`.
- `private_lens_available: true` when the optional source is mounted.

## 7. Everyday Restart

After the first-time setup, the normal restart is only:

```bash
# Terminal 1
./scripts/start_api.sh

# Terminal 2
./scripts/start_web.sh
```

Rebuild Milvus Lite only when `data/knowledge/cards.yaml`, `data/knowledge/sources.yaml`, the
embedding provider, or the embedding model changes.

## 8. Run Checks

```bash
uv run ruff check src tests scripts/build_knowledge_db.py scripts/run_rag_smoke.py
uv run pytest -q
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
```

## 9. Troubleshooting

### The web page says `Access-session issuance is not enabled`

Confirm that `.env` contains all three settings and restart FastAPI:

```env
XIANG_AUTH_ENABLED=true
XIANG_PUBLIC_SESSIONS_ENABLED=true
XIANG_APP_API_KEY=a-random-value-with-at-least-32-characters
```

### The web page cannot connect to the API

- Confirm `curl http://127.0.0.1:8080/health` succeeds.
- Keep `NUXT_PUBLIC_API_BASE=http://127.0.0.1:8080` in `apps/web/.env` only if overriding the
  built-in development default.
- Confirm `http://127.0.0.1:3000` is listed in `XIANG_ALLOWED_ORIGINS`.
- Do not enter the Radeon `llama-server` URL in the web UI's advanced API setting.

### FastAPI returns `502` during analysis

- Confirm the configured URL ends in `/v1`.
- Check `/v1/models` on `llama-server`.
- Make `XIANG_LLM_MODEL` match the server's model ID.
- Confirm the multimodal projection is loaded by `llama-server`.
- Increase `XIANG_LLM_TIMEOUT_SECONDS` only if the server is reachable but inference is slow.

### The UI shows `Milvus unchecked` or retrieval returns no evidence

Rebuild the local database and restart FastAPI:

```bash
uv run python scripts/build_knowledge_db.py --provider hash
```

### Port 8080 or 3000 is already in use

Choose different application ports:

```bash
XIANG_PORT=8081 ./scripts/start_api.sh
XIANG_WEB_PORT=3001 ./scripts/start_web.sh
```

When changing the FastAPI port, set the web API base through the UI's **Advanced settings** or in
`apps/web/.env`:

```env
NUXT_PUBLIC_API_BASE=http://127.0.0.1:8081
NUXT_PUBLIC_RUN_TRANSPORT=stream
```

Add the new web origin to `XIANG_ALLOWED_ORIGINS`, for example
`http://127.0.0.1:3001`.

### Nuxt reports `Failed to resolve import "#app-manifest"`

This can happen after switching between a GitHub Pages static build and the development server.
Stop Nuxt, clear generated caches, and start it again:

```bash
pnpm --dir apps/web exec nuxt cleanup
./scripts/start_web.sh
```

## 10. Stop and Reset

Press `Ctrl+C` in both terminals to stop the processes.

Runtime state is stored under `runtime/`. To start with fresh application data, stop FastAPI first,
then move that directory to a backup location. Rebuild the knowledge database before the next
start. Do not delete or overwrite `runtime/` while FastAPI is running.
