
# Radeon.Aura

A compact, full-stack multimodal AI studio for image, video and audio generation and composition — optimized for AMD ROCm acceleration and Google Gemini integration. This repository contains the web UI, server glue, and developer tooling to run and iterate locally.



**Contents:** quickstart, pipeline overview, repo layout, assets & credits.

**Prerequisites:** Node.js (16+ recommended), a valid `GEMINI_API_KEY` in `.env` for model calls. For GPU-accelerated workloads, an AMD ROCm-capable environment is recommended.

**Quickstart**

1. Install dependencies:

```bash
npm install
```

2. Copy configuration and set secrets:

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY and other env vars
```

3. Run in development (hot-reload + server middleware):

```bash
npm run dev
```

Open: http://localhost:3000

4. Production build and start:

```bash
npm run build
npm start
```

If you run into PowerShell execution policy errors on Windows, try running the script via `cmd`:

```bash
cmd /c "npm run dev"
```

**Repository layout**

- `server.ts` — Express + Vite middleware and Gemini client integration.
- `src/` — React app source
  - `App.tsx`, `main.tsx`, `index.css`
  - `components/` — `ImageCanvas.tsx`, `VideoComposer.tsx`, `AudioStudio.tsx`, `DirectorChat.tsx`, `GpuProfiler.tsx`, `Dashboard.tsx`
- `assets/` — bundled images, example media
- `package.json` — scripts and dependencies
- `tsconfig.json`, `vite.config.ts` — TypeScript and Vite config

**Pipeline (overview)**

Radeon.Aura follows a simple M1→M5 pipeline that maps developer workflows to reproducible stages:

- M1 — Scene & UI: author assets, layout canvases and scene presets for image/video/audio composition.
- M2 — Scripted Composition & Randomization: scripted scene composers, prompt templates and augmentations.
- M3 — Data Capture: record output stems (images, frames, audio) and export assets for training or sharing.
- M4 — Profiling & Quantization: measure ROCm performance (`GpuProfiler`) and prepare FP16/INT8 optimized pipelines.
- M5 — Train / Evaluate (optional): export datasets for downstream model training and run evaluations.

**Run the app tasks**

- Development server: `npm run dev` (starts `tsx server.ts` + Vite middleware)
- Build for production: `npm run build`
- Start production server: `npm start`

**Assets & datasets**

- `assets/` contains bundled example media so the UI works out-of-the-box. These can be large — use Git LFS or host externally if you plan to publish the repo.
- `outputs/` (gitignored) is used for generated videos, exported stems, and profiling results.

**Notes & troubleshooting**

- The server will abort at startup if `GEMINI_API_KEY` is missing — this prevents returning simulated outputs by mistake.
- On Windows, PowerShell execution policies may block scripts; use `cmd /c "npm run dev"` as a workaround.

**Credits & licenses**

This project integrates models and assets from various upstream projects. Respect their licenses if you redistribute or modify assets.

- Gemini / Google AI integration: follow Google API terms for `GEMINI_API_KEY` usage.
- ROCm-related packages and performance tooling: AMD ROCm project and related wheels.


