# Submission — FluxReel (Track 1: Multimodal Content Creation Tools)

**AMD Radeon Hackathon 2026-07 · Track 1** — short-form video creation tool running on AMD Radeon GPU + ROCm.

FluxReel turns a plain topic into a polished **15-second vertical short video**
(1080×1920, 9:16, 30 fps) — fully locally on an AMD Radeon GPU with ROCm.
The whole pipeline (script writing, scene images, captions, and video assembly)
runs on-device: no per-video API cost, and no data leaves the machine.

## Submission contents

| File | Requirement | Description |
|---|---|---|
| `project_profile.pdf` | Project Profile Document (PDF) | Background, target users & scenarios, system architecture, model & algorithm introduction, AMD Radeon GPU / ROCm adaptation description |
| `code.zip` | Project source code | Complete source code archive — `fluxreel/` package, `pyproject.toml`, and `README.md` with environment configuration, startup guide and dependency list |
| `fluxreel.mov` | Demo video (3–5 min) | Live walkthrough of the actual operation on an AMD Radeon GPU — CLI/web UI → generated video, showing output clarity, stability and diversity |
| `README.md` (this file) | Submission index | Explanation of what is submitted and where everything lives |

## Required materials mapping

Per the contest's Track 1 submission requirements:

1. **Project Profile Document (PDF)** → `project_profile.pdf`
   - Project background
   - Target users & application scenarios
   - System architecture
   - Model & algorithm introduction
   - Adaptation description for AMD Radeon GPU / ROCm

2. **Project Source Code** → `code.zip`
   (complete source archive: `fluxreel/` package, `pyproject.toml`, `fabfile.py`,
   and `README.md` with environment configuration, startup guide and dependency list.
   Unzip and run from the extracted directory.)

3. **Demo Video** → `fluxreel.mov` (recommended 3–5 minutes; demonstrates the
   actual operation process and execution performance on an AMD Radeon GPU,
   from command line / GUI to the final result)

4. **Supplementary Material** → PPT/poster source (`fluxreel_slides.pptx` /
   Marp slides, see the project repo) highlighting creative scenarios and
   practical value.

## Quick start (see `code.zip` → `README.md` for details)

```bash
unzip code.zip && cd code
pip install -e .
fluxreel server --port 8000          # web UI + REST API
fluxreel img "a cyberpunk city"       # local image via sd-cpp (FLUX Q4_0 GGUF)
fluxreel download flux --token hf_xxx # fetch FLUX models to the AMD GPU host
fluxreel info                         # GPU / ROCm / disk check
```

## Track-fit notes

- **Core inference = AMD Radeon GPU + ROCm**: scene images via PyTorch ROCm +
  diffusers (FLUX.1-schnell/dev/2-dev) or stable-diffusion.cpp
  (FLUX.1-schnell Q4_0 GGUF, 4-bit quantization) with `--vae-tiling` and
  VRAM budgeting.
- Remote API (OpenRouter) is **optional** for the text planning step only;
  the image/video core never requires it.
- Optimizations: 4-step distilled schnell, Q4_0 quantization, VAE tiling,
  VRAM budget, parallel scene generation, no-re-encode assembly.
