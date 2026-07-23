# FrameForge

Image-to-video generation, end to end: upload a still image, describe the
subject, pick a camera-motion preset, and get back a rendered clip. The
backend can drive either a hosted API ([Replicate](https://replicate.com),
running [LTX-Video](https://replicate.com/lightricks/ltx-video)) or local
GPU hardware — NVIDIA CUDA, AMD ROCm, AMD DirectML, or Apple MPS.

```
┌─────────────┐      HTTP        ┌──────────────┐      HTTPS       ┌───────────────┐
│   React UI   │ ──────────────▶│  FastAPI     │─────────────────▶│  Replicate    │
│ (Vite dev    │                 │  backend     │                  │  (LTX Video)  │
│  server)     │◀────────────── │  (job queue) │◀─────────────────│               │
└─────────────┘                 └──────────────┘                  └───────────────┘

                     OR (local GPU)

┌─────────────┐      HTTP        ┌──────────────┐      Local      ┌───────────────┐
│   React UI   │ ──────────────▶│  FastAPI     │─────────────────▶│  CUDA / ROCm  │
│ (Vite dev    │                 │  backend     │                  │  / DirectML   │
│  server)     │◀────────────── │  (job queue) │◀─────────────────│               │
└─────────────┘                 └──────────────┘                  └───────────────┘
```

> **Status note:** local GPU execution is detected and routed end to end,
> but the diffusion inference call itself (`video_pipeline.py`) is
> currently a stub. See [What's real vs. what's next](#whats-real-vs-whats-next).

---

## Table of contents

- [Features](#features)
- [Dependencies](#dependencies)
- [Environment configuration](#environment-configuration)
- [Startup guide](#startup-guide)
- [Using the app](#using-the-app)
- [API reference](#api-reference)
- [What's real vs. what's next](#whats-real-vs-whats-next)

---

## Features

- **Dual backend** — Replicate cloud API or local GPU execution, chosen by
  config or auto-detected at runtime
- **AMD ROCm support** — Radeon GPUs on Linux, detected via PyTorch's HIP
  compatibility layer
- **AMD DirectML support** — Radeon GPUs on Windows via `onnxruntime-directml`
- **NVIDIA CUDA support** — GeForce/Quadro GPUs
- **9 motion presets** (dolly, jib, orbit, handheld, static) plus a custom
  free-text motion option
- **Dimension & frame-count auto-correction** to LTX-Video's `32n+1` /
  `8n+1` requirements, with a human-readable adjustment note
- **In-browser draw canvas** as an alternative to uploading a file
- **Live job polling** — status updates in real time, video plays inline
  when done

---

## Dependencies

### Backend (Python)

| Package             | Version | Purpose                               |
| ------------------- | ------- | ------------------------------------- |
| `fastapi`           | 0.115.6 | Web framework / API routes            |
| `uvicorn[standard]` | 0.32.1  | ASGI server                           |
| `httpx`             | 0.28.1  | Async HTTP client (Replicate calls)   |
| `python-multipart`  | 0.0.20  | Multipart form parsing (image upload) |

Installed from `backend/requirements.txt`:

```bash
pip install -r requirements.txt
```

**Not included in `requirements.txt`** — only needed if you're running the
**local GPU** path, since the default cloud path never imports them:

| Package                              | When you need it                        |
| ------------------------------------ | --------------------------------------- |
| `torch`, `torchvision`, `torchaudio` | Any local GPU backend (CUDA, ROCm, MPS) |
| `onnxruntime-directml`               | AMD DirectML on Windows                 |
| `Pillow`                             | Local pipeline's image resizing step    |

Python **3.12** is what the included `__pycache__` artifacts were compiled
against; 3.10+ should work fine since nothing in the backend uses
version-specific syntax beyond that.

### Frontend (Node)

| Package                | Version        | Purpose                   |
| ---------------------- | -------------- | ------------------------- |
| `react`                | ^18.3.1        | UI library                |
| `react-dom`            | ^18.3.1        | React DOM renderer        |
| `vite`                 | ^6.0.5 *(dev)* | Dev server / bundler      |
| `@vitejs/plugin-react` | ^4.3.4 *(dev)* | React fast-refresh plugin |

Installed from `frontend/package.json`:

```bash
npm install
```

Node **18+** is recommended (Vite 6 requires it).

---

## Environment configuration

All backend configuration is read from environment variables in
`backend/app/core/config.py`. Nothing is required for local-GPU mode; only
`REPLICATE_API_TOKEN` is required for cloud mode.

| Variable                    | Default                           | Description                                                                                                                                                                        |
| --------------------------- | --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `REPLICATE_API_TOKEN`       | *(none)*                          | Your Replicate API token. Required for cloud mode. Get one at [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens).                                        |
| `REPLICATE_API_BASE`        | `https://api.replicate.com`       | Replicate API base URL. Only change this if you're proxying requests.                                                                                                              |
| `REPLICATE_API_VERSION`     | `v1`                              | Replicate API version path segment.                                                                                                                                                |
| `REPLICATE_MODEL`           | `lightricks/ltx-video:8c47da6...` | Which Replicate model handles the request. Accepts `owner/name` or `owner/name:version_hash`. Swap this to point at any other image-to-video model with a compatible input schema. |
| `REPLICATE_TIMEOUT_SECONDS` | `600`                             | Max time to wait on a single prediction before giving up.                                                                                                                          |
| `USE_LOCAL_GPU`             | `false`                           | Set `true` to force local GPU execution instead of Replicate.                                                                                                                      |
| `VIDEO_GENERATION_MODE`     | `auto`                            | `auto` (local if a GPU is detected, else Replicate), `replicate` (always cloud), or `local` (always local, error if no GPU).                                                       |
| `FRAMEFORGE_DATA_DIR`       | `./data`                          | Where uploaded images and rendered videos are stored on disk.                                                                                                                      |
| `FRAMEFORGE_POLL_INTERVAL`  | `2.0`                             | Seconds between backend polls of a Replicate prediction's status.                                                                                                                  |
| `FRAMEFORGE_MAX_CONCURRENT` | `2`                               | Max jobs submitted to Replicate at once.                                                                                                                                           |

### Setting them

**Option A — export directly:**

```bash
export REPLICATE_API_TOKEN="r8_..."
export VIDEO_GENERATION_MODE="auto"
```

**Option B — `.env` file** in `backend/` (no `.env` ships with the repo,
so create one):

```bash
# backend/.env
REPLICATE_API_TOKEN=r8_...
VIDEO_GENERATION_MODE=auto
```

**Option C — runtime, via the UI settings panel** (token and model only —
this calls `POST /api/settings` and updates the running process, but does
not persist across a restart).

**PowerShell** (Windows):

```powershell
$env:REPLICATE_API_TOKEN = "r8_..."
```

---

## Startup guide

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Pick **one** of the following depending on how you want jobs executed:

#### Option A — Replicate cloud (default, no GPU needed)

```bash
export REPLICATE_API_TOKEN="r8_..."
uvicorn app.main:app --reload --port 8000
```

#### Option B — Local GPU execution

**NVIDIA CUDA** (Linux/Windows):

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
export USE_LOCAL_GPU=true
export VIDEO_GENERATION_MODE=local
uvicorn app.main:app --reload --port 8000
```

**AMD ROCm** (Linux):

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
export USE_LOCAL_GPU=true
export VIDEO_GENERATION_MODE=local
uvicorn app.main:app --reload --port 8000
```

**AMD DirectML** (Windows):

```powershell
pip install torch-directml onnxruntime-directml
$env:USE_LOCAL_GPU = "true"
$env:VIDEO_GENERATION_MODE = "local"
uvicorn app.main:app --reload --port 8000
```

> Local GPU mode currently runs the full detection/routing path, but the
> render step itself is a stub — see the status note at the top of this
> file before relying on it for real output.

The backend starts on **`http://localhost:8000`**. Confirm it's up:

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Opens at **`http://localhost:5173`**. The Vite dev server proxies
`/api/*` to the backend on port 8000 automatically (see
`frontend/vite.config.js`) — no CORS setup needed in dev.

### 3. Verify

Open `http://localhost:5173`, upload an image, pick a motion preset, and
click **Generate Video**. If `REPLICATE_API_TOKEN` isn't set and you're
not in local-GPU mode, job submission will fail — set the token via the
in-app settings panel or an environment variable and retry.

### Production build (frontend)

```bash
cd frontend
npm run build      # outputs to frontend/dist
npm run preview    # serve the built assets locally to sanity-check
```

Serve `frontend/dist` behind whatever static host or reverse proxy you
use, and point it at a deployed instance of the FastAPI backend (update
the proxy target or add an explicit API base URL, since the dev-only Vite
proxy won't exist in the built output).

---

## Using the app

1. Upload a source image, or switch to the draw canvas and sketch one.
2. Describe the subject/scene in the prompt field.
3. Pick a camera motion preset (or choose **Custom** and write your own).
4. Click **Generate Video**. Status updates live via polling; the
   finished clip plays inline when the job completes.

---

## API reference

| Method | Route                      | Purpose                                      |
| ------ | -------------------------- | -------------------------------------------- |
| `GET`  | `/api/health`              | Liveness check                               |
| `GET`  | `/api/settings`            | Current token status, model, mode            |
| `POST` | `/api/settings`            | Update token/model at runtime                |
| `GET`  | `/api/gpu`                 | Detected local backend, device, fp16 support |
| `GET`  | `/api/presets`             | List of motion presets for the picker UI     |
| `POST` | `/api/jobs`                | Upload image + submit a render job           |
| `POST` | `/api/jobs/draw`           | Submit a render job from draw-canvas data    |
| `GET`  | `/api/jobs`                | List all jobs, most recent first             |
| `GET`  | `/api/jobs/{job_id}`       | Single job status                            |
| `GET`  | `/api/jobs/{job_id}/video` | Download/stream the finished video           |

---

## What's real vs. what's next

**Working end-to-end right now:**

- Replicate API integration: submit prediction, poll status, download video
- Local GPU *detection* (CUDA/ROCm/DirectML/MPS) and backend routing
- Dual backend execution (cloud or local) sharing one job-queue contract
- All 9 motion presets + custom prompt fallback
- Dimension/frame-count auto-correction
- Job status API + polling frontend
- Draw-canvas submission flow

**Deliberately simple for this first pass:**

- In-memory job queue (single process, resets on backend restart)
- No auth / multi-user support

**Not yet built:**

- The actual local diffusion pipeline — `video_pipeline.py` is currently a
  stub that returns a placeholder file; hooking in a real diffusers
  pipeline, local ComfyUI client, or equivalent is the main open item
- Batch upload / multi-job submission
- First/last-frame (FLF2V) mode
- A "send to remix" flow for trying a different preset on the same image
- Persistent job history across restarts
