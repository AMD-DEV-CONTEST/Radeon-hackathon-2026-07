# Live-Science Web (frontend/backend split)

The **AMD Dev Contest 2026 · Track 1 (Multimodal Content Creation Tools)** web deliverable:
feeds teaching documents/concepts through a three-phase pipeline (Phase 1 program video + Bridge
route decision → Phase 2 FLUX keyframes → Phase 3 LTX video) to produce teaching animations or
short videos.

```
┌─────────────────────┐         ┌──────────────────────────────┐
│  React SPA (Vite)   │  /api   │  FastAPI backend             │
│  web/frontend/dist  │ ──────▶ │  - job queue (asyncio + worker)│
│  (dev: Vite proxy)  │ ◀────── │  - SQLite job store (JobStore)│
└─────────────────────┘  JSON   │  - engines: auto /            │
                                │    deterministic /            │
                                │    generative / procedural    │
                                └──────────────────────────────┘
```

## Directory layout

| Path | Description |
|---|---|
| `backend/app` | FastAPI app (API, services, job management) |
| `backend/requirements.txt` | Backend deps (includes repo-root deps: manim / Pillow, etc.) |
| `frontend/` | React + Vite + TypeScript frontend (SPA) |
| `frontend/dist/` | Frontend build output (served by the backend) |
| `backend/data/` | Runtime data (SQLite + job artifacts, gitignored) |

## Quick start

### 1. Backend

```bash
cd web/backend
python -m venv .venv && . .venv/bin/activate   # or reuse the repo-root .venv
pip install -r requirements.txt

# API only (frontend runs in its own dev server)
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# or also serve the built frontend (production mode)
LIVE_SCIENCE_SERVE_FRONTEND=1 python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `LIVE_SCIENCE_SERVE_FRONTEND` | `0` | When `1`, serve `frontend/dist` at `/` |
| `LIVE_SCIENCE_DATA_DIR` | `backend/data` | Runtime data dir (DB + artifacts) |
| `LIVE_SCIENCE_HOST` / `LIVE_SCIENCE_PORT` | `127.0.0.1:8000` | Listen address |
| `LIVE_SCIENCE_CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |
| `DEEPSEEK_API_KEY` | empty | DeepSeek key (required for auto/deterministic/generative Phase 1) |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | `https://api.deepseek.com` / `deepseek-chat` | Phase 1 LLM (OpenAI-compatible) |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | Local ComfyUI (FLUX/LTX model generation) |

### 2. Frontend (dev mode)

```bash
cd web/frontend
npm install
npm run dev        # http://localhost:5173, /api proxied to 127.0.0.1:8000
```

### 3. Frontend (production build)

```bash
cd web/frontend
npm install
npm run build      # outputs dist/, served by the backend with LIVE_SCIENCE_SERVE_FRONTEND=1
```

## API overview

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/health` | Service / GPU(ROCm) / engine availability |
| `POST` | `/api/v1/jobs` | Submit a generation job (`engine` + `text`) |
| `GET` | `/api/v1/jobs` | Job list (`?limit=&offset=`) |
| `GET` | `/api/v1/jobs/{id}` | Job status (progress / artifacts / manifest / error) |
| `GET` | `/api/v1/jobs/{id}/files/{name}` | Download artifact (mp4 / gif / manifest / keyframes) |

Interactive docs: `http://localhost:8000/docs`

## Rendering engines

| Engine | Implementation | Description |
|---|---|---|
| `auto` | Phase 1 → route | Decides from the final render: `programmatic` → program video, `realizable/hybrid` → FLUX+LTX model video |
| `deterministic` | Phase 1 (DeepSeek → program → render) | Generates a subtitled programmatic teaching video (MP4 + SRT + poster) |
| `generative` | Local ComfyUI (FLUX keyframes + LTX video) | Model video; needs AMD Radeon GPU + ROCm + ComfyUI |
| `procedural` | PIL programmatic renderer | Lightweight fallback GIF with no model dependency, always available |

Job state machine: `pending → running → completed / failed`. After a server restart, leftover
pending/running jobs are marked failed (`StaleJob`).

## Deploy to the public internet (Radeon Cloud)

Official Radeon Cloud exposes a public URL via `rc-tunnel`, and only **one port** can be exposed,
so a **single-port all-in-one deployment** is recommended (FastAPI serves both the API and the
frontend static assets):

```bash
cd web/backend
LIVE_SCIENCE_SERVE_FRONTEND=1 python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# in a separate terminal (Radeon Cloud environment)
rc-tunnel expose --port 8000
# → gives a public URL like https://rc-*.radeon.firstdg.ai
```

- Anyone can reach that public URL, so the app **must** enforce login before going public
  (the FastAPI layer uses a simple Bearer token; the frontend logs in and carries the token).
- `VITE_API_BASE` defaults to `/api/v1` (same origin), so single-port deployment needs no extra config.

## Track 1 compliance notes

- ✅ Web UI deliverable: React SPA + FastAPI, frontend/backend split
- ✅ Local inference: Phase 1 program video renders locally; model generation uses local ComfyUI
  (FLUX/LTX) — no closed online API dependency
- ✅ AMD Radeon GPU + ROCm: `generative` engine hooks into local ComfyUI; `/api/v1/health`
  reports GPU/engine availability
- ✅ Deliverables: source repo (this dir) + `competition.md` + demo video (generated with the
  deterministic/auto engine) + PPT/Poster

## Public deployment (Radeon Cloud rc-tunnel)

Per the official Radeon Cloud guide: the public URL is reachable from the internet, and the app
**must enforce login itself**. The system has built-in Bearer-token login: every `/api/*` route
(except `/api/v1/auth/login`) requires `Authorization: Bearer <token>`; the frontend shows only
the login page until authenticated.

### Prerequisites

- The notebook must be a **newly created** Pod (old Pods lack the `FRP_BROKER_URL` env var, so
  `rc-tunnel` cannot be installed). Verify: `env | grep FRP_BROKER_URL`.
- Each Pod can only expose one port → use all-in-one mode (backend serves the frontend, port 8000).

### One-command deploy

```bash
git clone https://github.com/HowardGuan24/Live-Document.git
cd Live-Science
bash web/deploy-public.sh
```

The script builds the frontend → starts the backend (auto-generating/reading the access token) →
installs `rc-tunnel` → exposes port 8000, then prints the public URL
(`https://rc-xxxx.radeon.firstdg.ai`) and the access token.

### Manual deploy

```bash
cd web/frontend && npm install && npm run build && cd ..
cd backend
LIVE_SCIENCE_AUTH_TOKEN=your-token LIVE_SCIENCE_SERVE_FRONTEND=1 \
  /path/to/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# new terminal:
$HOME/.local/bin/rc-tunnel expose --port 8000
```

- Token sources, in order: env var `LIVE_SCIENCE_AUTH_TOKEN`; otherwise auto-generated and persisted
  to `web/backend/data/auth_token.txt`.
- Artifact downloads (video/GIF) accept a `?access_token=` query param (browser `<video>/<a>` tags
  cannot send custom headers).
- For local development, set `LIVE_SCIENCE_AUTH_DISABLED=1` to turn off auth.
