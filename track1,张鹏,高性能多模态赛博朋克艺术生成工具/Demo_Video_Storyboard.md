# AetherStyle — Demo Video Storyboard & Recording Guide

**Requirement:** Demo Video, recommended duration **3–5 minutes**, demonstrating the actual
operation on an **AMD Radeon GPU**, from command line / GUI to the final result, showing
**clarity, stability, and diversity** of outputs.

> ⚠️ This video must be **recorded on the AMD ROCm test machine** (the dev/Windows box cannot
> run ROCm). The storyboard below is the script to follow when you capture it.

---

## 1. Recording environment

- Machine: AMD Radeon (gfx1100), 48 GB VRAM, ROCm 6.x/7.x, prebuilt venv at `/opt/venv`.
- Launch: `source /opt/venv/bin/activate` then `bash run_light.sh`.
- UI: Gradio at **http://localhost:7860** (a `*.gradio.live` public link is also printed).
- Capture: OBS Studio (or `ffmpeg`/`kazam`) recording the browser + a terminal window.
  Record at 1080p, 30 fps; show the terminal to prove it is running on AMD ROCm.

## 2. Pre-recording checklist

- [ ] `python3 test_flow.py --mode env` passes (`torch.cuda.is_available()` → True, HIP version printed).
- [ ] At least ~60 GB free disk for cached weights (SD3.5 + Wan + SDXL).
- [ ] Models are **pre-cached** (first run download can be slow; record after caching to avoid wait).
- [ ] Terminal font large enough to read; browser zoom set so the Web UI is legible.
- [ ] Microphone / or prepare on-screen captions for narration.

## 3. Shot list (target ~4 minutes)

| # | Time | On screen | Narration / caption | Shows |
| --- | --- | --- | --- | --- |
| 1 | 0:00–0:20 | Terminal: `source /opt/venv/bin/activate`, `python -c "import torch; print(torch.cuda.is_available(), torch.version.hip)"` → `True <rocm>` | "AetherStyle runs natively on AMD ROCm — here is the HIP backend live." | **AMD ROCm execution** |
| 2 | 0:20–0:40 | Terminal: `bash run_light.sh`; browser opens `:7860` | "One command launches the Web UI on the AMD GPU." | **CLI → GUI** |
| 3 | 0:40–1:10 | Tab "Text-to-Image": enter an English prompt (e.g. "a neon city at night, cinematic"), Steps 30, click Generate → PNG appears | "Text-to-image with SD3.5-Medium — sharp, prompt-faithful." | **Clarity** |
| 4 | 1:10–1:40 | Same tab: a second, different prompt (e.g. "watercolor fox in a forest") → second image | "Different styles from the same UI — diversity." | **Diversity** |
| 5 | 1:40–2:10 | Tab "Image-to-Image": upload the earlier PNG, enter "make it snowy", Generate → restyled image | "Image-to-image restyles an existing picture locally." | **Stability / multimodal** |
| 6 | 2:10–3:00 | Tab "Text-to-Video": Chinese prompt (e.g. "一只猫在樱花树下奔跑，电影感") → 81 frames @24fps → MP4 plays | "Text-to-video with Wan2.2-TI2V-5B — 720P, native Chinese, no translation." | **Clarity + Chinese + AMD video** |
| 7 | 3:00–3:30 | Run 2–3 more video prompts of different themes (product shot, abstract, portrait) in one session | "Multiple clips in one stable session — no crashes." | **Stability + Diversity** |
| 8 | 3:30–3:50 | Model-management panel: show loaded backends / fallback status | "The engine auto-selects the best model that fits; falls back safely if needed." | **Robustness** |
| 9 | 3:50–4:00 | End card: repo + "Track 1, <Your Team Name>, AetherStyle" | "AetherStyle — multimodal AIGC, native on AMD ROCm." | **Submission ID** |

## 4. Post-recording

- [ ] Trim to **3–5 minutes**, keep the AMD/ROCm terminal visible at least in shot #1.
- [ ] Export as **MP4** (H.264, 1080p). Name it `AetherStyle_Demo.mp4`.
- [ ] Verify it plays and the final results are clearly visible (clarity of outputs).
- [ ] If a heavier model was unavailable during recording, keep the fallback clip — it demonstrates stability.

## 5. Tips

- Pre-generate a few outputs once, then re-record the UI actions quickly so the video is smooth.
- Keep one terminal pane showing `rocm-smi` (or `torch.version.hip`) during generation to evidence AMD execution.
- Speak or caption in **English** (all submission materials must be English).
