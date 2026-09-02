# StagePoster Job Lifecycle v1.0

## Goal

Define async task status, progress, persistence, cancellation, retry, and
recovery for the MVP: single Go backend process + SQLite + bounded in-memory
queue + private ComfyUI.

## 1. Why Async Is Required

A single poster generation may involve:

- Brief validation
- Style planning
- Workflow selection
- Asset preprocessing
- Upload inputs to ComfyUI
- Wait for GPU queue
- Model inference
- Retrieve outputs
- Logo and text composition
- Generate preview
- Persist results

The task creation endpoint must return `job_id` immediately. Long-lived HTTP
connections are not acceptable.

## 2. Top-Level States

| State | Meaning | Terminal |
|---|---|---|
| `queued` | Waiting to execute | No |
| `running` | Currently executing | No |
| `succeeded` | Finished successfully | Yes |
| `failed` | Finished with error | Yes |
| `canceled` | Canceled by user | Yes |

These are the exact wire values in `domain.JobStatus`. Earlier drafts of this
document listed `cancelling` and `completed`; neither was ever emitted.
`canceled` uses one `l`, matching poster and AI-session statuses.

### Sub-States (ComfyUI polling)

| State | Meaning |
|---|---|
| `submitted` | Prompt sent to ComfyUI |
| `processing` | ComfyUI is generating |
| `uploading_output` | Copying output files to storage |

## 3. Progress Model

```json
{
  "total": 3,
  "completed": 1,
  "failed": 0,
  "percent": 33
}
```

Progress is updated in the database by the reconciler goroutine. The frontend
polls `GET /api/ai/sessions/{sessionId}` for current progress.

## 4. Cancellation

```
POST /api/jobs/{jobId}/cancel
```

Cancellation is best-effort:
1. If the ComfyUI job is still queued, remove it from the queue
2. If it is already running, let it finish but discard the output
3. Update status to `canceled`

## 5. Retry

```
POST /api/jobs/{jobId}/retry
```

Retry rules:
- Only `failed` jobs can be retried
- Maximum 2 retry attempts
- Each retry generates a new ComfyUI prompt (new seed)
- Retry count stored in `retry_count` column

## 6. Recovery on Backend Restart

On startup, the backend:

1. Queries all `queued` and `running` jobs from SQLite
2. For each job, checks ComfyUI history via `/history/{prompt_id}`
3. If ComfyUI shows `completed`, transitions to `succeeded` and copies output
4. If ComfyUI shows `failed`, transitions to `failed`
5. If ComfyUI has no record, transitions to `failed` (stale)

## 7. Memory Bounds

- In-memory queue: max 100 pending jobs
- Reconciler tick: every 2 seconds
- Reconciler timeout per tick: 90 seconds
- Max concurrent ComfyUI prompts: 1 (single GPU)

## 8. API

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs?limit=20` | List jobs |
| `GET` | `/api/jobs/{jobId}` | Get job status |
| `POST` | `/api/jobs/{jobId}/cancel` | Cancel job |
| `POST` | `/api/jobs/{jobId}/retry` | Retry failed job |
| `GET` | `/api/jobs/{jobId}/result` | Download result |
| `GET` | `/api/jobs/{jobId}/thumbnail` | Download thumbnail |

## 9. Review and Auto-Optimization Loop

After composition succeeds, `POST /api/ai/sessions/{id}/finalize` runs a bounded
quality loop in `internal/assistant/finalize.go`.

```
compose → review(round N) ──ACCEPT──────────────→ succeeded
                    │
                    ├─RECOMPOSE──→ re-layout ────┐
                    ├─REGENERATE─→ re-generate ──┤
                    │                            └→ review(round N+1)
                    └─REWRITE_BRIEF→ needs_user_input
                    
   round >= maxFinalizeReviewRounds → restore best round → completed_with_warnings
```

- `maxFinalizeReviewRounds = 2`, so there is **one** optimization attempt.
- `ACCEPT` requires `totalScore >= domain.ReviewAcceptScore` (**82**).
- On exhaustion, `finalizeBestAvailable` restores the highest-scoring round's
  snapshot — a round that made things worse cannot be the delivered result.

### Terminal states

| State | Meaning |
|---|---|
| `succeeded` | Review returned `ACCEPT` |
| `completed_with_warnings` | Rounds exhausted; best version retained |
| `needs_user_input` | `REWRITE_BRIEF` — the brief itself conflicts |
| `failed` | Composition or review errored |

**`completed_with_warnings` is a normal, successful outcome**, not a failure. The
poster, thumbnail and review evidence are all delivered. It is currently the
*typical* outcome, for the reason below.

### Measured behaviour (live data, 44 reviews / 15 paired posters)

| Round | n | min | avg | max | ACCEPTs |
|---|---|---|---|---|---|
| 1 | 29 | 58 | 81.2 | 92 | 2 |
| 2 | 15 | 65 | 79.5 | 88 | 0 |

Paired per-poster round 1 → round 2 delta:

| Decision | pairs | improved | unchanged | worse | avg delta |
|---|---|---|---|---|---|
| `REGENERATE` | 5 | 3 | 1 | 1 | **+4.8** |
| `RECOMPOSE` | 10 | 1 | 6 | 3 | **-0.7** |

So `REGENERATE` works and `RECOMPOSE` does not. 82 is reachable — round 1 peaks
at 92 and two real `ACCEPT`s exist — so the threshold is not the problem.

### Known defect: `RECOMPOSE` is frequently a no-op

Three independent causes, all in the review → adjustment mapping:

1. **The adjustment constants equal the template defaults.**
   `reviewAdjustments` (`internal/poster/finalization.go:426`) sets
   `TitleOffsetRatio = 0.055` and `PanelTopRatio = 0.81`, which are byte-for-byte
   the `cinematic_center` defaults in `normalizeCompositionAdjustments`
   (`internal/composer/composer.go:454`). For posters on that template the
   recompose regenerates an **identical image**, so the VLM necessarily returns
   an identical score. This explains the `88 → 88` cases where *every* issue code
   matched.
2. **Roughly half of issue codes match nothing.** The matcher does substring
   tests against `TITLE`, `INFORMATION_PANEL`, `SPACING`, `HIERARCHY`, `LAYOUT`.
   Measured over 86 live issues, **47 matched none** — the VLM invents codes
   freely (`INFO_PANEL_CONTRAST`, `INFO_ZONE_CONTRAST`, and four spellings of
   one venue concept: `VENUE_MISSING`, `VENUE_INFO_MISSING`,
   `VENUE_TEXT_MISSING`, `MISSING_VENUE_TEXT`). Unmatched codes leave the
   adjustment struct zero-valued, which the composer reads as "use defaults".
3. **Adjustments do not escalate per round.** The values are constants, so a
   second `RECOMPOSE` computes exactly what the first did.

`ReviewIssue.Layer` (`generation` / `composition` / `brief`) is parsed but not
used to route unmatched codes, which would be the natural fallback.

**Do not work around this by lowering `ReviewAcceptScore`.** That changes the
reported status without changing the poster.

