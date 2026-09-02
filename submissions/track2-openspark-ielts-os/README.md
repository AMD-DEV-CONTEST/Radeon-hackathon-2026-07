# IELTS OS · Private AI Study Agent (Radeon Hackathon 2026-07 · Track 2)

A local-first IELTS study app with a built-in **private AI agent**. Listening,
Reading, Writing and Speaking retain complete practice workflows. After each
attempt, the AI tutor reads the verified answers, mistakes, drafts, transcripts,
hint history and persistent learning memory. It reviews each skill, plans the
next task and carries the evidence into later sessions. Development inference runs on AMD GPUs through Radeon Cloud.
The same server can use a fully local Ollama or vLLM backend. Personal files
always stay local; local-backend mode also keeps prompts and tool results on
the machine. The Chinese product interface is intentional for its target
learners; all submission documents, demo narration, subtitles and PR content
are provided in English.

> See [RADEON-CLOUD.md](RADEON-CLOUD.md) for Radeon setup notes and
> [SPECIFICATION.md](SPECIFICATION.md) for the Track 2 project specification.

## Submission package

| Requirement | Deliverable |
| --- | --- |
| Project specification | [SPECIFICATION.md](SPECIFICATION.md) |
| Source code and setup guide | This repository and the Quick start section below |
| Demo video | [IELTS OS demo](demo/IELTS-OS-OpenSpark-Demo.mp4), 3 min 6 s with real UI interaction, English narration, chapter captions, and an embedded English subtitle track ([SRT](demo/IELTS-OS-OpenSpark-Demo.en.srt)) |
| Supplementary material | [A4 project poster](poster.pdf) |

## Core Capabilities (Track 2 rubric)

| Capability | Implementation |
| --- | --- |
| Local personal assistant | In-app AI Tutor chat panel grounded in local study data |
| Local knowledge-base QA | Agent tools over an 8,000-word book, 99 synonym groups and the personal library index |
| Tool calling | 5 local tools: `lookup_word` / `find_synonyms` / `search_library` / `get_study_status` / `get_learning_memory` |
| Multi-step planning | Agent loop (≤12 steps) with parallel tool calls and a visible call trace |
| Persistent personalization | Local memory carries four-skill reviews, dialogue transcripts, weak areas and recent evidence into the next session |
| Live speaking | Full-screen browser/iPhone voice mode, spoken follow-up questions, dialogue summary and transcript-based ability review |
| Privacy | Keys stay server-side in a git-ignored `.env`; personal files are streamed locally and never uploaded; Ollama/vLLM mode also keeps model prompts local |
| Four-skill coaching | Listening and Reading evidence reviews, Writing correction, Speaking Live debrief, and one prioritized next plan over the same AI contract |

## Architecture

```text
┌─────────────────────────────┐
│ IELTS OS Web App (PWA)      │  index.html / app.js, packaged with Capacitor
│  · AI Tutor  → /api/agent   │
│  · Four skill reviews → /api/ai
│  · Learning memory  → localStorage
└──────────────┬──────────────┘
               │ OpenAI-compatible + local REST
┌──────────────▼──────────────┐
│ local-agent-server.mjs      │  static hosting + /api/agent + /api/ai
│  · tools over local data    │  + /library/* streaming (HTTP Range)
└──────────────┬──────────────┘
               │ chat/completions (with tools)
┌──────────────▼──────────────┐
│ Model backend (pick one):   │
│  · Radeon Cloud (AMD GPU)   │  Qwen3.6-35B-A3B — development/demo
│  · Local Ollama / vLLM      │  qwen3:8b — fully offline
└─────────────────────────────┘
```

## Quick Start

Requires Node.js 18+. No npm dependencies.

```bash
# Option A: Radeon Cloud (AMD GPU cloud)
cp .env.radeon.example .env.radeon   # fill in your Radeon Cloud key
npm run agent:radeon

# Option B: local Ollama (fully offline)
ollama pull qwen3:8b
npm run agent:dev

# Open the app
open http://127.0.0.1:8790/        # full app, AI endpoint auto-configures
open http://127.0.0.1:8790/demo    # standalone agent demo page
```

## Verification

```bash
npm run check              # 21 checks: learning loops, data contracts, agent server
npm run check:local-agent  # server only (stubbed upstream, no model quota used)
```

## Content & Licensing

The repository ships **original sample content only** (3 reading passages,
3 listening scripts, 6 writing tasks) plus an anonymized library catalog
sample. Personal materials stay on the learner's machine: the index is
generated locally and files are streamed via `/library/` — never
redistributed. See [CONTENT-LICENSING.md](CONTENT-LICENSING.md).

## Field Notes (Radeon Cloud free tier, Aug 2026)

- A final live Listening validation completed in 4.0 s; shared free-tier
  latency varied with queue load during recording. Writing feedback end-to-end
  ≈ 50 s; agent study plan (status + 8 lookups
  + plan) ≈ 20 s
- The gateway hard-cuts requests at ~120 s; the server retries transient
  failures once and the client once more
- Qwen3.6 hidden thinking exhausts the token budget;
  `LLM_DISABLE_THINKING=1` keeps answers stable
- Details in [SPECIFICATION.md](SPECIFICATION.md) §6
