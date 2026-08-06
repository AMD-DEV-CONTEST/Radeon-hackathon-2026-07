# 🎨 AI-Image-Studio v2 · Radeon Edition

> AMD AI DevMaster Hackathon · **Track 1: Multimodal AI** submission
> Six production-grade AI image pipelines, rebuilt from the ground up on **SDXL**,
> running locally on **AMD Radeon GPU + ROCm**.

## Pipelines

| Feature | Engine | What makes it good |
| --- | --- | --- |
| 🖌️ Inpaint | SDXL Inpainting, crop-around-mask | Edits stay local and sharp — recolor/change exactly the brushed region, pasted back seamlessly |
| 🔍 Outpaint | SDXL Inpainting | Canvas extension with edge-replicated seed + overlap mask for invisible seams |
| 🧽 Remove | LaMa (local TorchScript) | One-click object/watermark erasing, prompt-free, seconds; SDXL fallback |
| 🎭 Style | SDXL img2img + ControlNet Canny | **Structure lock** preserves pose, composition and identity while restyling |
| 🧑‍🎨 Background | BiRefNet + SDXL txt2img | Precision matte → transparent / solid / gradient / full-frame AI backdrop, exact-size composite (no ghosting) |
| 🧩 Asset Split | BiRefNet + LaMa | Transparent character layer + AI-completed background → layered PSD + PNG pack |

**⚡ LCM-LoRA (SDXL) turbo mode**: 30 steps → 8 steps, 3–5× faster, one checkbox
on Inpaint / Outpaint / Style / AI-Background.

## Quick Start

```bash
# 1. PyTorch for ROCm (skip if already installed)
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.3

# 2. Dependencies
pip install -r requirements.txt

# 3. Models (~17 GB; mainland China: export HF_ENDPOINT=https://hf-mirror.com)
python scripts/download_models.py
# LaMa weight (one file, once):
curl -kL -o models/big-lama.pt "https://hf-mirror.com/martintomov/big-lama/resolve/main/big-lama.pt"

# 4. Run (recommended on ROCm: enable AOTriton attention for stability)
export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
python app.py            # http://localhost:7860
python app.py --share    # public URL
```

## Runtime notes

- Auto-detects ROCm (`torch.version.hip`); FP16 + SDPA by default; graceful CPU fallback.
- `--low-vram` enables attention/VAE slicing for smaller cards.
- Code contains zero CUDA-only dependencies.

## Project structure

```
app.py                 # Gradio UI (8 tabs: Home + 6 pipelines + System)
config.py              # env-overridable settings
src/
  device.py            # ROCm/CUDA/CPU runtime
  model_manager.py     # SDXL / ControlNet / BiRefNet / LaMa hub + LCM toggle
  birefnet.py          # matting helper
  utils.py             # image/mask utilities
  pipelines/           # inpaint · outpaint · remove · style · background · split
scripts/download_models.py
```

## Models & licenses

SDXL base / SDXL inpainting / ControlNet-Canny-SDXL (Stability AI & diffusers,
OpenRAIL++-M), BiRefNet (MIT), LaMa (Apache-2.0), LCM-LoRA (Apache-2.0),
lbpcascade_animeface (nagadomi, MIT — anime-face detection for the recolor
engine's face guard, `assets/models/lbpcascade_animeface.xml`).
Project code: MIT. Weights are used for research/learning only.
