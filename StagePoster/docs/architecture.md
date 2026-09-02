# StagePoster Backend Architecture

## Overview

StagePoster uses three independently managed services that cooperate through
local HTTP APIs:

- **Go Backend** — the only service the browser talks to
- **ComfyUI** — image generation
- **vLLM** — planning and review

## System Diagram

```text
┌──────────────────────────────┐
│ Frontend                     │
│ Web / Desktop / Mobile       │
└──────────────┬───────────────┘
               │ HTTPS
               ▼
┌──────────────────────────────┐
│ Cloudflare Tunnel            │
│ Development public gateway   │
└──────────────┬───────────────┘
               │ localhost:8080
               ▼
┌──────────────────────────────┐
│ Go Backend                   │
│ Session and poster runtime   │
├──────────────────────────────┤
│ Conversation state machine   │
│ Design plan persistence      │
│ Candidate orchestration      │
│ Deterministic composer       │
│ Review loop                  │
│ Snapshot and restore         │
│ SQLite repository            │
└───────────┬───────────┬──────┘
            │           │
            ▼           ▼
┌─────────────────┐   ┌─────────────────┐
│ ComfyUI :8188   │   │ vLLM :8001      │
│ Z-Image-Turbo   │   │ Qwen3.5-9B      │
│ Image generation│   │ Plan and review │
└─────────────────┘   └─────────────────┘
```

## Responsibilities

### Go Backend

Owns AI session state, conversation history, missing-requirement tracking,
design plan persistence, candidate generation requests and selection, poster
composition, review records and snapshots, best-so-far restoration, finalization
idempotency, the public API and CORS, and all database and storage paths.

### ComfyUI

**Owns:** Z-Image-Turbo inference, prompt and seed execution, job status,
generated key-visual files.

**Does not own:** user sessions, text layout, event metadata, review history,
finalization.

### vLLM

Serves Qwen3.5-9B through an OpenAI-compatible API, used for requirement
extraction, follow-up questions, design-plan generation, multimodal poster
review, and structured review decisions.

## GPU Lifecycle

The Radeon PRO W7900 is shared by ComfyUI and vLLM.

```text
Conversation or review request
        ↓
Acquire VLM runtime  →  unload ComfyUI models (ReleaseComfyMemory)
        ↓
Run Qwen3.5-9B
        ↓
Release runtime; ComfyUI generation may run again
```

> **vLLM sleep mode is NOT used.** Earlier revisions of this document said the
> runtime "uses vLLM sleep mode to release GPU memory when the VLM is idle".
> That is no longer true and must not be re-enabled: on ROCm 7.2 + vLLM 0.20.0,
> `--enable-sleep-mode` makes every request after the first wake fail with
> `CUDA Error: invalid argument`. vLLM stays **resident**, and VRAM is reclaimed
> by unloading ComfyUI's models instead.

vLLM's dev endpoints are bound to localhost and must not be exposed publicly.

## AI Session State

Frontend code should primarily follow `availableActions` rather than
hardcoding this progression.

```text
collecting requirements
        ↓
awaiting plan confirmation
        ↓
generating candidates
        ↓
awaiting candidate selection
        ↓
succeeded
        ↓
finalize
        ↓
succeeded  or  completed_with_warnings
```

Additional terminal or exceptional states: `needs_user_input`, `failed`,
`canceled`.

## Poster State

```text
created → generating_candidates → awaiting_selection → selected
        → composing → succeeded | failed
```

## Review Loop

```text
Final poster V1
        ↓
Review Round 1
        ↓
Decision ── ACCEPT / RECOMPOSE / REGENERATE / REWRITE_BRIEF
        ↓
Snapshot current round
        ↓
Apply action
        ↓
Review next version
        ↓
Maximum rounds or ACCEPT
        ↓
Restore highest-scoring snapshot
```

See `docs/job-lifecycle.md` §9 for terminal-state semantics and measured
per-round score data.

### RECOMPOSE vs REGENERATE

| | `RECOMPOSE` | `REGENERATE` |
|---|---|---|
| Key visual | Reuses the selected candidate | Submits a new ComfyUI generation |
| ComfyUI | Not invoked again | Invoked |
| Mechanism | `CompositionAdjustments` | Extends positive/negative prompts |
| Then | Re-layouts text deterministically | Adopts the new job, recomposes, re-reviews |

Measured on live data, `REGENERATE` improves the score by **+4.8** on average
while `RECOMPOSE` averages **-0.7**. `RECOMPOSE` is currently frequently a
no-op; the cause is documented in `docs/job-lifecycle.md` §9.

## Composition Adjustments

The deterministic composer supports four parameters:

| Field | Effect |
|---|---|
| `Template` | Selects a layout preset |
| `TitleOffsetRatio` | Vertical title nudge, clamped to `[0, 0.12]` |
| `PanelTopRatio` | Information panel top edge, clamped to `[0.70, 0.86]` |
| `PanelTheme` | `dark` / light panel treatment |

Review issue codes are mapped onto these in
`internal/poster/finalization.go:426` via substring matching against `TITLE`,
`INFORMATION_PANEL_CONTRAST`, `INFORMATION_PANEL`, `SPACING`, `HIERARCHY`,
and `LAYOUT`.

> The VLM emits free-form codes, and roughly half match none of these. Unmatched
> codes leave the struct zero-valued, which the composer reads as "use template
> defaults" — so the recompose can reproduce an identical image. `ReviewIssue.Layer`
> is parsed but not yet used as a fallback route.

## Persistence

SQLite tables:

```text
ai_sessions        ai_messages        ai_design_plans    ai_session_assets
assets             poster_requests    poster_candidates  poster_outputs
poster_reviews     jobs               outputs
```

Review images are preserved as filesystem snapshots so a superseded round can be
restored:

```text
review-round-1-final_poster.png    review-round-1-thumbnail.png
review-round-2-final_poster.png    review-round-2-thumbnail.png
```

## Idempotency

Finalize is idempotent. Once a session is finalized, a repeated call returns the
existing result, creates no additional review round, does not change the final
image, and performs no duplicate composition.

## Concurrency

Finalize calls are serialized by session key, so calls for the same session
cannot modify the poster concurrently. Different sessions finalize
independently. Both reconciler goroutines tick every 2 s and have panic recovery
— without it they would die silently.

## Public Exposure

**Expose only:** Go Backend `:8080`

**Must remain private:** ComfyUI `:8188`, vLLM `:8001`, SQLite files, storage
directories.
