# IndieGen Asset Studio

**A full-chain, multimodal AI asset generation platform for indie game developers.**

One text setting goes in; game-ready assets come out. Built on top of ComfyUI as
the GPU workflow engine, wrapped in a FastAPI backend and a browser UI, this
project turns a single written setting (for example *"a post-apocalyptic
wasteland bar"*) into a complete, style-consistent asset chain:

```text
Text setting (wasteland bar)
  |
  |-- W1  Concept art (image)
  |       `-- (human approval) --> W2  Depth map --> W3  PBR material set
  |
  |-- W4  Background music (MusicGen, e.g. dark industrial electronic)
  `-- W5  Ambient SFX (procedural: glass clinks, murmur, bar ambience)

W6  Sprite sheet: character sheet + action command --> PNG atlas + JSON config
W7  2D character --> 3D model (TripoSR, GLB/OBJ)
```

Every stage is conditioned on the same character sheet / setting so the whole
batch stays visually consistent — solving the "style drift between outsourced
vendors" problem that plagues small teams.

---

## 1. Workflows

| ID | Workflow | Input | Output | Key nodes / models |
|----|----------|-------|--------|--------------------|
| W1 | Concept art | Text setting | HD concept image | SDXL base + KSampler, fixed seed for reproducibility |
| W2 | Depth map | Concept image | Grayscale depth | MiDaS DPT-Hybrid (`comfyui_controlnet_aux` preprocessor) |
| W3 | PBR materials | Depth map | normal / height / roughness / metalness | Custom node `PBRFromDepth` (gradient-based) |
| W4 | Background music | Style prompt | MP3 | Custom node `MusicGenNode` (transformers MusicGen-small) |
| W5 | Ambient SFX | SFX type | MP3 loop / trigger | Custom node `ProceduralSFX` (glass clink, murmur, bar ambience) |
| W6 | Sprite sheet | Character sheet + action | PNG atlas + JSON config | Custom node `ActionPose` -> ControlNet OpenPose (SDXL) per-frame img2img -> `ImageGrid` |
| W7 | 2D -> 3D character | Character sheet | GLB/OBJ model | ComfyUI-Flowty-TripoSR (`TripoSR.ckpt`) |

## 2. Architecture

```text
Browser UI (web/index.html + app.js)
        |  HTTP / polling
FastAPI backend (server/app/main.py, port 8000)
        |  SQLite job records (server/data/jobs.db)
        |  HTTP /prompt /history /view
ComfyUI GPU engine (port 8188)
        |  workflows/*.json (API format) + custom nodes (nodes/indie_studio_nodes)
        `  output files -> served back through the backend proxy

Optional: Three.js scene viewer (web/scene.html) assembles one batch into an
interactive 3D wasteland bar with an automated bartender performance.
```

The backend proxies output files, so browsers only talk to port 8000 and never
need direct access to ComfyUI's 8188 port.

## 3. AMD Radeon GPU / ROCm support

The one-click setup script auto-detects your hardware:

- `nvidia-smi` present -> PyTorch **CUDA 12.8** wheels
- `/dev/kfd` or `rocminfo` present -> PyTorch **ROCm 7.1** wheels
  (`torch==2.11.0+rocm7.1`, `torchvision==0.26.0+rocm7.1`, `torchaudio==2.11.0+rocm7.1`)
- otherwise -> CPU wheels

Verified on an **AMD Radeon GPU (gfx1100 / 48 GiB VRAM)** with
`torch 2.11.0+rocm7.1` and ComfyUI 0.30.0. See
[docs/AMD_ROCm_EN.md](docs/AMD_ROCm_EN.md) for the adaptation details and the
measured performance table.

## 4. Environment configuration

**Tested environment**

| Component | Version |
|-----------|---------|
| OS | Ubuntu 24.04 (container), kernel 6.x |
| GPU | AMD Radeon (gfx1100), 48 GiB VRAM, ROCm 7.1 userspace |
| Python | 3.12 |
| PyTorch | 2.11.0+rocm7.1 |
| torchvision / torchaudio | 0.26.0+rocm7.1 / 2.11.0+rocm7.1 |
| ComfyUI | 0.30.0 |
| Backend | FastAPI 0.141.1, uvicorn, httpx, python-multipart |
| Frontend | Vanilla JS + Three.js (vendored, no CDN needed) |

**Model files** (not committed to git; see `docs/models.md`)

| Model | Use | Size |
|-------|-----|------|
| `sd_xl_base_1.0.safetensors` | W1/W6 SDXL base | ~6.5 GB |
| `sdxl_vae.safetensors` | SDXL VAE | ~320 MB |
| `dpt_hybrid-midas-501f0c75.pt` | W2/W3 depth | ~87 MB |
| MusicGen-small | W4 music | ~2.3 GB |
| `OpenPoseXL2.safetensors` | W6 ControlNet | ~4.7 GB |
| `TripoSR.ckpt` | W7 3D | ~1.6 GB |
| Helsinki-NLP `opus-mt-zh-en` | offline Chinese->English prompts | ~300 MB |

## 5. Quick start

```bash
# 1. Install ComfyUI + venv + custom nodes (auto-detects AMD/ROCm, NVIDIA/CUDA, CPU)
bash scripts/setup_comfyui.sh

# 2. Download models (resumable; uses hf-mirror by default, set HF=... to override)
bash scripts/download_models.sh        # W1/W2 models
bash scripts/download_musicgen.sh      # W4 music model
bash scripts/download_translator.sh    # offline zh->en translation
bash scripts/setup_3d.sh               # W7 TripoSR node (optional)
bash scripts/download_3d_model.sh      # W7 TripoSR weights (optional)

# 3. Start ComfyUI on 8188
cd ComfyUI && .venv/bin/python main.py --listen 0.0.0.0 --port 8188

# 4. Start the web app on 8000 (from the repo root)
bash server/run.sh

# 5. Open http://localhost:8000 in a browser
```

Or deploy everything at once on a host machine:

```bash
bash scripts/deploy_host.sh
```

This is idempotent and starts ComfyUI + the web app with logs in `logs/`.
For containerized web/nginx (ComfyUI stays on the host for GPU passthrough):

```bash
cd deploy && docker compose up -d --build
```

## 6. Using the web app

1. Pick a workflow (W1..W7).
2. Fill in the text/prompt parameters — **Chinese prompts are auto-translated to
   English offline** (MarianMT `opus-mt-zh-en`).
3. For image workflows, upload a local image or pick an image already on the
   server (input or output directory).
4. Give the batch a name (e.g. `wasteland_bar`); outputs are archived under
   `ComfyUI/output/<batch>/` with readable names.
5. Submit; the job list polls every 2 s; previews and downloads are served
   through the backend.
6. For W6, download the atlas + `sprite-config` JSON for direct engine import.
7. After a batch completes, click **Enter 3D scene** (`/scene.html?batch=...`)
   to assemble the assets into an interactive, auto-animated 3D bar.

## 7. Measured performance on AMD Radeon (ROCm)

Live run through the web API on this machine (`gfx1100`, 48 GiB VRAM,
`torch 2.11.0+rocm7.1`), sampled with `rocm-smi` every second:

| Workflow | Settings | Execution | Wall time | GPU peak | VRAM peak |
|----------|----------|-----------|-----------|----------|-----------|
| W1 concept | SDXL 1024x1024, 25 steps | 14.6 s | 15.3 s | 100 % | 9.6 GB |
| W2 depth | MiDaS 512 | 1.1 s | 7.7 s | 93 % | 12.2 GB |
| W3 PBR | 4 maps, strength 2.0 | 1.0 s | 1.6 s | 50 % | 12.2 GB |
| W4 music | MusicGen-small, 8 s | 9.6 s | 10.7 s | 100 % | 12.6 GB |
| W5 SFX | glass clink, 4 s | 0.04 s | 1.5 s | 0 % | 12.4 GB |
| W6 sprite | 8 frames SDXL 512x512, 20 steps | 20.9 s | 21.3 s | 100 % | 21.7 GB |

Reproduce anytime with:

```bash
./ComfyUI/.venv/bin/python scripts/benchmark_amd.py --out deliverables/perf/benchmark.json
```

## 8. Repository layout

```text
.
├── README.md / README_EN.md      # docs (EN + CN)
├── scripts/                      # setup, model download, deploy, benchmark
├── docs/                         # model manifest, AMD/ROCm notes, project profile
├── workflows/                    # ComfyUI API-format workflows W1-W7
├── nodes/indie_studio_nodes/     # custom nodes (PBRFromDepth, MusicGen, SFX, ActionPose, SaveMeshGLB)
├── server/                       # FastAPI backend + SQLite
├── web/                          # browser UI + Three.js scene
├── deploy/                       # docker-compose, nginx, systemd units
└── assets/demo/                  # generated demo batch (wasteland bar)
```

## 9. Dependency list

Backend (`server/requirements.txt`): `fastapi`, `uvicorn[standard]`, `httpx`,
`python-multipart`.

Custom nodes (`nodes/indie_studio_nodes`): `numpy`, `torch`, `scipy`,
`transformers` (MusicGen + MarianMT), `opencv-python` (ActionPose drawing).

ComfyUI + third-party nodes installed by `scripts/setup_comfyui.sh`:
`ComfyUI-DepthAnythingV2`, `comfyui_controlnet_aux`, `ComfyUI-Flowty-TripoSR`,
plus `ComfyUI-Essentials` (ImageGrid) when available.

## 10. Troubleshooting

- **ABI errors on start**: the setup script pins torch/torchvision/torchaudio to
  matching wheels; do not mix CUDA and ROCm wheels.
- **`/dev/kfd` present but ROCm not found**: install `rocm` userspace packages
  (`rocminfo`, `rocm-smi`) or run `bash scripts/setup_comfyui.sh` after ROCm is
  installed.
- **HF downloads slow**: the scripts use `hf-mirror.com` by default; set
  `HF=https://huggingface.co` for direct downloads.
- **WebGL unavailable**: `scene.html` automatically falls back to a 2D
  compatible mode.

## 11. Project deliverables

Track-1 deliverables generated from this repository (English):

| Deliverable | File |
|-------------|------|
| Submission index (requirement → file) | `deliverables/README.md` |
| Project profile PDF | `deliverables/Project_Profile_EN.pdf` |
| Supplementary PPT | `deliverables/Supplementary_Deck_EN.pptx` |
| Hands-on walkthrough | `docs/HANDS_ON_WALKTHROUGH_CN.md` |
| Demo video (3-5 min) | provided by the submitter; checklist in `deliverables/README.md` |
| Live benchmark data | `deliverables/perf/benchmark.json` + `.log` |

Deliverable generator scripts live in `deliverables/tools/`
(`render_profile_pdf.py`, `make_deck.py`) — edit the sources and re-run them to
regenerate the PDF / PPT.

---

Track: **Multimodal Content Creation Tools** · License: see repository history.
