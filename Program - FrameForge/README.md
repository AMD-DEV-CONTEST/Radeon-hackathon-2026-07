# FrameForge

A deployable web app for image-to-video generation with support for both
cloud APIs (Replicate) and **local GPU inference** on NVIDIA (CUDA) and
AMD (ROCm/DirectML) hardware.

## Features

- **Dual backend**: Replicate cloud API *or* local GPU execution
- **AMD ROCm support**: Radeon GPUs on Linux via ROCm
- **AMD DirectML support**: Radeon GPUs on Windows via DirectML
- **NVIDIA CUDA support**: GeForce/Quadra GPUs
- **Local inference pipeline** with automatic backend detection
- **Higgsfield.ai-esque UI** with cyberpunk aesthetic
- **Motion presets** for camera movement
- **Dimension auto-correction**
- **Job queue** with live status polling

## Architecture

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

## Setup

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

#### Option A: Replicate Cloud (default)

```bash
export REPLICATE_API_TOKEN="r8_..."    # or add to .env
uvicorn app.main:app --reload --port 8000
```

#### Option B: Local GPU Execution

**NVIDIA CUDA (Linux/Windows):**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
uvicorn app.main:app --reload --port 8000
```

**AMD ROCm (Linux):**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
uvicorn app.main:app --reload --port 8000
```

**AMD DirectML (Windows):**
```bash
pip install torch-directml onnxruntime-directml
uvicorn app.main:app --reload --port 8000
```

Enable local mode via environment variables:
```bash
export USE_LOCAL_GPU=true
export VIDEO_GENERATION_MODE=local
```

Or use settings in the UI.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. The Vite dev server proxies `/api/*`
requests to the backend on port 8000 automatically.

## Backend Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `REPLICATE_API_TOKEN` | `None` | Replicate API token for cloud mode |
| `VIDEO_GENERATION_MODE` | `auto` | `auto`, `replicate`, or `local` |
| `USE_LOCAL_GPU` | `false` | Force local GPU execution |
| `REPLICATE_MODEL` | LTX Video | Model ID for Replicate |

## Using it

1. Upload a source image.
2. Describe the subject/scene.
3. Pick a camera motion preset.
4. Click **Generate Video**. Status updates live; the finished video
   plays inline when done.

## What's real vs. what's next

**Working end-to-end right now:**
- Replicate API integration: submit prediction, poll status, download video
- Local GPU detection (CUDA/ROCm/DirectML)
- Dual backend execution (cloud or local)
- All 9 motion presets + custom prompt fallback
- Dimension/frame-count auto-correction
- Job status API + polling frontend
- Higgsfield.ai-esque cyberpunk UI

**Deliberately simple for this first pass:**
- In-memory job queue (single process, resets on backend restart)
- No auth/multi-user support

**Not yet built:**
- Batch upload / multi-job submission
- First/last-frame (FLF2V) mode
- A "send to remix" flow for trying a different preset on the same image
- Persistent job history across restarts
- Real local diffusion pipeline (currently stub)
