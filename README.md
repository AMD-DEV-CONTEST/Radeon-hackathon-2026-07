# XiangLens

XiangLens is a private, source-backed profile-image agent built for **AMD AI DevMaster 2026, Track 2**. It reviews one to four candidate avatars against goals supplied by the user, finds visible privacy risks, retrieves contextual evidence, and remembers preferences only after explicit approval.

The project does not identify people or infer personality, intelligence, health, wealth, criminality, protected attributes, relationships, politics, religion, or destiny from an image.

## Current Implementation

- FastAPI application with permanent server credentials and short-lived browser access sessions;
- bounded LangGraph workflow with a visible nine-step plan and live node events;
- self-hosted llama.cpp chat-completions and multimodal adapter;
- local image validation, measurement, EXIF scanning, and optional QR scanning;
- 32 source-backed knowledge cards in Milvus Lite;
- opt-in runtime-only private Lens Tool for a locally mounted 24-lesson, 108-technique
  course distillation;
- deterministic dense development embeddings and optional CPU semantic embeddings;
- SQLite threads, messages, audit state, consent requests, and approved memories;
- validated visual, comparison, memory-proposal, and report schemas with one repair attempt;
- explicit one-to-four-image comparison with a privacy-first scoring rule;
- metadata-stripped safe-copy export and a complete user-state deletion route;
- English-only Nuxt workspace for upload, SSE progress, evidence, metrics, and memory consent;
- 120 open-license image fixtures with complete source manifests;
- offline tests that never substitute fake output into the production model path.

## Deployment Topology

The model is always a user-controlled open model served by llama.cpp on AMD Radeon and ROCm.

During Mac development:

```text
Mac FastAPI application
  -> private tunnel or authenticated URL
  -> user-controlled llama-server on Radeon/ROCm
```

For the competition submission and demo:

```text
GitHub Pages
  -> POST /api/v1/session on XiangLens FastAPI
  <- 10–30 minute Bearer token
  -> authenticated XiangLens API on the Radeon/ROCm machine
  -> http://127.0.0.1:8000/v1
  -> llama-server on the same Radeon/ROCm machine
```

The permanent application key stays on the FastAPI host. Each browser receives a random session
identity, and the backend scopes threads, memories, consent decisions, exports, and deletion to that
identity. A Cloudflare Worker may be placed in front for edge rate limiting, but is not required to
hold or expose the permanent key in the default FastAPI-issued flow.

The development URL is not a third-party AI service. However, the final same-host topology is important because Track 2 prohibits core inference through a remote API.

## Requirements

- Python 3.11, 3.12, or 3.13;
- [uv](https://docs.astral.sh/uv/) for the documented setup;
- Node.js 20 or newer and pnpm 11 for the web workspace;
- a user-controlled OpenAI-compatible llama.cpp endpoint for real analysis;
- AMD Radeon plus ROCm on the final inference machine.

The currently configured model is:

```text
mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K
```

## Setup

```bash
uv sync --extra dev
cp .env.example .env
cd apps/web
pnpm install
cd ../..
```

Set at least:

```env
XIANG_LLM_BASE_URL=https://YOUR-RADEON-ENDPOINT.example/v1
XIANG_LLM_API_KEY=replace-me
XIANG_LLM_MODEL=xianglens-qwen3.6-35b-a3b-fable5-q6k
XIANG_LLM_ENABLE_THINKING=true
XIANG_LLM_REASONING_BUDGET=2048
XIANG_AUTH_ENABLED=true
XIANG_APP_API_KEY=replace-with-a-long-random-value
XIANG_PUBLIC_SESSIONS_ENABLED=true
XIANG_ACCESS_TOKEN_TTL_MINUTES=20
XIANG_SESSION_ISSUE_LIMIT_PER_MINUTE=10
XIANG_ALLOWED_ORIGINS=https://ld0574.github.io
```

To mount the optional private Lens Tool, keep the source outside the repository and add:

```env
XIANG_PRIVATE_LENS_ENABLED=true
XIANG_PRIVATE_LENS_PATH=/secure/private/avatarKnowledge.ts
XIANG_PRIVATE_LENS_NAME=Private 108-Technique Lens
```

The backend extracts the existing TypeScript template-literal knowledge export at startup. It
never returns the source text to the browser, and the UI must opt in for each run. See
[Private Lens Tool](docs/PRIVATE_LENS_TOOL.md).

The application does not probe the model during startup unless `XIANG_LLM_PROBE_ON_START=true`.
Thinking mode remains enabled for the distilled model. Structured calls reserve 2,048 reasoning
tokens in addition to each node's final-content budget, so reasoning and final JSON do not compete
for the same allowance. The live endpoint accepted an 8,192-token reasoning budget, but the default
is lower to protect interactive latency. XiangLens validates only `message.content` and never
displays or persists `reasoning_content`. If the model still exhausts the combined output budget,
the client returns an explicit error.

## Build the Knowledge Database

The dependency-free hashing embedder is suitable for framework development and currently passes all eight smoke queries:

```bash
uv run python scripts/build_knowledge_db.py --provider hash
uv run python scripts/run_rag_smoke.py
```

For the final semantic configuration, install the optional embedding dependency, download the model once, and rebuild locally:

```bash
uv sync --extra semantic --extra dev
XIANG_EMBEDDING_PROVIDER=fastembed \
  uv run python scripts/build_knowledge_db.py --provider fastembed
```

Runtime retrieval does not require network access after the model artifacts are cached.

## Start the API

Start the API and web workspace in separate terminals:

```bash
./scripts/start_api.sh
./scripts/start_web.sh
```

Open `http://127.0.0.1:3000`. The frontend requests a short-lived session automatically; it never
asks for or stores `XIANG_APP_API_KEY`. Browser origins are restricted by
`XIANG_ALLOWED_ORIGINS`.

Useful endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Process health without a model request |
| `POST` | `/api/v1/session` | Issue a short-lived, visitor-scoped Bearer token |
| `GET` | `/api/v1/system/status?probe_model=true` | Deployment and model status |
| `POST` | `/api/v1/threads` | Create a conversation thread |
| `POST` | `/api/v1/threads/{id}/images` | Upload a JPEG, PNG, or WebP image |
| `POST` | `/api/v1/threads/{id}/runs` | Execute the complete agent graph |
| `POST` | `/api/v1/threads/{id}/runs/stream` | Execute the graph with live SSE node events |
| `GET` | `/api/v1/threads/{id}/state` | Restore images and recent messages |
| `GET` | `/api/v1/threads/{id}/runs` | List stored run results |
| `GET` | `/api/v1/runs/{run_id}` | Read one stored run result |
| `POST` | `/api/v1/threads/{id}/images/{image_id}/safe-copy` | Download a metadata-free JPEG |
| `POST` | `/api/v1/threads/{id}/memory-proposals` | Propose, but do not write, a memory |
| `POST` | `/api/v1/consents/{id}` | Approve or reject a memory write |
| `GET` | `/api/v1/memories?user_id=...` | List approved memories |
| `DELETE` | `/api/v1/memories/{id}?user_id=...` | Delete an approved memory |
| `DELETE` | `/api/v1/privacy/forget-me?user_id=...` | Delete all user threads, images, and memories |

The web application sends `Authorization: Bearer <short-lived-token>`. `X-App-API-Key` remains
available only for trusted operator scripts and must never be embedded in the frontend bundle.

Interactive API documentation is available at `http://127.0.0.1:8080/docs`.

## GitHub Pages Preview

The English Nuxt workspace can be generated as a client-side application and deployed by the
included GitHub Actions workflow:

```bash
cd apps/web
NUXT_APP_BASE_URL=/Radeon-hackathon-2026-07/ pnpm generate
```

The deployable artifact is `apps/web/.output/public`. The public page includes a static workspace
preview. Configure the repository Actions variable `XIANGLENS_API_BASE` with the public HTTPS URL of
FastAPI; the UI uses that build-time default and keeps the override under **Advanced settings**.
Preview mode keeps selected files inside the browser and never fabricates analysis output. Live
analysis still requires the FastAPI application; do not point the UI directly at llama-server.

## Test

```bash
uv run ruff check src tests scripts/build_knowledge_db.py scripts/run_rag_smoke.py
uv run pytest -q
cd apps/web
pnpm typecheck
pnpm build
```

Tests cover:

- the complete LangGraph node sequence;
- private Lens mounting, explicit opt-in, and safety-filtered output;
- structured-output repair, multi-image comparison, and memory-proposal rules;
- sensitive-inference policy blocking;
- real GPS and device EXIF fixture parsing;
- all eight RAG smoke queries;
- consent-before-memory-write and foreign-key-safe memory deletion;
- SSE lifecycle events, run recovery, CORS preflight, and API authentication;
- metadata-free safe-copy export and complete user-state deletion.

## Data

- `data/knowledge/cards.yaml`: 32 four-field retrieval cards;
- `data/knowledge/sources.yaml`: source registry;
- `data/fixtures/images/`: 120 actual 512-by-512 JPEG fixtures;
- `data/fixtures/manifest.yaml`: per-fixture labels, provenance, licenses, and hashes;
- `data/fixtures/source_manifest.yaml`: original Wikimedia Commons source metadata.

No fixture image was generated by an AI model.

Private course material is not part of the repository dataset. It is mounted by absolute path at
runtime and remains outside Git, the public Milvus corpus, screenshots, and distributed builds.

## Documents

- [Submission Package](submission/README.md)
- [Submission Brief](docs/SUBMISSION_BRIEF.md)
- [Submission Checklist](docs/SUBMISSION_CHECKLIST.md)
- [Demo Video Script](docs/DEMO_VIDEO_SCRIPT.md)
- [Local Development Guide](docs/LOCAL_DEVELOPMENT.md)
- [Production Deployment Guide](docs/PRODUCTION_DEPLOYMENT.md)
- [Private Lens Tool](docs/PRIVATE_LENS_TOOL.md)
- [Radeon Benchmark Protocol](benchmarks/README.md)
- [Reviewed W7900 Result](benchmarks/results/llama_cpp_w7900_optimized.md) — 87.09 ms median first
  generated delta, 83.42 tok/s median decode throughput, 11.92 s median end-to-end latency, and
  100% valid JSON across five warm multimodal runs.
- [Application Design](docs/XIANGLENS_APPLICATION_DESIGN.md)
- [Knowledge and Image Dataset Plan](docs/KNOWLEDGE_BASE_DATASET_PLAN.md)
- [Image Fixture Pack](data/fixtures/README.md)

## License and Attribution

Project-authored source code is intended for release under Apache-2.0. Knowledge-card and image rights are documented separately in `data/knowledge/LICENSE.dataset`, `data/fixtures/LICENSE.images`, and the two source manifests. Preserve per-file attribution when redistributing the image fixture pack.
