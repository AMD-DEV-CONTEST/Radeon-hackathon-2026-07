# System Architecture — Knowledge Garden

Knowledge Garden is a **local web application** (React + FastAPI) that
drives **vLLM on ROCm** through OpenAI-compatible HTTP. There are two
physically separate runtime components on the single AMD Radeon gfx1100 card.

## High-level diagram

```
   ┌────────────────────────────────────────────────────────────────────┐
   │                        User (Web Browser)                          │
   └───────────────────────────────┬────────────────────────────────────┘
                                   │ HTTP (SPA + JSON API)
                                   ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │                    FastAPI backend (:8510)                          │
   │                                                                    │
   │   ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐   │
   │   │ REST API      │   │  Study/Review │   │ Extraction worker  │   │
   │   │ (materials,   │──▶│  services     │   │ (async thread)     │   │
   │   │ skills, runs, │   │  (learning,   │   │  polls queued runs │   │
   │   │ sessions)     │   │  assessment,  │   │  -> validated units│   │
   │   └──────────────┘   │  SM-2 review)  │   └─────────┬──────────┘   │
   │            │         └───────┬────────┘             │               │
   │            ▼                 ▼                      ▼               │
   │   SQLite (WAL)      bge-base-en-v1.5         vLLM HTTP client       │
   │   learning.db       embeddings (RAG)         (batch extraction)     │
   └───────────────────────────────────────────────┬────────────────────┘
                                                   │ OpenAI-compatible
                                                   ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │       vLLM on ROCm — single AMD Radeon gfx1100 (48 GB VRAM)         │
   │                                                                    │
   │   :8000  Qwen2.5-14B-Instruct-AWQ   dialogue layer (26.5 tok/s)    │
   │   :8001  Qwen2.5-32B-Instruct-AWQ   batch extraction (12.5 tok/s)  │
   └────────────────────────────────────────────────────────────────────┘
```

## Component responsibilities

### Frontend (`web/` — React 19 + Vite + Tailwind v4)

- **GardenPage** — skill garden: growth value, mastery status, due reviews.
- **UploadPage** — Markdown-only drag & drop upload; shows the filename,
  never echoes content; only `.md`/`.markdown` accepted.
- **ProcessingPage** — extraction run status (queued/running/verified/
  failed) with live polling (1.5 s interval), retry and delete actions.
  Updates automatically when the job completes — no manual refresh.
- **SkillDetailPage** — verified knowledge units with source spans and key
  points; "view source" links into the source-document viewer.
- **SourcePage** — renders the original uploaded Markdown (react-markdown +
  remark-gfm, safe: raw HTML not rendered, URL transform sanitized).
- **LearnPage / AssessmentPage / ReviewPage** — Feynman recall with draft
  persistence, source-grounded assessment, SM-2 review with hidden answers.
- **Custom router** — History API, no routing dependency; deep-link and
  refresh recovery; three responsive viewports (375/768/1280).

### Backend (`app/` — FastAPI + SQLite)

| Module | Responsibility |
|---|---|
| `main.py` | REST API wiring, drain protocol, SPA fallback |
| `processing.py` | Material ingestion, extraction-run lifecycle, source validation, entailment |
| `worker.py` | Async extraction worker: polls queued runs, calls 32B, commits validated units |
| `study.py` | Learning sessions, assessment scoring, SM-2 review scheduling |
| `review.py` | Review session state machine, override, transcript persistence |
| `grading.py` | Server-side authoritative grading client |
| `schedule.py` | SM-2 spaced-repetition scheduler |
| `db.py` | SQLite data layer (skills, cards, sessions, WAL mode) |
| `drain.py` | Drain/undrain protocol with atomic lock + writer counting |
| `extract.py`, `llm.py` | Legacy extraction + vLLM HTTP client |

### Data model (`db/migrations/0001_initial.sql`)

- `skills` — name, growth_value (0-100), decay_rate, status
- `materials` — raw_text (original Markdown), normalized_text, sha256,
  **filename** (persisted upload name)
- `extraction_runs` — material_id, status (queued/running/verified/failed),
  model, error_detail, retries
- `learning_units` — content, **source_material**, source_start/end,
  source_quote, key_points, status (candidate/verified/duplicate/rejected)
- `learning_progress` — per-unit SM-2 state (mastery, repetitions, ease,
  next_review_at)
- `study_sessions`, `assessment_attempts` — learning/assessment/review
  session persistence

SQLite runs in **WAL mode** (crash safety + concurrent reads); the WAL
pragma is set once per process to avoid a concurrency deadlock under load
(`PRAGMA busy_timeout=5000` on every connection).

## Data flow: upload → verified units

1. `POST /api/materials` (JSON: `skill_name`/`skill_id` + `text` +
   `filename`) — Markdown boundary check first (422 if not `.md`), then
   idempotent material creation (per-skill content hash).
2. `create_run()` queues an extraction run.
3. Worker thread (2 s poll) picks the run, marks it `running`, truncates
   the material to the 32B context budget, calls the model with a prompt
   that forces source-phrase-grounded content.
4. Candidate units are validated: exact quote/offset match against the
   persisted normalized source, then field-level entailment (longest common
   substring ≥ 4 chars — rejects fabricated claims, accepts paraphrases).
5. Validated candidates are committed as `verified` units; the run becomes
   `verified`. All units reference their material via `source_material`.
6. The UI polls every 1.5 s and shows the terminal state automatically.

## Resilience

- Startup recovery: `running` runs are requeued (crash recovery).
- Drain protocol: `POST /api/admin/drain` blocks new writes and waits for
  zero in-flight writers; `undrain` atomically resets.
- Retry: manual retries are unlimited (only a failed run may be retried).
- Delete: skill/run/material cascade with FK `ON DELETE CASCADE`.
- Local DB on fast storage to avoid NFS I/O stalls (with periodic backup).
