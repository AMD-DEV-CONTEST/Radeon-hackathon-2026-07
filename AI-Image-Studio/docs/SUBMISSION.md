# Submission Guide · AMD AI DevMaster Hackathon

## Timeline (Beijing time, UTC+8)

- Submission opens: 2026-07-15 00:00
- **Final deadline: 2026-08-06 23:59** (submit 1–2 days early)

## Checklist

- [ ] Registered for the **AMD AI Developer Program** (Mainland China: AMD Developer Program China). ⚠️ Without registration, prize money cannot be paid even if the project wins.
- [ ] Project runs on the AMD Radeon GPU instance (ROCm) — every feature verified once
- [ ] `docs/BENCHMARKS.md` filled with **real measured data** from `scripts/benchmark.py` (run on the Radeon instance)
- [ ] `docs/PROJECT_PROFILE.md` blanks filled → exported to **PDF**
- [ ] ≥ 4 UI screenshots in `docs/screenshots/`
- [ ] Demo video (3–5 min) recorded — see script below
- [ ] All submission materials in **English**
- [ ] Fork contains the project in a **single** `AI-Image-Studio/` folder (no model weights committed)
- [ ] Pull Request opened, titled: `Track 1, <Team name>, AI-Image-Studio`

## Steps

1. Fork <https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07>.
2. Put the project folder into your fork:

   ```bash
   git clone https://github.com/<your-username>/Radeon-hackathon-2026-07.git
   cd Radeon-hackathon-2026-07
   cp -r /path/to/AI-Image-Studio .          # single folder at repo root
   git add AI-Image-Studio
   git commit -m "Track 1: AI-Image-Studio - all-in-one AI image & video editor"
   git push
   ```

3. Open a Pull Request to the official repo's `main` branch.
   **Title:** `Track 1, <Team name>, AI-Image-Studio`

## PR Description Template

```markdown
## Track 1: Multimodal AI

### Input → Model → Output → Verification
- **Input**: an image / a short video clip / a text prompt
- **Model**: 11 reproducible AI pipelines (SD / Real-ESRGAN / BiRefNet / GFPGAN /
  LaMa / LCM-LoRA), all running locally on an AMD Radeon GPU + ROCm
- **Output**: edited images, enhanced videos, layered PSDs, full e-commerce
  asset sets, typeset posters
- **Verification**: every operation shows live latency / peak VRAM;
  `scripts/benchmark.py` reproduces all measured data with one command
  (incl. LCM 25-step → 6-step turbo comparison)

### Runtime Environment
GPU: AMD Radeon ____ (__ GB) ｜ ROCm: ____ ｜ PyTorch: ____

### Highlights
- 11 features in one app; LCM-LoRA turbo mode (3–5× speedup); custom LoRA support
- Asset splitting / e-commerce suite / poster batch match the official topic suggestions
- Real-ESRGAN & GFPGAN re-implemented in pure PyTorch for ROCm portability
  (zero CUDA-only dependencies)

### Materials
- Project profile PDF: docs/PROJECT_PROFILE.pdf
- Benchmarks: docs/BENCHMARKS.md
- Demo video: <link>
- Screenshots: docs/screenshots/
```

## Demo Video Script (≈ 4 minutes)

| Time | Content |
| --- | --- |
| 0:00–0:20 | One-sentence intro + show `rocm-smi` and the app's runtime backend line (proof of Radeon GPU + ROCm) |
| 0:20–1:20 | E-Commerce Suite end-to-end: one product photo → full asset set (the strongest closed-loop demo) |
| 1:20–2:00 | Inpainting + Object Removal quick demos |
| 2:00–2:40 | **Same prompt, standard 25 steps vs LCM turbo 6 steps side-by-side**, with the measured timing on screen |
| 2:40–3:20 | Face restoration on an old photo + image SR; short video SR clip |
| 3:20–4:00 | Show `docs/BENCHMARKS.md` measured table + wrap-up (architecture in one sentence) |

Recording tips:
- Keep a terminal running `watch -n1 rocm-smi` visible in frame — direct evidence of GPU execution
- Use the `--share` public URL or the instance's tunnel to show the app is genuinely served from the Radeon instance
- Narration/subtitles in English
