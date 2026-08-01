# AetherStyle

> **Track 1: Development of Multimodal Content Creation Tools**
> A one-stop, open-source multimodal AIGC toolkit (text-to-image, image-to-image, and text-to-video) optimized for **AMD Radeon GPUs / ROCm**.

AetherStyle is a local-first creative tool that turns natural-language prompts into images and short videos entirely on AMD hardware. It automatically selects the best model that fits your machine's disk and memory budget, and gracefully falls back to lighter models if a download or load fails — so it **never crashes** on a misconfigured box. The video path is built around **Wan2.2-TI2V-5B**, whose `umt5-xxl` text encoder understands Chinese natively (no translation subsystem required).

---

## 1. Features

| Capability | Primary model | Fallback chain |
| --- | --- | --- |
| Text-to-Image | Stable Diffusion 3.5-Medium (~10 GB, Community License) | SDXL (~7 GB) → SD v1.5 (~4 GB) |
| Image-to-Image | Stable Diffusion 3.5-Medium / SDXL | SD v1.5 |
| Text-to-Video | **Wan2.2-TI2V-5B** (5B DiT + umt5-xxl, ~34 GB, 720P@24fps, Apache-2.0) | LTX-Video 2B → Legacy damo-vilab/text-to-video-ms-1.7b |

- **Native Chinese prompts** for video (Wan `umt5-xxl` multilingual encoder).
- **Automatic best-model selection** — the engine only downloads what fits the free disk and only loads what fits VRAM, then degrades safely.
- **Crash-proof** — incomplete weights, gated/quota limits, or OOM are caught and routed to the next fallback tier.
- **Web UI** built with Gradio (port `7860`, optional public `*.gradio.live` share link).
- **Self-test suite** (`test_flow.py`) covering env checks, smoke tests, and a full generation benchmark.

---

## 2. Hardware & Software Requirements

| Item | Requirement |
| --- | --- |
| GPU | AMD Radeon (CDNA/RDNA) with ROCm support, e.g. **gfx1100**, ≥ 24 GB VRAM (48 GB recommended for Wan2.2-TI2V-5B + SD3.5 together) |
| OS | Linux (tested on the AMD ROCm test machine) |
| ROCm | ROCm 6.x or 7.x |
| Python | 3.10+ (3.13 used in dev) |
| Disk | ≥ 60 GB free for cached weights (SD3.5 10 GB + Wan 34 GB + SDXL 7 GB + …) |
| PyTorch | ROCm build (`torch` + `torchvision` from the ROCm wheel index) |

> On older torch + gfx1100 you may need `export HSA_OVERRIDE_GFX_VERSION=11.0.0` if you see `hipErrorNoBinaryForGpu`.

---

## 3. Environment Setup

The competition/test image ships a prebuilt venv with the correct `torch`+`HIP` at `/opt/venv`. Activate it first:

```bash
source /opt/venv/bin/activate
which python3        # must print /opt/venv/bin/python3
```

If you need to build a fresh environment, install the ROCm build of PyTorch **before** the rest of the dependencies:

```bash
# ROCm 6.x
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.0
# ROCm 7.x
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.0

# then the project dependencies
pip install -r requirements.txt
```

Verify the ROCm backend is live:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.version.hip)"
# expected: True <rocm-version>
```

---

## 4. Dependencies (`requirements.txt`)

Core AIGC framework:

- `diffusers>=0.33.0,<1.0` — includes `WanPipeline`, `LTXPipeline`, SD3.5, SDXL pipelines
- `transformers>=4.56.0,<5.0` — umt5-xxl / T5-XXL / CLIP text encoders
- `accelerate>=0.32.0`, `safetensors>=0.4.1`, `invisible-watermark>=0.2.0`
- `sentencepiece>=0.2.0`, `protobuf>=6.31.1,<7.0`

Web & API:

- `fastapi>=0.108.0`, `uvicorn>=0.27.0`
- `gradio>=4.44.0,<4.45.0`, `gradio-client>=1.3.0,<1.4.0`
- `huggingface_hub>=0.34.0,<1.0`

Image / video:

- `Pillow>=10.0.0`, `opencv-python>=4.8.0`, `numpy>=1.24.0`
- `av>=11.0.0`, `imageio-ffmpeg>=0.4.9`, `moviepy>=1.0.3` (GIF export / editing)

---

## 5. Project Structure

```
aether_style/
├── engine.py            # Model loading, generation, fallback orchestration
├── app.py               # Gradio Web UI (tabs: T2I / I2I / T2V / …)
├── run_light.sh         # Launch script (auto best-model selection)
├── test_flow.py         # Validation / benchmark suite
├── requirements.txt     # Pinned dependency list
└── models/              # Local weight cache (auto-populated on first run)
```

---

## 6. Startup

```bash
# from the aether_style/ directory
bash run_light.sh
```

`run_light.sh` sets sensible defaults (`AETHER_SD_MODEL=sdxl`, `AETHER_ENABLE_SD3=1`,
`AETHER_SD3_MODEL=medium`, `AETHER_T2V_MODEL=Wan-AI/Wan2.2-TI2V-5B`, `HF_ENDPOINT=https://hf-mirror.com`)
and launches the Web UI on **http://localhost:7860**. With `share=True` it also prints a
public `https://*.gradio.live` URL.

Web UI tabs:

1. **Text-to-Image** — SD3.5-Medium primary; Chinese/English prompts; resolution & step controls.
2. **Image-to-Image** — img2img from an uploaded image.
3. **Text-to-Video** — Wan2.2-TI2V-5B primary; native Chinese prompt; 720P@24fps presets.
4. **Model management** — reload / inspect loaded backends and fallback status.

---

## 7. Validation (`test_flow.py`)

```bash
python3 test_flow.py --mode env            # checks python deps, torch+HIP, GPU (no download)
python3 test_flow.py --mode smoke --no-heavy   # quick SD v1.5 path only (no big downloads)
python3 test_flow.py --mode full --benchmark-steps 30   # full pipeline + benchmark
```

`--no-heavy` skips SD3 (10 GB) and Wan (34 GB) downloads so the suite runs fast on first boot.

---

## 8. Configuration Environment Variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `AETHER_SD_MODEL` | `sdxl` | Force SD tier (`sdxl` / `v1.5`) |
| `AETHER_ENABLE_SD3` | `1` | Enable SD3.5-Medium (set `0` to disable) |
| `AETHER_SD3_MODEL` | `medium` | `medium` / `large` / `turbo` |
| `AETHER_T2V_MODEL` | `Wan-AI/Wan2.2-TI2V-5B` | Force a specific T2V model / path |
| `AETHER_T2V_DTYPE` | `bf16` | Wan inference precision (`bf16`/`fp16`/`fp32`) |
| `HF_ENDPOINT` | `https://hf-mirror.com` | HuggingFace mirror for faster downloads |

---

## 9. Model Licenses

All bundled models are open / Community License and ROCm-compatible:

- **SD3.5-Medium** — Stability Community License
- **SDXL / SD v1.5** — OpenRAIL-M
- **Wan2.2-TI2V-5B** — Apache-2.0
- **LTX-Video** — (Lightricks) Apache-2.0
- **damo-vilab/text-to-video-ms-1.7b** — ModelScope community license

---

## 10. Submission

This repository is prepared for **Track 1: Development of Multimodal Content Creation Tools**.
Accompanying materials (Project Profile PDF, demo video, PPT) are provided alongside this README.
All submission text is in English per the contest rules.
