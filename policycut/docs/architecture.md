# PolicyCut Architecture

## Overview

PolicyCut is a single-process FastAPI application with a vanilla-JS browser frontend, a single-GPU job queue and file-based persistence. There is deliberately no database, no Redis, no build step: the whole tool starts with `python run.py` and stores everything under `data/projects/<project_id>/`.

```
┌────────────────────────── Browser ──────────────────────────┐
│ index.html      project.html     processing.html            │
│ (projects)      (upload+policy)  (SSE progress)             │
│ review.html ◄── the core: video + canvas overlay,           │
│                 dual-track timeline, event editing          │
│ export.html     (render + downloads + audit stats)          │
└───────────────┬─────────────────────────────────────────────┘
                │ REST + SSE   /api/v1
┌───────────────▼─────────────────────────────────────────────┐
│ FastAPI (policycut.api)                                      │
│   projects · policy · jobs (SSE) · events (revision-checked) │
│   artifacts · system                                         │
│                                                              │
│ JobQueue (core.queue) — one worker thread, one GPU           │
│   └─ pipeline.run_analysis / pipeline.run_render             │
│                                                              │
│ NORMALIZING   media.normalize   ffmpeg: CFR, ≤1080p,         │
│                                 proxy ≤1280, thumb, ASR wav  │
│ TRANSCRIBING  audio.transcribe  Whisper large-v3-turbo (GPU) │
│ DETECTING_PII audio.pii         spoken-form norm + regex     │
│ DETECTING_VISUAL vision.detector Grounding DINO (GPU)+YuNet  │
│ TRACKING      vision.tracker    association → SAM 2.1 (GPU)  │
│                                 → masks.npz (fallback: box)  │
│ BUILDING_PREVIEW review.overlay boxes burned into preview    │
│ ── human review happens here (events.json, revisions) ──     │
│ RENDERING     media.render      OpenCV effects + audio       │
│                                 mute/beep → libx264/AAC mux  │
│ AUDITING      audit.builder     audit.json + srt + zip       │
└──────────────────────────────────────────────────────────────┘
```

## Key design decisions

**Models load sequentially, never concurrently.** One GPU, bounded VRAM: Whisper is unloaded before Grounding DINO loads; DINO is unloaded before SAM 2.1 propagates. Every stage is bracketed by `torch.cuda.synchronize()` + peak-memory reset/read so the numbers in `audit.json` are honest.

**Events are the unit of truth.** Analysis produces `RedactionEvent`s (visual with track keyframes + optional mask archive; audio with padded time spans). The review UI edits events, never raw model output. Every mutation carries `expected_revision` (HTTP 409 on conflict), bumps the project revision, appends to `review_history.jsonl` and marks exports stale.

**Fail toward privacy.** Empty SAM masks → padded interpolated boxes, never a hole. Missing word timestamps → whole segment redacted + forced review. Unknown policy terms → surfaced as unsupported, never guessed. Export blocked while any automatic event is unreviewed.

**Atomic everything.** JSON saves go through `tmp + os.replace`. The rendered MP4 is ffprobe-validated before being atomically moved into `exports/`. A killed server leaves jobs marked `server_restarted`, ready to retry — never a half-written project file.

**ROCm adaptation** (see `docs/project-profile.md` §5): Transformers port of Grounding DINO (no CUDA custom ops), SAM 2.1 with `SAM2_BUILD_CUDA=0`, FP16 default with per-stage FP32 re-run fallback, `--require-rocm` contest mode that forbids silent CPU fallback for core stages.

## Data layout

```
data/projects/<id>/
├── project.json / policy.json / events.json / jobs.json
├── review_history.jsonl
├── source/original.<ext>
├── working/{normalized.mp4, proxy.mp4, asr.wav, review_overlay.mp4, thumbnail.jpg}
├── analysis/{transcript.private.json, stage_metrics.json, tracks.json, masks/*.npz}
├── exports/{redacted.mp4, redacted.srt, audit.json, policycut_export.zip}
└── logs/pipeline.jsonl
```

`transcript.private.json` never leaves `analysis/`; exports only carry the redacted SRT and the PII-free audit.
