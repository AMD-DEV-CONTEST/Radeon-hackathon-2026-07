# FluxReel — AMD Hackathon Short-Video Studio

CLI tool + web UI to turn a one-line topic into a **15-second vertical short video**
(1080×1920, 9:16, 30 fps) — running the core image generation on an **AMD Radeon
GPU (ROCm)**. Also manages the AMD GPU remote server: tunnel setup, model
downloads, and system info.

**Track 1 — Multimodal Content Creation Tools** · AMD AI DevMaster Hackathon 2026-07

## Features

- 🎬 **Topic → 15 s video in minutes**: LLM drafts a markdown article, a scene planner
  splits it into 5 scenes (titles / subtitles / image prompts), scene images are
  generated on the GPU, and ffmpeg assembles the final vertical MP4 with background music.
- 🌐 **Bilingual captions** — auto-detects the topic's language (EN / 中文), with
  CJK-aware fonts (Noto Sans CJK) and character-based text wrapping.
- 🖥️ **Multiple image backends** (switchable per job):
  - `local` — PyTorch ROCm + diffusers, FLUX.1-schnell / dev / 2-dev on the AMD GPU
  - `sdcpp` — stable-diffusion.cpp, FLUX.1-schnell **Q4_0 GGUF** (4-bit, low VRAM)
  - `openrouter` — cloud FLUX (optional convenience; never required for the core)
  - `auto` — try local first, fall back to OpenRouter
- 🌸 **Web UI + REST API** (`fluxreel server`) with job queue, progress polling,
  video preview, and download.
- ▶️ **Optional YouTube upload** with auto-generated title / description / tags
  (public / private / unlisted).
- 🔌 Remote server management: rc-tunnel, FLUX model downloads via `hf-mirror.com`
  (China-friendly), GPU / ROCm / disk info, remote inference.

## Install

```bash
pip install -e .
```

## Quick Start

```bash
fluxreel server --port 8000            # start web UI + API (http://localhost:8000)
fluxreel img "a cyberpunk city at night"   # local image via sd-cpp (no server needed)
fluxreel gen-video video notes/foo.md --provider sdcpp   # video straight from markdown
fluxreel download flux --token hf_xxx   # fetch FLUX models to the AMD GPU host
fluxreel info                           # GPU / ROCm / disk check
```

## Usage

### 🎬 Video generation — web UI + REST API

Start the FastAPI server (embedded SPA frontend at `/`, job queue, provider
selector, video preview):

```bash
fluxreel server                 # 0.0.0.0:8000
fluxreel server --port 8000 --reload
# alias: fluxreel gen-video server
```

API endpoints:

| Endpoint | Description |
|---|---|
| `GET /` | Frontend UI |
| `POST /api/generate-content` | Generate markdown content from a topic |
| `POST /api/generate-video` | Submit a video job (returns `job_id` immediately) |
| `GET /api/jobs/{job_id}` | Query job status |
| `GET /api/jobs/{job_id}/download` | Download the finished MP4 |
| `GET /api/jobs` | List all jobs |
| `POST /api/check-key` | Validate an OpenRouter API key |
| `GET /health` | Health check (also lists available local models) |

### 🎬 Video generation — CLI

```bash
# Directly from a markdown file (fully local pipeline)
fluxreel gen-video video notes/2026-07-20-gpu.md
fluxreel gen-video video notes/gpu.md --provider sdcpp     # sd-cpp images
fluxreel gen-video video notes/gpu.md --provider local --local-variant dev
fluxreel gen-video video notes/gpu.md --provider openrouter
fluxreel gen-video video notes/gpu.md --output out.mp4 --upload   # + YouTube

# Via the server (reads markdown from the pasteboard)
export GEN_VIDEO_SERVER_URL=http://localhost:8000
fluxreel gen-video generate            # submit pasteboard content → job_id
fluxreel gen-video generate --poll     # wait, then download
fluxreel gen-video generate --upload --privacy unlisted

# Query a job
fluxreel gen-video query ab12cd34
fluxreel gen-video query ab12cd34 --json
```

Options: `--model` (LLM), `--image-model` (OpenRouter image model,
default `black-forest-labs/flux.2-pro`), `--provider {openrouter|local|sdcpp|auto}`,
`--local-variant {schnell|dev|2-dev}`, `--output`, `--server`, `--poll`,
`--upload`, `--privacy {public|private|unlisted}`.

### 🖼️ Local image generation — sd-cpp FLUX (this machine, no server needed)

```bash
# Generate an image locally with FLUX.1-schnell Q4_0 via stable-diffusion.cpp
fluxreel img "a cyberpunk city at night, neon reflections"
fluxreel img "a dragon on a castle tower" --width 1024 --height 1024   # needs free VRAM
fluxreel img "cat" --steps 4 --output cat.png --seed 7
```

Defaults to 960×720 (4:3 — the desktop holds ~2.9 GB of the 12 GB RTX 4070, so
1024×1024 needs Chromium/Slack closed). Overrides: `--width`, `--height`,
`--steps`, `--max-vram`, `--seed`, `--bin`, `--model-dir`, or env vars
`SDCPP_BIN`, `SDCPP_MODEL_DIR`, `SDCPP_WIDTH`, `SDCPP_HEIGHT`, `SDCPP_STEPS`,
`SDCPP_MAX_VRAM`, `SDCPP_BACKEND`.

### 🌐 Remote FLUX inference (AMD GPU server)

```bash
fluxreel gen "a cyberpunk city at night"          # 1024×1024, 4 steps, schnell
fluxreel gen "a dragon" --model dev --steps 28 --download   # + fetch the PNG
fluxreel gen "cat" --width 768 --height 768 --output cat_remote.png
```

Uses the diffusers `FluxPipeline` on the remote server (`/root/FLUX.<variant>`).
Options: `--model {schnell|dev|2-dev}`, `--steps`, `--width`, `--height`,
`--guidance`, `--output`, `--download`, `--model-dir`.

### 🔌 Tunnel — Expose a local port to the internet

```bash
# Set up the rc-tunnel (expose port 8081)
fluxreel tunnel setup

# Check tunnel status
fluxreel tunnel status

# View tunnel logs
fluxreel tunnel logs

# Stop the tunnel
fluxreel tunnel stop
```

### 📥 Download models

```bash
# Download FLUX.1-schnell (default, ~58 GB)
fluxreel download flux --token hf_xxxxx

# Download FLUX.1-dev (~69 GB)
fluxreel download flux dev --token hf_xxxxx

# Download FLUX.2-dev (~177 GB)
fluxreel download flux 2-dev --token hf_xxxxx

# Or set env var instead of --token
export HF_TOKEN=hf_xxxxx
fluxreel download flux
```

Downloads run in a background tmux session (`flux-download`) via `hf-mirror.com`,
monitor with `fluxreel check`.

### ℹ️ System Info

```bash
# Show GPU, PyTorch, disk, memory
fluxreel info

# Check download progress (FLUX dirs, incomplete files, tmux/process)
fluxreel check

# Run any command on the remote server
fluxreel shell nvidia-smi
# or
fluxreel shell "df -h && free -h"

# Open interactive SSH session
fluxreel ssh
```

### ▶️ YouTube upload

When `--upload` is used, metadata (title / description / tags) is auto-generated
via LLM and the MP4 is uploaded through the YouTube Data API v3.

Setup (one-time):

1. Go to <https://console.cloud.google.com/>, enable **YouTube Data API v3**
2. Create OAuth 2.0 credentials (Desktop app type)
3. Save the JSON as `~/.google/client_secret.json`

## Configuration

All env vars can live in `~/.config/fluxreel/.env` (loaded automatically):

| Env var | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter key (LLM script/scene planning + optional cloud images) |
| `MODEL` | LLM model for script generation (default: `openrouter/auto-beta`) |
| `GEN_VIDEO_SERVER_URL` | Server URL for `gen-video generate/query` |
| `HF_TOKEN` | HuggingFace token for `download` |
| `SDCPP_BIN` / `SDCPP_MODEL_DIR` | sd-cpp binary / models dir for `img` |
| `SDCPP_WIDTH` / `SDCPP_HEIGHT` / `SDCPP_STEPS` / `SDCPP_MAX_VRAM` | sd-cpp generation defaults |
| `SDCPP_BACKEND` | sd-cpp `--backend` string (set empty to omit — needed for Vulkan builds) |

## Deployment (remote AMD GPU host)

[Fabric](https://www.fabfile.org/) is used to sync the source tree to the remote
server and `pip install -e .` it:

```bash
pip install fabric
fab -H 36.150.116.206:31005 deploy     # rsync → /root/fluxreel → install
fab -H 36.150.116.206:31005 status     # deployed version + package info
fab -H 36.150.116.206:31005 shell -- cmd="nvidia-smi"
```

## Defaults

| Setting | Default |
|---------|---------|
| Host | `36.150.116.206` |
| Port | `31005` |
| User | `root` |
| Image provider | `openrouter` (`black-forest-labs/flux.2-pro`) |
| Local FLUX variant | `schnell` |
| Server bind | `0.0.0.0:8000` |
| Video format | 1080×1920 @30fps H.264, 5 slides × 3 s, background music + fade-out |

Override host with `--host`, `-p`/`--port`, `--user`.

## How it works

1. **Script** — LLM drafts a 300–500 word markdown article from a topic, then a
   scene planner produces exactly 5 scenes with `title` / `subtitle` / `image_prompt`
   (bilingual, auto-detected from the topic).
2. **Images** — 5 scene images (4:3) generated in parallel on the selected provider:
   AMD GPU via diffusers (FLUX.1-schnell/dev/2-dev), stable-diffusion.cpp
   (FLUX.1-schnell Q4_0 GGUF, VAE tiling, `--max-vram` budget), or OpenRouter.
3. **Compose** — PIL builds each 1080×1920 slide: 4:3 image centered, bold title /
   subtitle bars, fonts auto-shrunk to fit, CJK-aware wrapping.
4. **Assemble** — ffmpeg encodes each slide to a 3 s H.264 segment, concatenates
   without re-encode, and mixes in background music (`bg.mp3`) with a fade-out.
5. **Optional upload** — title/description/tags auto-generated, uploaded to YouTube
   (public / private / unlisted).

Remote management commands (tunnel, download, info, check, shell) all SSH into the
server (`rc-tunnel` FRP-based exposure; `hf-mirror.com` + tmux background downloads).

## Project layout

```
fluxreel/
├── cli.py                    # main CLI (tunnel, download, gen-video, img, gen, server, info…)
├── env.py                    # loads ~/.config/fluxreel/.env
├── llm/openrouter_client.py  # OpenRouter chat client
└── gen_video/
    ├── server.py             # FastAPI server + embedded web UI
    ├── video.py              # full pipeline: scenes → images → slides → ffmpeg
    ├── generate.py           # pasteboard → server submit (+ poll/download)
    ├── query.py              # job status query
    ├── youtube_upload.py     # YouTube Data API v3 upload
    ├── youtube_set_privacy.py
    ├── bg.mp3                # background music track
    └── providers/
        ├── factory.py        # provider registry
        ├── base.py           # ImageProvider ABC
        ├── local_provider.py # diffusers FLUX on AMD GPU (ROCm)
        ├── sd_cpp_provider.py# stable-diffusion.cpp FLUX Q4_0
        └── openrouter_provider.py
fabfile.py                    # Fabric deployment to the remote host
submission/                   # hackathon package (spec, slides, demo script)
```

## Dependencies

- Python ≥ 3.10; `requests`, `Pillow`, `python-dotenv`, `pyperclip`, `fastapi`,
  `uvicorn[standard]` (see `pyproject.toml`)
- `ffmpeg` / `ffprobe` for video assembly
- Optional: `torch` (ROCm build) + `diffusers` for the local GPU provider;
  stable-diffusion.cpp `sd-cli` for the sd-cpp provider;
  `google-api-python-client` + `google-auth-oauthlib` for YouTube upload
