# AI-Image-Studio · Project Profile

> Track 1: Multimodal AI — AMD AI DevMaster Hackathon
> Export this document to PDF for submission (fill in the `____` fields with measured data from your Radeon instance before exporting).

## 1. Project Background

Content creators, e-commerce sellers, and indie designers repeat the same image-editing tasks every day: erasing unwanted objects, extending canvases, upscaling low-resolution assets, restyling photos, cutting out products, and producing posters. Professional tools (Photoshop + plugins) have a steep learning curve, while cloud AI services raise privacy and recurring-cost concerns.

**AI-Image-Studio** packages 11 high-frequency creation capabilities into a single lightweight web application that runs **entirely on a local AMD Radeon GPU with the ROCm stack** — no data leaves the machine, no per-call fees, and every operation reports its measured latency and peak VRAM so performance is verifiable rather than claimed.

## 2. Target Users & Application Scenarios

| User | Scenario | Features used |
| --- | --- | --- |
| E-commerce seller | One product photo → white-background main image + AI scene images + typeset posters | E-Commerce Suite, Poster Batch, Background Replace |
| Content creator / designer | Retouch, extend, restyle photos; restore old portraits | Inpainting, Outpainting, Style Transfer, Face Restoration |
| Live2D / 2.5D artist | Split a single character illustration into transparent layer + completed background, exported as layered PSD | Asset Splitting |
| Short-video creator | Upscale and enhance low-resolution clips | Video Super-Resolution |
| General user | Remove passers-by / watermarks, enhance blurry images | Object Removal, Super-Resolution |

## 3. System Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Gradio Web UI (12 tabs)                 │
│   per-op live metrics: latency / ms-per-step / peak VRAM   │
├────────────────────────────────────────────────────────────┤
│                  Feature Pipelines (src/pipelines)         │
│  inpaint · outpaint · remove · upscale · style ·           │
│  background · face_restore · split · poster · video ·      │
│  ecommerce                                                 │
├────────────────────────────────────────────────────────────┤
│  ModelManager (lazy load / VRAM eviction)                  │
│  LCM-LoRA turbo · custom LoRA · low-VRAM mode              │
├────────────────────────────────────────────────────────────┤
│  Models: SD1.5 & SD-Inpainting (diffusers) · Real-ESRGAN   │
│  (pure-PyTorch) · GFPGAN (pure-PyTorch) · BiRefNet · LaMa  │
│  · YuNet · LCM-LoRA                                        │
├────────────────────────────────────────────────────────────┤
│  PyTorch 2.x (ROCm build) — FP16 · SDPA · channels_last    │
│  AMD Radeon GPU ｜ ROCm ____ ｜ Driver ____                │
└────────────────────────────────────────────────────────────┘
```

## 4. Models & Algorithms

- **Inpainting / Outpainting / AI background** — Stable Diffusion Inpainting (diffusers). Outpainting constructs an extended canvas + mask and reuses the inpainting pipeline; AI background inverts the BiRefNet alpha matte so the foreground is preserved while the scene is regenerated, then the crisp foreground is composited back.
- **Object / watermark removal** — LaMa (fast, prompt-free) with automatic fallback to SD inpainting when the package is unavailable.
- **Super-resolution** — Real-ESRGAN weights (SRVGGNetCompact "fast" tier and RRDBNet "HQ" tier) re-implemented in pure PyTorch — no `basicsr` compiled dependency — with overlap-tiled inference for large images on limited VRAM.
- **Face restoration** — YuNet detection (OpenCV DNN) → 5-point Umeyama alignment → GFPGAN v1.4 (pure-PyTorch re-implementation) → feathered paste-back; falls back to whole-image restoration when no face is detected.
- **Style transfer** — SD img2img with 6 curated presets, custom prompts, batch mode, and user-supplied LoRA weights.
- **Poster / e-commerce** — txt2img → 2× SR → PIL template typesetting (accurate CJK text rendering, avoiding diffusion-generated garbled text).
- **LCM-LoRA turbo mode** — LCM-LoRA adapter + LCMScheduler compress sampling from 25 steps to 4–8 steps (guidance 1.5), giving a measured 3–5× speedup (see BENCHMARKS.md).

## 5. Adaptation for AMD Radeon GPU / ROCm

1. **Device layer**: ROCm is detected via `torch.version.hip`; PyTorch maps HIP devices to the `cuda` namespace, so all pipelines run on the Radeon GPU with FP16 precision by default, with automatic CPU fallback for development.
2. **Inference optimizations on ROCm**: PyTorch 2.x SDPA attention (native on ROCm 5.4+), `channels_last` UNet memory layout, TF32 matmul, tiled SR inference, and an optional low-VRAM mode (attention slicing + VAE slicing/tiling + model eviction).
3. **Dependency portability**: Real-ESRGAN and GFPGAN were re-implemented in pure PyTorch specifically to avoid CUDA-only or compiled extensions; the repository contains **zero** xformers/flash-attention/triton/CUDA-extension usage.
4. **Measured performance**: all latency / throughput / peak-VRAM figures in [BENCHMARKS.md](BENCHMARKS.md) were measured on the target AMD Radeon GPU by `scripts/benchmark.py` (GPU: ____, ROCm: ____, PyTorch: ____), including the standard-25-step vs LCM-6-step comparison.

## 6. Deliverables

- Complete source code (this repository) + README with environment setup, startup guide and dependency list
- Benchmark report: `docs/BENCHMARKS.md` (reproducible via `scripts/benchmark.py`)
- Demo video (3–5 min): installation → feature walkthrough → standard vs turbo comparison, with `rocm-smi` visible
- Poster/PPT (supplementary material)

## 7. Team

| Member | Role / Contribution |
| --- | --- |
| ____ | ____ |
