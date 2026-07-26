# 🎨 AI-Image-Studio · Radeon Edition

> AMD AI DevMaster Hackathon · **Track 1: Multimodal AI** submission
> An all-in-one intelligent image & video editor running locally on **AMD Radeon GPU + ROCm**

## ⚡ The 30-Second Review

| Reviewer's question | Our answer |
| --- | --- |
| **What is the input?** | An image / a short video clip / a text prompt (e.g. a product photo, a blurry old portrait, "Summer Carnival") |
| **What does the model do?** | 11 reproducible AI pipelines run locally on an AMD Radeon GPU (ROCm): inpainting, outpainting, object removal, super-resolution, style transfer, background removal/replace, face restoration, asset splitting, poster batch, video enhancement, e-commerce suite. LCM-LoRA compresses diffusion sampling from 25 steps to 4–8 steps |
| **How to verify the result?** | ① Every operation shows live latency / ms-per-step / peak VRAM; ② `scripts/benchmark.py` reproduces the full measured table with one command (incl. LCM vs standard comparison) → [docs/BENCHMARKS.md](docs/BENCHMARKS.md); ③ before/after images + demo video |

**AI-Image-Studio** integrates 11 high-frequency image/video creation capabilities into one lightweight web application. All inference runs locally on an AMD Radeon GPU via ROCm (the codebase also degrades gracefully to CUDA or pure CPU for development).

## ✨ Features

| Feature | Description | Tech stack |
| --- | --- | --- |
| 🖌️ Inpainting | Brush a region + describe the change (recolor, add object, fix details) | Stable Diffusion Inpainting |
| 🔍 Outpainting | Extend the canvas in 4 directions, AI fills seamlessly | SD Inpainting + canvas construction |
| 🧽 Object/Watermark Removal | Brush to erase passers-by, clutter, watermarks — no prompt needed | LaMa (seconds) + SD fallback |
| ✨ Super-Resolution | 2×–4× enhancement, tiled low-VRAM inference for large images | Real-ESRGAN (pure PyTorch re-implementation) |
| 🎭 Style Transfer | Anime / cyberpunk / watercolor / oil / film / pixel presets + custom, **batch supported** | SD img2img |
| 🧑‍🎨 Background Replace | High-precision matting → transparent PNG / solid / gradient / **AI-generated background** | BiRefNet + SD Inpainting |
| 😊 Face Restoration | Blurry/old photos → clear faces, multi-face detect & align, optional upscale | GFPGAN + YuNet (pure PyTorch) |
| 🧩 Asset Splitting | One character image → transparent layer + AI-completed background → **layered PSD export** | BiRefNet + LaMa + psd-tools |
| 🖼️ Poster Batch | txt2img → 2× upscale → template typesetting, batch e-commerce covers/posters | SD txt2img + Real-ESRGAN + PIL |
| 🎬 Video Super-Resolution | Short-video frame-by-frame enhancement, original audio preserved | Real-ESRGAN + FFmpeg |
| 🛒 E-Commerce Suite | One product photo → white-background main image + AI scene images + typeset posters | BiRefNet + SD + SR + typesetting |

**⚡ Global acceleration:** inpainting / outpainting / style transfer / poster / e-commerce all support the **LCM-LoRA turbo mode** — 25 steps → 4–8 steps, 3–5× faster. **Custom LoRA** weights (HF repo id or local `.safetensors`) can be loaded for arbitrary styles.

UI screenshots live in `docs/screenshots/`.

## 🚀 Quick Start

### 1. Requirements

- AMD Radeon GPU (RX 7000/9000 series or the official Radeon Cloud instance), ROCm 6.x driver
- Python 3.10+, ~15 GB free disk (model weights)

### 2. Install

```bash
# PyTorch for ROCm (skip if the cloud image already ships it — check with:
#   python -c "import torch; print(torch.__version__, torch.version.hip, torch.cuda.is_available())")
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.3

pip install -r requirements.txt
```

### 3. Download models (~10 GB)

```bash
# Mainland-China instances: export HF_ENDPOINT=https://hf-mirror.com
python scripts/download_models.py            # everything
python scripts/download_models.py --minimal  # core only (inpaint + light SR)
```

### 4. Run

```bash
python app.py --preload            # local:  http://localhost:7860
python app.py --preload --share    # cloud instance: creates a public gradio.live URL
python app.py --low-vram           # limited-VRAM mode
```

### 5. Reproduce the benchmark

```bash
python scripts/benchmark.py --image examples/demo.jpg --out docs/BENCHMARKS.md
```

The generated table includes the **standard 25-step vs LCM 6-step** comparison measured on the local GPU.

## ⚙️ Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `AISTUDIO_DEVICE` | `auto` | `cuda` (ROCm maps to cuda) / `cpu` |
| `AISTUDIO_DTYPE` | `auto` | `fp16` / `bf16` / `fp32` |
| `AISTUDIO_LOW_VRAM` | `0` | `1` = evict models after use + attention/VAE slicing |
| `AISTUDIO_MAX_DIFFUSION` | `768` | working resolution (long edge) for diffusion |
| `AISTUDIO_MAX_VIDEO_SECONDS` | `30` | video SR input length limit |
| `AISTUDIO_MAX_VIDEO_HEIGHT` | `720` | video SR input height limit |
| `AISTUDIO_ENABLE_LCM` | `1` | set `0` to disable LCM turbo mode |
| `HF_ENDPOINT` | — | set `https://hf-mirror.com` for faster HF downloads |

## 🧱 Project Structure

```
AI-Image-Studio/
├── app.py                  # Gradio web UI (12 tabs)
├── config.py               # global settings (env-overridable)
├── requirements.txt
├── src/
│   ├── device.py           # ROCm/CUDA/CPU detection + inference optimization
│   ├── model_manager.py    # lazy model loading & VRAM management
│   ├── lora_tools.py       # LCM-LoRA turbo + custom LoRA
│   ├── utils.py            # image / mask utilities
│   └── pipelines/          # 11 feature pipelines
├── scripts/
│   ├── download_models.py  # one-click model download
│   └── benchmark.py        # performance benchmark (auto Markdown table)
├── docs/
│   ├── PROJECT_PROFILE.md  # project profile (source of the submission PDF)
│   ├── SUBMISSION.md       # submission guide
│   ├── BENCHMARKS.md       # measured performance (generated on target GPU)
│   └── screenshots/
└── models/                 # SR/face weights (created by download script; not committed)
```

## 📦 Models & Licenses

| Model | Used for | License |
| --- | --- | --- |
| SD 1.5 Inpainting | inpaint / outpaint / background | CreativeML OpenRAIL-M |
| SD 1.5 | style transfer img2img / poster txt2img | CreativeML OpenRAIL-M |
| Real-ESRGAN | super-resolution | BSD-3 |
| BiRefNet | background removal / asset splitting | MIT |
| LaMa | object/watermark removal | Apache-2.0 |
| GFPGAN | face restoration | Apache-2.0 |
| YuNet (opencv_zoo) | face detection | MIT |
| LCM-LoRA | turbo sampling | Apache-2.0 |

Project code is released under the MIT License. Model weights follow their own licenses and are used for learning and research only.

## 🔧 ROCm Adaptation Notes

- Device layer detects ROCm via `torch.version.hip` and maps inference onto the `cuda` namespace HIP device; FP16 + SDPA attention (native in PyTorch 2.x on ROCm 5.4+) + `channels_last` UNet layout are enabled by default.
- Real-ESRGAN and GFPGAN are **re-implemented in pure PyTorch** (no `basicsr`/`facexlib` compiled dependencies), so behavior is identical on ROCm/CUDA/CPU and no CUDA-only operators are used anywhere.
- Measured performance on AMD Radeon GPU: see [docs/BENCHMARKS.md](docs/BENCHMARKS.md).
