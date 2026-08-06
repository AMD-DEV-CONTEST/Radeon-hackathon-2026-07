# Knowledge Garden

> **Track 2 — Development & Local Deployment of Private AI Agents**
> AMD AI DevMaster Hackathon 2026-07 (AMD Radeon GPU + ROCm)

**Knowledge Garden** (formerly `learning-companion`) is a **fully private learning
companion Agent** that runs end-to-end on a **single AMD Radeon gfx1100 GPU
(48 GB VRAM)** with **ROCm**. It turns a Markdown study document into a
complete, verified learning loop:

```
Upload Markdown  →  Extract knowledge units  →  Feynman recall learning
        →  Mastery assessment  →  SM-2 spaced repetition review
```

Every component runs locally — **no cloud LLM, no external API key**. The
inference backend is **vLLM on ROCm** serving two co-resident AWQ-quantized
models over OpenAI-compatible endpoints.

---

## Key features

- **Markdown-only upload** — drag & drop a `.md` file; the original source
  document is persisted with its filename.
- **Verified knowledge extraction** — the 32B batch model extracts knowledge
  units, and every unit is validated against the exact source span
  (quote matching + entailment check). No hallucinations pass.
- **Source traceability** — every knowledge card links to its original
  document, rendered as formatted Markdown in the viewer.
- **Feynman learning** — recall-and-explain sessions with structured
  feedback from the dialogue model.
- **Mastery assessment** — source-grounded recall grading with server-side
  authoritative scoring.
- **SM-2 spaced repetition** — reviews scheduled on the Ebbinghaus
  forgetting curve, resumed automatically with hidden answers.
- **Resilient processing** — async extraction worker with queued/running/
  verified/failed lifecycle, retry, delete, and live UI updates.
- **Drain/undrain protocol** — safe database maintenance with zero in-flight
  writes.

## Hardware & runtime (verified on the submission instance)

| Component | Value |
|---|---|
| GPU | 1× AMD Radeon gfx1100 (RDNA3), 48 GB VRAM |
| ROCm | 7.2.x (rock module loaded) |
| Python | 3.12 (`/opt/venv`, ROCm torch + vLLM) |
| vLLM | 0.16.1 (ROCm build) |
| Dialogue model | Qwen2.5-14B-Instruct-AWQ (4-bit, :8000, 26.5 tok/s) |
| Batch model | Qwen2.5-32B-Instruct-AWQ (4-bit, :8001, 12.5 tok/s) |
| Embedding | BAAI/bge-base-en-v1.5 (RAG source grounding) |

AWQ 4-bit quantization runs **2.1× faster than bf16** on gfx1100 and lets
both models co-reside on one 48 GB card (42 GB total, 6 GB headroom).

## Quick start

```bash
# 1) start the dialogue model (must be first, wait until ready)
bash scripts/start_vllm.sh /path/to/Qwen2.5-14B-Instruct-AWQ Qwen2.5-14B-AWQ 8000 0.3 8192

# 2) start the batch extraction model (after :8000 is ready)
bash scripts/start_vllm.sh /path/to/Qwen2.5-32B-Instruct-AWQ Qwen2.5-32B-AWQ 8001 0.5 4096

# 3) start the backend (SPA fallback serves the web UI)
cd /persistent/learning-companion && /opt/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8510

# 4) open http://127.0.0.1:8510 and upload a .md file to begin learning
```

Full reproduction steps: **[docs/REPRODUCE.md](docs/REPRODUCE.md)**

## Documentation

| Document | Purpose |
|---|---|
| [docs/SPECIFICATION.md](docs/SPECIFICATION.md) | Application scenario, architecture, core capabilities, deployment plan |
| [docs/Knowledge-Garden-Specification.pdf](docs/Knowledge-Garden-Specification.pdf) | Project Specification in PDF form (submission-ready) |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture diagram & component responsibilities |
| [docs/ROCM_OPTIMIZATION.md](docs/ROCM_OPTIMIZATION.md) | AMD Radeon GPU / ROCm optimization notes with benchmark tables |
| [docs/REPRODUCE.md](docs/REPRODUCE.md) | Step-by-step reproduction from scratch |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | Narration script for the 3-5 minute demo video |

## Demo video

[`docs/demo/knowledge-garden-demo.mp4`](docs/demo/knowledge-garden-demo.mp4)
— a 4-minute walkthrough recorded on the real AMD Radeon GPU: GPU/ROCm
verification, dual-model check, Markdown upload, live extraction completion,
source-document rendering, Feynman learning, assessment and review —
with English narration and burned-in subtitles.

## Tests

- **85 backend unit tests** — extraction lifecycle, source validation,
  entailment, learning/assessment/review flows, drain protocol, Markdown
  upload boundary, source-document API.
- **75 Playwright end-to-end tests** across 3 viewports (375/768/1280) —
  full user journeys and shell routing on the production fallback server.

## Dependencies

| Layer | Dependencies |
|---|---|
| Runtime | Python 3.12, ROCm 7.2.x, vLLM 0.16.1 (ROCm build), PyTorch (ROCm) — see [requirements.txt](requirements.txt) |
| Backend | FastAPI, Uvicorn, Pydantic v2, SQLite (stdlib `sqlite3`), httpx |
| Frontend | Node.js 20+, React 19, Vite 8, TypeScript 6, Tailwind CSS v4, react-markdown, remark-gfm |
| Models | Qwen2.5-14B-Instruct-AWQ, Qwen2.5-32B-Instruct-AWQ, BAAI/bge-base-en-v1.5 |
| Testing | unittest (backend), Playwright 1.62 (e2e) |

See `docs/REPRODUCE.md` for the full environment setup.

## Repository layout

```
Knowledge-Garden/
├── app/                 # FastAPI backend (main, processing, study, worker, review, grading)
├── web/                 # React + Vite + Tailwind v4 frontend
├── db/migrations/       # canonical SQLite schema (0001_initial.sql)
├── scripts/             # vLLM startup, benchmarks, schema canonicalization, evaluation
├── docs/                # submission docs, performance data, evaluation results
├── tests/               # backend unit tests
└── eval/                # evaluation harness artifacts
```
