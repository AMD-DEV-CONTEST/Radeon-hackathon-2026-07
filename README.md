# ROCm-SDXL AI Creation Workbench

A lightweight, one-click reproducible, AMD ROCm-optimized AI image creation
workbench built on ComfyUI, with A1111 WebUI as a secondary interface. The
primary generation model is **SDXL 1.0 Base**.

- **Track**: Track 1 — Multimodal AI Content Creation
- **Runtime**: AMD Radeon GPU + ROCm (gfx1100, 48 GB VRAM)
- **Primary model**: `sd_xl_base_1.0.safetensors` (6.9 GB, sha256 `31e35c80...`)
- **Interfaces**: ComfyUI (8188) + A1111 WebUI (7860), both local-only, remote via SSH tunnel

> English README derived from the four Chinese deployment documents in
> `docs/` (see References below).

---

## 1. Overview

This project adapts ComfyUI for the AMD ROCm ecosystem. It solves the common
pain points developers hit when deploying AI image generation on AMD cloud
servers:

- complex environment adaptation
- VRAM scheduling differences vs. NVIDIA/CUDA
- port mapping / remote access
- ROCm-specific compatibility errors

All inference, loading and rendering happen locally on the AMD GPU. No
external API is used.

## 2. Hardware / Environment

| Item | Value |
| --- | --- |
| GPU | AMD Radeon Pro W7900D (`gfx1100`) |
| VRAM | 48 GB (`rocm-smi` total: 51522830336 B) |
| ROCm | 7.2.1 (rocm-smi lib 7.8.0) |
| OS | Ubuntu/Debian container, Python 3.12.3 |
| PyTorch | `2.9.1+rocm7.2.1` (shared env `/persistent/amd_ai_env`) |
| torchvision | `0.24.0+rocm7.2.1` |

## 3. Directory Layout

```
/workspace/ComfyUI                    ComfyUI main program (port 8188)
/workspace/stable-diffusion-webui     A1111 WebUI main program (port 7860)
/persistent/amd_ai_env                Shared ROCm torch env (torch, torchvision, torchaudio)
/persistent/webui_env                 A1111 WebUI venv (torch symlinked from amd_ai_env)
/persistent/comfyui/models            Model dir (checkpoints at top level)
```

Organized project deliverables (`sdxl_project/`):

```
sdxl_project/
├── scripts/            startup & deploy scripts (ComfyUI / WebUI / sshd / benchmark)
├── patches/            sd_disable_initialization.py patch + AMD ROCm compat notes
├── workflows/          SDXL txt2img ComfyUI workflow (API format)
├── docs/               the four Chinese deployment documents
├── demo/               screenshots, generated images, terminal & error logs
└── requirements_amd.txt  merged dependency list (amd_ai_env + webui_env)
```

## 4. Environment Setup

### 4.1 Shared ROCm torch environment (`amd_ai_env`)

This env holds the AMD build of PyTorch and is shared by both interfaces.

```bash
/usr/bin/python3.12 -m venv /persistent/amd_ai_env
# install ROCm PyTorch from the official ROCm index (do NOT pip install from PyPI)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.7
```

Export these for every shell / startup script:

```bash
export ROCM_PATH=/opt/rocm
export HSA_OVERRIDE_GFX_VERSION=11.0.0   # gfx1100 compatibility
```

### 4.2 A1111 WebUI venv (`webui_env`)

The WebUI venv **symlinks** the shared torch stack instead of reinstalling it.

```bash
/usr/bin/python3.12 -m venv /persistent/webui_env
/usr/local/bin/python3.12 -m venv /persistent/webui_env
/persistent/webui_env/bin/pip install --upgrade pip

ln -s /persistent/amd_ai_env/lib/python3.12/site-packages/{torch,torchvision,torchaudio,triton}* \
      /persistent/webui_env/lib/python3.12/site-packages/

/persistent/webui_env/bin/pip install --no-deps open-clip-torch==2.20.0
/persistent/webui_env/bin/pip install --no-deps git+https://github.com/openai/CLIP.git
```

`open-clip-torch` **must stay at 2.20.0**; 3.x breaks SDXL attention mask shapes.

### 4.3 Model placement

| Interface | Path |
| --- | --- |
| WebUI | `/workspace/stable-diffusion-webui/models/Stable-diffusion/` |
| ComfyUI | `/persistent/comfyui/models/` (via `extra_model_paths.yaml`) |

Share one file with a symlink (saves 6.9 GB):

```bash
ln -s /persistent/comfyui/models/sd_xl_base_1.0.safetensors \
  /workspace/stable-diffusion-webui/models/Stable-diffusion/sd_xl_base_1.0.safetensors
```

### 4.4 Model integrity

```bash
sha256sum /persistent/comfyui/models/sd_xl_base_1.0.safetensors
# 31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b  (matches official release)
```

## 5. Startup

### ComfyUI (port 8188)

```bash
bash /persistent/start_comfyui.sh        # start (listens on 127.0.0.1:8188)
tail -f /tmp/comfyui_run.log             # log
```

### A1111 WebUI (port 7860)

```bash
bash /persistent/start_webui.sh          # start
tail -f /tmp/webui_run.log               # log
pkill -9 -f '[p]ython webui.py'          # stop (note the [p] to avoid self-match)
```

### sshd

```bash
bash /persistent/start_sshd.sh
```

### Verify

```bash
curl -s -o /dev/null -w "ComfyUI %{http_code}\n" http://127.0.0.1:8188    # expect 200
curl -s -o /dev/null -w "WebUI %{http_code}\n"   http://127.0.0.1:7860    # expect 200
```

## 6. Dependencies

All dependencies of both environments are merged into
`requirements_amd.txt` (203 pinned packages). Key ones:

| Package | Version | Notes |
| --- | --- | --- |
| torch | 2.9.1+rocm7.2.1 | ROCm build, shared via symlink |
| torchvision | 0.24.0+rocm7.2.1 | ROCm build |
| torchaudio | 2.9.0+rocm7.2.1 | ROCm build |
| transformers | 4.40.2 | requires the sd_disable_initialization patch |
| open-clip-torch | 2.20.0 | A1111 fixed version, do not upgrade |
| clip | 1.0 | OpenAI CLIP, from git |
| triton | 3.7.1+rocm7.14.0 | ROCm build |

Do not install torch from PyPI — use the ROCm index (section 4.1).

## 7. Remote Access (SSH tunnel, recommended)

Both services bind to `127.0.0.1` only. From your local machine:

```bash
ssh -i <your_private_key> -N -L 7860:127.0.0.1:7860 -L 8188:127.0.0.1:8188 root@SERVER_IP -p SSH_PORT
```

Then open `http://localhost:7860` (WebUI) and `http://localhost:8188` (ComfyUI)
in your local browser. If port 22 is firewalled, use a Cloudflare Tunnel or the
platform tunnel tool instead.

## 8. Known Errors & Fixes

### 8.1 `RuntimeError: operator torchvision::nms does not exist`

Cause: a wrong libtorch is loaded, so torchvision's operators never register
with torch's dispatcher. On this server the container pre-set
`LD_LIBRARY_PATH=/opt/rocm/lib:/usr/local/lib:` which made `torchvision._C.so`
load the system's stale libtorch instead of the torch-bundled one.

Fix: `unset LD_LIBRARY_PATH` before starting either interface. All startup
scripts handle this. (Reproduction log:
`demo/logs/error1_LD_LIBRARY_PATH_torchvision_nms.log`.)

### 8.2 `ERROR: VAE is invalid: None`

Cause: the `sd_xl_base_1.0.safetensors` file **does not contain a VAE** — the
official SDXL base checkpoint ships UNet + text encoders only. Using a
`VAELoader` (or any node that reads a VAE out of this file) fails with
`No VAE weights detected, VAE not initalized`.

Fix: use the VAE output of `CheckpointLoaderSimple` (`output 2`) when decoding
SDXL latents, or supply a separate `sdxl_vae` .safetensors file. The bundled
workflow already does this. (Reproduction log:
`demo/logs/error2_VAELoader_VAE_is_invalid.log`.)

### 8.3 WebUI "hang" at `Creating model from config: ...sd_xl_base.yaml`

Cause: transformers 4.40.2 requests a config from the network for
`openai/clip-vit-large-patch14`, gets a 404, and the exception is swallowed in
a background thread — the process stays alive but never finishes.

Fix: apply `patches/sd_disable_initialization.patch` (see its README).

## 9. Benchmark (SDXL 1024×1024, 20 steps, euler_ancestral)

Measured via `scripts/sdxl_benchmark.py` against the running ComfyUI instance.

| Run | Wall time | Peak VRAM |
| --- | --- | --- |
| 1 | 8.02 s | 31.20 GB |
| 2 | 8.02 s | 31.21 GB |
| 3 | 8.02 s | 31.21 GB |
| **Average** | **8.02 s** | **31.21 GB** |

- VRAM idle (model loaded): ~21.98 GB
- Sample: `demo/sdxl_benchmark_1024.log`, generated images in `demo/images/`

## 10. References (Chinese docs)

- `docs/ROCm-SDXL快速创作模板工作台-参赛README.md` — competition entry README
- `docs/文生图部署说明书.md` — step-by-step deployment manual
- `docs/访问说明.md` — remote access quick reference
- `docs/部署实操全记录与踩坑复盘.md` — deployment log & pitfall review

Adobe Acrobat


总结此内容


询问 AI 助手
