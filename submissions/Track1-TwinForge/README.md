# Track 1 — TwinForge (Team TwinForge)

**Application:** TwinForge — an open, self-hostable AI digital-human video creation studio whose
core generation runs locally on an AMD Radeon GPU via ROCm.

**Track:** Track 1 — Development of Multimodal Content Creation Tools
**Core creation task:** Text/Image → talking-human video (image-to-video + voice cloning + lip-sync)
**Deliverable form:** Web UI

## Repositories
- **App tier (Next.js studio):** https://github.com/dukemawex/twinforge
- **This submission folder:** materials + ROCm inference server (see below)

## Submission materials (per Track 1 Rules & Conditions)
| Requirement | File / Location | Status |
|---|---|---|
| Project Profile Document (PDF) | `PROJECT_PROFILE.md` → `PROJECT_PROFILE.pdf` | Draft ready |
| Project Source Code | `dukemawex/twinforge` (app) + `gpu-server/` (ROCm) | App done; ROCm WIP |
| README (env, startup, deps) | this file + `gpu-server/README.md` | In progress |
| Demo Video (3–5 min, real Radeon GPU run) | link TBA | Pending GPU access |
| Supplementary: PPT / Poster | `assets/` | Pending |

## Architecture (hybrid)
1. **App tier** — frontend, auth, Postgres, blob storage, job queue, GPU proxy + webhook. No inference.
2. **GPU inference tier (ROCm on AMD Radeon)** — PyTorch FastAPI server implementing:
   `POST /twins/train`, `GET /twins/:jobId/status`, `POST /render`, `POST /render/batch`,
   `GET /system/gpu-status`. This is where the scored local inference runs.

## Running the ROCm inference server on Radeon Cloud (planned)
1. Radeon Cloud → Profile → Add Template → ROCm PyTorch container image → Launch.
2. In the JupyterLab terminal (or via SSH): clone this repo, `pip install -r gpu-server/requirements.txt`.
3. `python gpu-server/server.py` — starts the FastAPI server on `0.0.0.0:8000`.
4. Set `GPU_API_BASE_URL` in the TwinForge app to the instance's Base URL; set the shared webhook secret.
5. Verify `GET /system/gpu-status` returns the live AMD Radeon GPU + ROCm version.

## Why this satisfies the rules
- **At least one key inference process runs locally on AMD Radeon GPU** — face animation, voice
  cloning, and lip-sync render execute on the Radeon GPU in the ROCm PyTorch server.
- **No sole reliance on closed online APIs** — core generation uses open-source models locally;
  only the optional script assistant uses the Radeon-served (open) model API.
- **Complete input → processing → output workflow** — upload → GPU render → downloadable MP4.
