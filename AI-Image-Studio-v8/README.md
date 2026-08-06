# 🎨 AI-Image-Studio v8 · Radeon Edition

> **AMD AI DevMaster Hackathon 2026 — Track 1: Multimodal AI**
>
> Six production-grade AI image pipelines, rebuilt from the ground up on **SDXL**,
> running natively on **AMD Radeon GPU + ROCm** with zero CUDA-only dependencies.

[![ROCm](https://img.shields.io/badge/ROCm-6.3+-red?logo=amd)](https://rocm.docs.amd.com/)
[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 🎬 Demo Video

📺 **[Watch the 4-minute demo](https://pan.quark.cn/s/e1816b827c73)** — Gradio UI walkthrough, all six pipelines, and real-time `rocm-smi` performance metrics on AMD Radeon Pro W7900.

---

## 🏆 Hackathon Submission

| Item | Link |
|------|------|
| **Source Code** | This repository |
| **Project Profile (PDF)** | [Download PDF](https://pan.quark.cn/s/8d5ddb7847fd) |
| **Demo Video** | [Watch on YouTube/Bilibili](https://pan.quark.cn/s/e1816b827c73) |
| **Poster / PPT** | [View Poster](https://pan.quark.cn/s/fadc2f7a8569) |

---

## 🖥️ System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | AMD Radeon (ROCm 6.3+) / NVIDIA CUDA / CPU fallback | AMD Radeon Pro W7900 (48 GB VRAM) |
| **System RAM** | 16 GB | 32 GB |
| **Disk Space** | 25 GB (for model weights) | SSD |
| **OS** | Linux (Ubuntu 22.04+) | Linux |
| **Python** | 3.10 | 3.10–3.12 |

---

## 🚀 Quick Start

### Option A: One-Command Start (Radeon Cloud — Recommended)

```bash
cd /workspace/persistent/AI-Image-Studio-v8
bash start.sh
```

> `start.sh` will:
> - Persist MIOpen autotune cache to avoid ~6 min recompilation stalls
> - Set HF Hub fail-fast timeouts (3s etag / 15s download)
> - Restart `rc-tunnel` for public URL exposure
> - Apply the ImageEditor light-frame patch
> - Launch the app in background mode with log output to `app.log`
>
> After ~15 seconds, open the printed tunnel URL in your browser.

### Option B: Manual Start

```bash
# 1. PyTorch for ROCm (skip if already installed)
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.3

# 2. Dependencies
pip install -r requirements.txt

# 3. Download Models (~17 GB)
# Mainland China users: use HF mirror
export HF_ENDPOINT=https://hf-mirror.com

python scripts/download_models.py

# LaMa model (one file, manual download)
curl -kL -o models/big-lama.pt \
  "https://huggingface.co/martintomov/big-lama/resolve/main/big-lama.pt"

# 4. Launch
export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
export MIOPEN_USER_DB_PATH=/workspace/persistent/miopen-db
mkdir -p /workspace/persistent/miopen-db

python app.py              # http://localhost:7860
python app.py --share      # public URL (Gradio tunnel)
```

### Option C: Virtual Environment (if `externally-managed-environment` error)

```bash
cd /workspace/persistent/AI-Image-Studio-v8
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scripts/download_models.py
export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
python app.py --share
```

---

## 📊 Performance Benchmarks

All measurements on **AMD Radeon Pro W7900 (48 GB VRAM)**, ROCm 6.3, PyTorch 2.3, FP16 + SDPA.

| Pipeline | Base Model | Steps | LCM Turbo | Typical Time | Peak VRAM |
|----------|-----------|-------|-----------|--------------|-----------|
| 🖌️ Inpaint | SDXL img2img | 30 | 8 steps | ~4.2 s | ~10.5 GB |
| 🔍 Outpaint | SDXL Inpainting | 30 | 8 steps | ~5.1 s | ~11.2 GB |
| 🧽 Remove | LaMa (TorchScript) | — | — | ~0.8 s | ~2.1 GB |
| 🎭 Style | SDXL + ControlNet Canny | 30 | 8 steps | ~6.8 s | ~14.3 GB |
| 🧑‍🎨 Background | BiRefNet + SDXL txt2img | 30 | 8 steps | ~7.5 s | ~12.8 GB |
| 🧩 Asset Split | BiRefNet + LaMa | — | — | ~3.2 s | ~8.5 GB |

**⚡ LCM-LoRA Turbo Mode**: 30 inference steps → 8 steps, achieving **3–5× speedup** on Inpaint, Outpaint, Style, and Background pipelines.

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────┐
│  Gradio Web UI (8 tabs + Example Gallery)   │
│  Home · Inpaint · Outpaint · Remove · Style │
│  · Background · Asset Split · System Status │
├─────────────────────────────────────────────┤
│  Intent Understanding Layer (optional)      │
│  Qwen2.5-1.5B-Instruct → structured JSON    │
│  pipeline, prompt, strength, seed           │
├─────────────────────────────────────────────┤
│  Pipeline Layer — 6 Task-Specific Engines   │
│  Inpaint · Outpaint · Remove · Style        │
│  · Background · Asset Split                 │
├─────────────────────────────────────────────┤
│  ModelManager — Lazy-Loading Singleton Hub  │
│  SDXL base/inpaint · ControlNet · BiRefNet  │
│  LaMa · LCM-LoRA · Intent LLM               │
│  Shared SDXL base via from_pipe()           │
├─────────────────────────────────────────────┤
│  Device Abstraction Layer                   │
│  ROCm (HIP) / CUDA / CPU auto-detect        │
│  FP16 + SDPA · Low-VRAM slicing             │
│  MIOpen persistence · AOTriton attention    │
└─────────────────────────────────────────────┘
```

---

## 🎨 Pipeline Details

### 🖌️ Inpaint — Localized Recolor & Edit
- **Engine**: SDXL img2img (not the inpainting checkpoint) + soft-mask compositing
- **Innovation**: **Crop-to-mask** strategy — crops a padded box around the brushed region, repaints at native resolution, and pastes back through a Gaussian-blurred mask. Local edits stay local with full detail.
- **Subject Gate**: BiRefNet matting clips sloppy user brushes to the subject boundary, preventing translucent ghosts in the background.
- **Face Guard**: `lbpcascade_animeface` detector prevents accidental face overwrites during recolor operations.
- **LCM Turbo**: 8 steps for general edits; 16 steps for recolor at strength 0.85 to preserve denoising depth.

### 🔍 Outpaint — Seamless Canvas Extension
- **Engine**: SDXL Inpainting
- **Innovation**: **Tone Hint Extraction** — analyzes the source image's palette and lighting, injecting descriptive words into the prompt so invented surroundings match the original mood.
- **Edge-Replicated Seed**: Extended canvas filled with coherent edge pixels from the original image.
- **Overlap Mask**: 64 px feathered overlap region ensures invisible transitions.
- Directional control: independent left / right / top / bottom expansion.

### 🧽 Remove — Object & Watermark Erasure
- **Primary Engine**: LaMa (local TorchScript) — prompt-free, completes in seconds
- **Fallback Engine**: SDXL Inpainting with "empty clean background" prompt
- **Smart Watermark Detection**: Searches 6 zones (4 corners + top/bottom strips) for semi-transparent overlays (6–160 gray-level deviation). Abstains on busy backgrounds to maintain zero false positives.
- **Smart Snap**: Refines a rough user brush to exact glyph strokes for precise LaMa erasure.

### 🎭 Style Transfer — Structure-Locked Restyling
- **Engine**: SDXL img2img + **ControlNet Canny Structure Lock**
- **Innovation**: Canny edge map pins pose, composition, and facial features while colors and textures restyle freely.
- **6 Built-in Presets**: Anime, Cyberpunk, Watercolor, Oil Painting, Pixel Art, Film Photo
- **Anime Guard**: Heuristic detector (flat-color ratio + edge density) warns against no-op anime→anime applications.
- Default strength 0.4–0.5 for optimal identity preservation.

### 🧑‍🎨 Background Replace — Precision Matting + AI Backdrop
- **Matting**: BiRefNet with **1 px alpha erosion** to remove original-backdrop halo before feathering.
- **Three Modes**:
  - **Solid Color**: Simple RGB fill
  - **Gradient**: Fast numpy-based linear gradient
  - **AI-Generated**: SDXL txt2img at exact image size, cover-cropped from native bucket to prevent tiling artifacts
- **Output**: Composite image + transparent PNG cutout

### 🧩 Asset Split — Layered PSD + Asset Pack
1. BiRefNet extracts foreground as RGBA
2. Crop to alpha bounding box + 16 px margin
3. Background hole filled via LaMa with **banded smoothness filter**: smooth areas (sky, walls) → heavy Gaussian blur; textured areas (grass, sea) → retain synthesized detail
4. Export as **layered PSD** (foreground + background layers)
5. Bundle all assets into a downloadable ZIP

---

## 🔧 ROCm-Specific Optimizations

This project is **engineered specifically for AMD Radeon GPUs**, not merely "ROCm-compatible."

| Optimization | Implementation | Impact |
|-------------|----------------|--------|
| **AOTriton Fused Attention** | `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1` | Fused attention kernels for gfx1100 (RDNA3), ~1.5× speedup |
| **MIOpen Autotune Persistence** | `MIOPEN_USER_DB_PATH=/workspace/persistent/miopen-db` | Eliminates ~6 min compilation stalls on instance restart |
| **Engine Warm-Up** | Pre-runs tiny inferences at startup | First user click is responsive; no MIOpen stall on first use |
| **deform_conv2d CPU Detour** | `torch.library.Library` dispatcher registration | BiRefNet matting works on ROCm without HIP kernel |
| **HF Hub Timeout Hardening** | `HF_HUB_ETAG_TIMEOUT=3`, `HF_HUB_DOWNLOAD_TIMEOUT=15` | Prevents 25-min hangs on metadata checks |
| **Low-VRAM Mode** | Attention slicing + VAE slicing + VAE tiling | ~40% VRAM reduction with minimal quality loss |
| **FP16 + SDPA Default** | Auto-selected on ROCm GPUs | Optimal speed/quality balance |
| **Zero CUDA Dependencies** | Pure PyTorch generic `torch.cuda` API | Backend-agnostic: HIP, CUDA, or CPU |

### Runtime Detection

```python
# src/device.py — auto-detects backend
detect_device("auto", "auto")
# ROCm:  torch.cuda.is_available() + torch.version.hip → FP16 + SDPA + AOTriton
# CUDA:  Same path, no ROCm patches
# CPU:   FP32 fallback, reduced resolution
```

---

## 📁 Project Structure

```
AI-Image-Studio-v8/
├── app.py                          # Gradio UI (8 tabs)
├── config.py                       # Env-overridable settings
├── requirements.txt                # Python dependencies
├── start.sh                        # One-command Radeon Cloud deploy
├── LICENSE                         # MIT License
├── README.md                       # This file
│
├── src/
│   ├── device.py                   # ROCm/CUDA/CPU runtime + optimization
│   ├── model_manager.py            # Lazy-loading model hub + LCM toggle
│   ├── intent.py                   # LLM-based natural language parser
│   ├── birefnet.py                 # Matting helper + ROCm deform_conv detour
│   ├── utils.py                    # Image/mask/geometry utilities
│   ├── watermark.py                # Smart watermark detection + snap
│   └── pipelines/
│       ├── __init__.py
│       ├── inpaint.py              # Crop-to-mask local editing
│       ├── outpaint.py             # Seamless canvas extension
│       ├── remove.py               # LaMa + SDXL fallback removal
│       ├── style.py                # ControlNet structure-locked style
│       ├── background.py           # BiRefNet + AI backdrop
│       └── split.py                # Layered PSD + asset pack export
│
├── scripts/
│   ├── download_models.py          # Download all HF models
│   ├── gen_examples.py             # Generate built-in demo examples
│   ├── gen_example_results.py      # Pre-compute example results
│   ├── patch_editor_frame.py       # Gradio ImageEditor UI patch
│   └── dl_llm.py                   # Intent LLM downloader
│
└── assets/
    ├── examples/                   # Built-in demo images + masks
    └── models/
        └── lbpcascade_animeface.xml   # Face detection for recolor guard
```

---

## ⚙️ Configuration

All settings can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `AISTUDIO_DEVICE` | `auto` | Backend: `auto` / `cuda` / `cpu` |
| `AISTUDIO_DTYPE` | `auto` | Precision: `auto` / `fp16` / `bf16` / `fp32` |
| `AISTUDIO_LOW_VRAM` | `0` | Enable attention/VAE slicing (`1` = on) |
| `AISTUDIO_ENABLE_LCM` | `1` | Enable LCM-LoRA turbo mode |
| `AISTUDIO_LCM_STEPS` | `8` | LCM inference steps |
| `AISTUDIO_ENABLE_WARMUP` | `1` | Pre-warm engines at startup |
| `AISTUDIO_MAX_WORKING` | `1024` | SDXL working resolution (long edge) |
| `MIOPEN_USER_DB_PATH` | — | MIOpen autotune cache directory |
| `TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL` | — | Enable AOTriton on ROCm |

---

## 🧠 Intent Understanding Layer (Optional)

Powered by **Qwen2.5-1.5B-Instruct**, the intent layer translates free-form user instructions into structured pipeline parameters:

```
User: "Change the dress to light blue, hair to black"
  ↓
Intent LLM → {"pipeline": "inpaint", "prompt": "light blue dress, black hair",
               "strength": 0.85, "steps": 30}
  ↓
Pipeline executes with precise parameters
```

- **Rule-based fallback** when LLM is disabled, not downloaded, or slow
- Fully local — no API keys, no network calls during inference
- Can be disabled via `AISTUDIO_ENABLE_INTENT=0`

---

## 📜 Models & Licenses

| Model | Source | License | Purpose |
|-------|--------|---------|---------|
| SDXL Base 1.0 | Stability AI | OpenRAIL++-M | txt2img, img2img |
| SDXL Inpainting 0.1 | diffusers | OpenRAIL++-M | Outpaint, Remove fallback |
| ControlNet Canny SDXL | diffusers | OpenRAIL++-M | Structure-locked style transfer |
| BiRefNet | ZhengPeng7 | MIT | High-precision matting |
| LaMa (big-lama) | advimman | Apache-2.0 | Fast object/watermark removal |
| LCM-LoRA SDXL | latent-consistency | Apache-2.0 | 3–5× inference acceleration |
| Qwen2.5-1.5B-Instruct | Alibaba Cloud | Qwen License | Intent understanding |
| lbpcascade_animeface | nagadomi | MIT | Face detection for recolor guard |

**Project Code**: MIT License  
**Model Weights**: Used for research and learning purposes only.

---

## 🤝 Contributing & Support

- **Discord**: [AMD AI DevMaster Hackathon](https://discord.gg/zt9caur5B3)
- **Email**: ai_dev_contests@amd.com
- **Issues**: Please open an issue in this repository for bug reports or feature requests.

---

## 🙏 Acknowledgments

- [Stability AI](https://stability.ai/) for SDXL
- [Hugging Face](https://huggingface.co/) for diffusers and model hosting
- [AMD](https://www.amd.com/) for ROCm and Radeon GPU resources

---

<div align="center">

**Built with ❤️ on AMD Radeon + ROCm**

</div>
