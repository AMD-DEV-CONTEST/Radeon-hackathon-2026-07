# StagePoster — Agent Engineering Guide

## Engineering Style

- Keep changes small and direct. Most fixes should touch the narrowest code path
  that explains the bug.
- Change the least amount of files possible. A change that touches many files is
  more likely to be a bad change than a good one unless the broader scope is
  directly required.
- Prefer practical fixes over broad architecture work. Add abstractions only
  when they remove real repeated logic.
- Prefer fewer dependencies. Do not add new Go dependencies unless absolutely
  necessary. The current dependency set is intentionally minimal (`golang.org/x/image`,
  `modernc.org/sqlite`).
- Delete obsolete code aggressively. Remove dead fallbacks, unused options,
  debug prints, and compatibility branches that are no longer needed.
- Preserve existing APIs, endpoint names, request/response shapes, and
  workflow compatibility unless the change is explicitly about replacing them.
- Code must look hand-written for this repository. Changes that read like
  generic AI-generated code will be rejected automatically: unnecessary helper
  layers, vague names, boilerplate comments, defensive branches without a real
  failure mode, broad rewrites, or code that ignores the local style.

## Architecture Boundaries

```
internal/
├── api/          # HTTP layer only. Translates HTTP to domain calls.
│                 # No business logic, no direct ComfyUI/vLLM calls.
│                 # All handlers delegate to service/ or poster/.
├── domain/       # Pure data structures + constants. No logic beyond
│                 # validation helpers (e.g. NewID, JSON struct tags).
├── repository/   # SQLite data access. Knows table schemas and SQL.
│                 # No HTTP, no ComfyUI, no vLLM.
├── service/      # Core business logic. Orchestrates ComfyUI, vLLM,
│                 # file storage. No HTTP types (no http.Request/Response).
├── poster/       # High-level poster generation flow. Orchestrates
│                 # planner → ComfyUI → evaluator → composer → reviews.
│                 # Depends on service/, repository/, composer/.
├── assistant/    # AI conversation state machine. Depends on ai/,
│                 # poster/, repository/. Manages brief → plans →
│                 # candidate selection → finalize lifecycle.
├── ai/           # vLLM client + Runtime (GPU sleep/wake).
│                 # Thin wrapper over OpenAI-compatible HTTP API.
├── comfy/        # ComfyUI client + Workflow template.
│                 # Knows node IDs, prompt submission, history polling.
├── composer/     # Poster layout engine. Pure image composition
│                 # using golang.org/x/image. No external dependencies.
├── storage/      # File system abstraction. Reads/writes job outputs,
│                 # assets, final posters. No business logic.
└── worker/       # Background goroutines. Reconcilers are fire-and-forget
                  # tick loops with panic recovery. Never block startup.
```

### Layer Rules

- `api/` → `service/` + `poster/` + `assistant/` (never skip to `repository/` directly)
- `poster/` → `service/` + `repository/` + `composer/` (never calls `ai/` directly)
- `assistant/` → `ai/` + `poster/` + `repository/` (never calls `comfy/` directly)
- `service/` → `comfy/` + `repository/` + `storage/` (never calls `ai/` directly)
- `worker/` → `service/` + `poster/` (read-only observers, never mutate domain directly)

### What Belongs Where

| Concern | Package | Reason |
|---|---|---|
| HTTP routing, CORS, auth middleware | `api/` | Framework boundary |
| SQL queries, table migrations | `repository/` | Persistence boundary |
| ComfyUI prompt submission, history polling | `service/` + `comfy/` | External service boundary |
| vLLM chat completions, vision calls | `ai/` | External service boundary |
| Poster state machine (3 candidates → select → compose → review) | `poster/` | Domain flow boundary |
| AI conversation flow (brief → plans → confirm → finalize) | `assistant/` | Domain flow boundary |
| Text rendering, image compositing, barcode generation | `composer/` | Pure computation boundary |
| Background polling loops | `worker/` | Concurrency boundary |
| PosterStatus / CandidateStatus constants | `domain/poster.go` | Shared vocabulary |
| Database schema changes | `repository/sqlite.go` Migrate | Migration ownership |

## Concurrency Rules

- Background goroutines MUST have panic recovery. A single panic silently kills
  the reconciler and stalls the entire poster pipeline. See
  `worker/reconciler.go` and `worker/poster_reconciler.go` for the required
  `defer recover()` pattern.
- Use `sync.Mutex` for in-memory locks (e.g. session-level select lock in
  `poster/service.go`). Do not use channels for mutual exclusion.
- Context timeouts must be explicit. Default reconciler timeout: 90s.
- Never start a goroutine that blocks on I/O without a timeout context.

## Error Handling

- Define sentinel errors at package level with `errors.New`.
- Wrap errors with `fmt.Errorf("context: %w", err)` to preserve error chain.
- Never log and return the same error — pick one.
- Reconciler errors are logged as warnings, not fatal. The tick loop continues.
- Database errors propagate up to the HTTP layer, which returns 5xx.

## ComfyUI Interaction Rules

- Never call ComfyUI directly from `api/` or `assistant/`. Route through
  `service/PosterService`.
- Node IDs (prompt, seed, negative prompt) are configurable via env vars.
  Do not hardcode them in Go source — they live in `z_image_poster_v1.json`.
- After submitting a prompt, the caller receives a `jobID`. The reconciler
  polls `/history/{prompt_id}` until `completed` or `failed`.
- ComfyUI model VRAM must be released before vLLM wakes up. This is handled
  by `ai.Runtime.SetBeforeAcquire(posterService.ReleaseComfyMemory)`.

## vLLM Interaction Rules

- vLLM is called through `ai.Service`, never directly from other packages.
- The `ai.Runtime` manages GPU sleep/wake. Currently sleep mode is disabled
  on ROCm 7.2 due to a known crash. Do not re-enable without testing.
- Vision calls (image understanding for evaluation/review) use Qwen's
  multimodal capability via `/v1/chat/completions` with image content.

## SQLite Rules

- All schema migrations are in `repository/sqlite.go` `Migrate()`.
- Additive migrations only. Never drop columns in a running system.
- Use `context.Context` with a timeout on every DB call.
- The `modernc.org/sqlite` driver is pure Go — no CGO, no system SQLite needed.

## Testing

- Unit tests live alongside source files (`*_test.go`).
- Run with `go test ./...` from `backend/`.
- ComfyUI memory pressure test: `comfy/client_memory_test.go` — requires
  running ComfyUI instance.
- Integration tests (E2E) are shell scripts in `scripts/`, not Go tests.

## Scripts Policy

- All shell scripts in `scripts/` must source `.env` from BOTH locations:
  - `$BACKEND_ROOT/.env` (for `cd backend && ./scripts/...` usage)
  - `$PROJECT_ROOT/.env` (for `cd /workspace/poster-engine && ./scripts/...` usage)
- Scripts must be idempotent where possible (re-running should not break state).
- Scripts must check prerequisites (ROCm, Python, etc.) before proceeding.
