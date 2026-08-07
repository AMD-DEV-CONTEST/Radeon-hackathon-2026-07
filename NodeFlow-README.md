# NodeFlow — Infinite Canvas AI Stylization Workstation

> **AMD AI DevMaster Hackathon 2026 — Track 1: Multimodal AI**
> An AI image generation tool that runs natively on AMD Radeon GPUs (ROCm). Users sketch on an infinite canvas or type a text prompt, and diffusion models transform the input into stylized artwork in seconds.

---

## Table of Contents

- [Overview](#overview)
- [Demo Video](#demo-video)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
- [Quick Start](#quick-start)
- [Deployment Guide](#deployment-guide)
- [API Reference](#api-reference)
- [Models & LoRA](#models--lora)
- [License](#license)

---

## Demo Video

▶️ **`NodeFlow_Demo.mp4`** — the final 3–5 minute demo video for the AMD AI DevMaster Hackathon 2026 (Track 1).

It demonstrates the tool running natively on an AMD Radeon GPU (ROCm): canvas sketching, sketch-to-art, text-to-image, Fast/Expert dual-mode speed comparison, multi-model hot-switching, and LoRA tuning — with real generation timings shown on screen.

> The video file is stored in this repository. Download it from:
> `https://github.com/Eason-made-it/Radeon-hackathon-2026-07/blob/main/NodeFlow_Demo.mp4`

---

## Overview

**NodeFlow** is an AI image generation workstation running on AMD Radeon GPUs. It combines **infinite-canvas hand-drawing** with **diffusion-model text/image generation**: users can sketch freely on the canvas, or enter a text description, and receive a stylized image within seconds. The entire inference pipeline runs natively on the AMD Radeon PRO W7900 via the ROCm stack — **no NVIDIA CUDA dependency**.

NodeFlow's core philosophy is **low barrier to entry with high controllability**:

- For speed: **Fast mode** uses SDXL-Lightning 4/8-step distilled models for near-instant generation.
- For quality: **Expert mode** uses full models (FLUX.2-klein, NoobAI XL, Animagine XL, Illustrious XL) with adjustable steps, guidance scale, seed, negative prompts, and LoRA weights.

It avoids the steep learning curve of ComfyUI's node editor while offering more creative engagement than a plain text-to-image input box — the canvas itself is the creative space.

---

## Key Features

1. **Native AMD Radeon GPU Inference via ROCm** — The full pipeline runs on AMD GPUs using PyTorch (ROCm) and diffusers, demonstrating the viability of an open GPU ecosystem without NVIDIA CUDA.

2. **Canvas-Based Creative Interaction** — Draw sketches directly on an infinite Excalidraw canvas; AI transforms them into finished artwork. Lower barrier than ComfyUI nodes, more creative than a text box.

3. **Dual-Mode: Fast & Expert** — Fast mode delivers near-instant results with distilled models; Expert mode provides high-fidelity output with full parameter control. One product covers both rapid previewing and final-quality rendering.

4. **Multi-Model Hot-Switching + LoRA** — Switch between base models on the fly. Adjust LoRA weights in real time. Users control "who draws" (model) and "how it's drawn" (style/LoRA), putting creative control in the user's hands.

5. **8 Style Presets** — Cyberpunk, Anime, Watercolor, Oil Painting, 3D Render, Pixel Art, Concept Art, Minimalist — each with a professional prompt prefix automatically appended by the backend.

6. **Built-in Model Store** — Browse and download popular checkpoints and LoRAs from HuggingFace and Civitai directly within the app.

---

## Tech Stack

| Layer | Technology | Version | License |
|-------|-----------|---------|---------|
| Frontend | React + Excalidraw | React 18.3 / Excalidraw 0.17 | MIT |
| Build Tool | Vite | 5.4 | MIT |
| Backend | FastAPI + Uvicorn | FastAPI 0.115 | MIT |
| AI Inference | diffusers + transformers + accelerate | diffusers ≥0.38 | Apache 2.0 |
| Deep Learning | PyTorch (ROCm) | 2.12.0 | BSD-style |
| GPU | AMD Radeon PRO W7900 | 48 GB VRAM | — |
| Runtime | ROCm | 7.2.1 | MIT |

---

## System Architecture

```
Frontend (React 18 + Excalidraw Infinite Canvas)
   │  /api/*
   ▼
main.py (FastAPI Route Layer)
   ▼
engine.py (FluxEngine Facade → delegates to ModelManager)
   ▼
model_manager.py (ModelManager Singleton: load/switch/generate/LoRA)
   ▼
   ├── adapters/sdxl_adapter.py        (SDXL family: Lightning / Animagine / Illustrious / NoobAI)
   ├── adapters/flux2klein_adapter.py  (FLUX.2 Klein family: distilled / base)
   └── store_service.py                (Model Store: aggregates HF + Civitai)
```

### Key Design Decisions

- **Facade Pattern**: `engine.py` retains the `FluxEngine` class name as a thin facade, delegating all calls to `ModelManager`. Legacy code works without modification.
- **ModelManager Singleton**: Handles model load/unload/switch, text/image generation dispatch, LoRA management, and GPU status queries.
  - **Thread-safe**: `_generation_lock` ensures only one generation at a time; `_switch_lock` prevents concurrent switches.
  - **Rollback Protection**: On switch failure, automatically rolls back to the previous working model and restores LoRA state.
- **Adapter Pattern**: `ADAPTER_REGISTRY` maps architecture names to `SDXLAdapter` / `Flux2KleinAdapter`, each exposing a unified `load / generate_from_text / generate_from_image / load_lora / unload_lora` interface. Adding a new architecture only requires one new adapter.
- **Configuration Hub**: `config.py` centralizes `MODEL_REGISTRY`, `STYLE_PRESETS`, `RATIO_MAPPINGS` (SDXL 64-aligned / Flux 16-aligned), `LICENSE_INFO`, and `LORA_REGISTRY` — a pure data file referenced by all layers.

---

## Quick Start

### Prerequisites

- AMD Radeon GPU instance (tested on W7900 48 GB)
- ROCm runtime installed
- Python 3.12+
- Node.js 20+
- HuggingFace token (for gated model repos)

### One-Command Deployment

```bash
cd /workspace/ai-canvas
bash start.sh
```

The script automatically: checks environment → activates venv → installs backend deps → verifies PyTorch/ROCm → starts backend (:8000) → installs frontend deps → builds frontend (Vite) → starts frontend (:5173).

### Manual Step-by-Step

```bash
# 1. Activate persistent venv
source /persistent/venv/bin/activate

# 2. Set environment variables
export HF_ENDPOINT=https://hf-mirror.com
export HF_TOKEN=<your_hf_token>
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"
export HF_HOME=/persistent/hf_cache
export TRANSFORMERS_CACHE=/persistent/hf_cache
export DIFFUSERS_CACHE=/persistent/hf_cache

# 3. Install backend dependencies (torch already installed via ROCm wheel)
cd backend
pip install -r requirements.txt

# 4. Build frontend
cd ../frontend
npm install --legacy-peer-deps
npm run build

# 5. Start backend (preloads model + serves frontend static files)
cd ../backend
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Public Access

```bash
# On the GPU instance terminal
rc-tunnel expose --port 8000
# Outputs a public URL — open in browser
```

---

## Deployment Guide

### Persistent Storage

`/workspace` is a temporary disk — it gets wiped on instance reset. All critical data must live in `/persistent`:

| Path | Purpose |
|------|---------|
| `/persistent/venv` | Python virtual environment (saves re-downloading 4 GB+ ROCm PyTorch) |
| `/persistent/hf_cache` | HuggingFace model cache (saves re-downloading multi-GB models) |
| `/persistent/loras` | Downloaded LoRA files |

### Environment Variables (Required)

```bash
# HuggingFace mirror (instance cannot directly reach huggingface.co)
export HF_ENDPOINT=https://hf-mirror.com

# HuggingFace token (for gated repos)
export HF_TOKEN=<your_hf_token>
export HUGGING_FACE_HUB_TOKEN="$HF_TOKEN"

# Model cache path (persistent storage)
export HF_HOME=/persistent/hf_cache
export TRANSFORMERS_CACHE=/persistent/hf_cache
export DIFFUSERS_CACHE=/persistent/hf_cache
```

### Instance Reset Recovery

```bash
source /persistent/venv/bin/activate
export HF_ENDPOINT=https://hf-mirror.com
export HF_HOME=/persistent/hf_cache
export TRANSFORMERS_CACHE=/persistent/hf_cache
export DIFFUSERS_CACHE=/persistent/hf_cache
cd /workspace/ai-canvas/backend && pip install -r requirements.txt
cd /workspace/ai-canvas/frontend && npm install --legacy-peer-deps && npm run build
cd /workspace/ai-canvas/backend && uvicorn main:app --host 0.0.0.0 --port 8000 &
rc-tunnel expose --port 8000
```

### Frontend Development

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

Vite dev server runs on :5173 with hot reload. API requests to `/api/*` are proxied to the backend at `localhost:8000` (configurable in `vite.config.js`).

> **Note**: `npm install` requires `--legacy-peer-deps` due to peer dependency conflicts between Excalidraw and React 18.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Frontend page |
| `/api/info` | GET | API info (GPU / runtime / current model) |
| `/api/health` | GET | Health check (includes GPU VRAM status) |
| `/api/styles` | GET | Style preset list |
| `/api/models` | GET | Model list for a given mode (`?mode=fast\|expert`) |
| `/api/models/current` | GET | Currently loaded model |
| `/api/models/{id}/config` | GET | Model parameter config & supported ratios |
| `/api/models/switch` | POST | Switch model `{model_id}` |
| `/api/loras` | GET | Loaded LoRA list |
| `/api/loras/load` | POST | Load LoRA `{path, weight}` |
| `/api/loras/unload` | POST | Unload LoRA `{lora_id}` |
| `/api/store/models` | GET | Model store: popular checkpoints (`?source=hf`) |
| `/api/store/loras` | GET | Model store: popular LoRAs |
| `/api/store/download` | POST | Download model/LoRA to local storage |
| `/api/gpu/status` | GET | GPU VRAM status |
| `/api/generate/text2img` | POST | Text-to-image (JSON body) |
| `/api/generate/img2img` | POST | Image-to-image (multipart form) |

### Text-to-Image

```bash
POST /api/generate/text2img
Content-Type: application/json

{
  "prompt": "a futuristic city at sunset",
  "style": "cyberpunk",
  "width": 1024,
  "height": 1024
}
```

Response:

```json
{
  "status": "ok",
  "image": "data:image/png;base64,iVBORw0KG...",
  "prompt": "a futuristic city at sunset",
  "style": "cyberpunk"
}
```

### Image-to-Image

```bash
POST /api/generate/img2img
Content-Type: multipart/form-data

file: <PNG blob>       // Canvas export from Excalidraw
style: "cyberpunk"     // Style key
strength: 0.8          // Stylization strength (0.1–1.0)
```

### Error Handling

Backend errors return HTTP 4xx/5xx with:

```json
{"detail": "Error message description"}
```

---

## Models & LoRA

### Model Registry

| Model ID | Mode | Architecture | Description | License | Commercial |
|----------|------|-------------|-------------|---------|------------|
| `sdxl_lightning_4step` | fast | SDXL | SDXL-Lightning 4-step distilled (default fast model) | Open RAIL++-M | Yes |
| `sdxl_lightning_8step` | fast | SDXL | SDXL-Lightning 8-step distilled | Open RAIL++-M | Yes |
| `flux2klein_distilled` | expert | FLUX.2 | FLUX.2 Klein distilled (4-step, locked params) | Apache 2.0 | Yes |
| `flux2klein_base` | expert | FLUX.2 | FLUX.2 Klein base (50-step default, fully adjustable) | Apache 2.0 | Yes |
| `animagine_xl` | expert | SDXL | Animagine XL 4.0 (anime) | SDXL License | Yes |
| `noobai_xl` | expert | SDXL | NoobAI XL 1.0 (anime) | Fair AI | No |
| `illustrious_xl` | expert | SDXL | Illustrious XL (anime/illustration) | Fair AI | No |

### LoRA System

NodeFlow uses a **three-layer decoupled** LoRA design:

1. **Base (who draws)**: User explicitly selects model base (anime / realistic / general).
2. **Theme (how to draw)**: Selecting a style auto-appends the style prompt and loads the matching LoRA.
3. **LoRA weight**: Adjustable (0–2.0), enabling hybrid effects like "realistic base + anime LoRA".

LoRA download helper:

```bash
cd backend
python lora_downloader.py --list                              # List all LoRAs and download status
python lora_downloader.py                                     # Download all with URLs (skip existing)
python lora_downloader.py --id sdxl_detail_tweaker            # Download specific LoRA
```

> **Note**: SDXL-Lightning is a distilled model. LoRA weights should not be maxed out — general quality LoRAs at `default_weight × 0.7`, style LoRAs at `× 0.8` — to avoid noise artifacts.

---

## License

### Project Code

All project-developed code (frontend + backend) uses open-source components:

| Component | License |
|-----------|---------|
| React / React DOM | MIT |
| Excalidraw | MIT |
| Vite | MIT |
| FastAPI / Uvicorn | MIT |
| diffusers / transformers / accelerate | Apache 2.0 |

### Models & LoRAs

| Resource | License | Commercial Use |
|----------|---------|----------------|
| SDXL-Lightning (4/8-step) | Open RAIL++-M | Yes |
| FLUX.2-klein-4B | Apache 2.0 | Yes (retain copyright notice) |
| Animagine XL 4.0 | SDXL License | Yes |
| NoobAI XL 1.0 | Fair AI | No (competition demo = non-commercial) |
| Illustrious XL | Fair AI | No |
| Detail Tweaker XL (LoRA) | CDLA-Permissive-2.0 | Yes |
| FLUX.1-dev LoRAs | FLUX.1-dev Non-Commercial | No |

The UI displays license and commercial-use status for every model and LoRA, helping users stay compliant.

---

## Project Structure

```
ai-canvas/
├── backend/
│   ├── adapters/
│   │   ├── base_adapter.py          # Abstract adapter interface
│   │   ├── sdxl_adapter.py          # SDXL family adapter
│   │   └── flux2klein_adapter.py    # FLUX.2 Klein family adapter
│   ├── config.py                    # Model registry, styles, ratios, licenses, LoRA registry
│   ├── engine.py                    # FluxEngine facade (delegates to ModelManager)
│   ├── main.py                      # FastAPI app (routes + static file serving)
│   ├── model_manager.py             # ModelManager singleton (load/switch/generate/LoRA)
│   ├── store_service.py             # Model store (HF + Civitai aggregation)
│   ├── lora_downloader.py           # Batch LoRA download script
│   └── requirements.txt             # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  # Main React component
│   │   └── main.jsx                 # React entry point
│   ├── index.html                   # HTML template
│   ├── package.json                 # npm dependencies
│   └── vite.config.js              # Vite config (base: './', API proxy)
├── start.sh                         # One-command deployment script
├── setup.sh                         # Environment check script
└── README.md                        # This file
```

---

*NodeFlow — Where canvas inspiration becomes artwork on AMD GPUs.*
