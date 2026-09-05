# Evidence packet: `E1-B-20260724T061322Z-efa5adb`

## Outcome and scope

- Engineering/user outcome: a runnable React/Vite/TypeScript status shell that
  truthfully presents service health, durable version/autosave state, milestone
  progress, confirmed/unresolved counts, route-readiness placeholders,
  stale/invalidation notices, and current run/terminal state — driven by typed
  contracts, switchable between checked-in mocks and the localhost FastAPI
  backend with no UI contract change.
- Explicit non-goals: no M1 interview/refinement feature, no final visual
  polish, no route/export/deletion implementation, no direct SQLite/vLLM access,
  no invented backend state, no public tunnel, no analytics, no performance
  claim, and no unilateral change to backend-owned schema/OpenAPI contracts.
- Commit / Issue / PR: describes code commit `1789448` on branch
  `codex/e1-b-react-shell` (based on `main` `efa5adb`); Issue #6; PR opened from
  this branch. This packet is added in the commit following `1789448`.
- AC / L1 / L2: AC-04, AC-11, AC-15, AC-17, AC-19, AC-22 · cross-cutting UI
  foundation (no M1–M5 promoted) · Canonical state, Persistence and resume,
  Failure behavior, Observability.

## Reproduction

- Fixture or approved sanitized scenario: checked-in typed mock scenarios
  (`healthy`, `loading`, `empty`, `failure`, `safe-stop`, `stale`,
  `terminal-failure`) plus a LIVE capture against the real E1-A FastAPI health
  and terminal-state contracts. No private user content; all IDs are opaque.
- Environment/model/profile: Node 24.12 / Vite 5.4 / Vitest 2.1 / Playwright
  chromium-headless-shell 149. No model loaded (frontend). Live capture ran the
  E1-A backend (`fastapi 0.128.8`) from contract commit `4960fa0` on
  `127.0.0.1:8080`.
- Commands and exit status (all run in `web/` unless noted):

  ```bash
  npm install
  npm run verify:contracts     # PASS — 9/9 vendored contracts match E1-A checkpoint
  npm run typecheck            # exit 0
  npm run lint                 # exit 0
  npm run test                 # 6 files / 39 tests passed
  npm run build                # exit 0 (gzip JS ~55.7 kB)
  npm run e2e:install          # one-time: chromium
  # live capture: start the E1-A backend, then:
  E2E_LIVE_BASE_URL=http://127.0.0.1:8080 VITE_PROXY_TARGET=http://127.0.0.1:8080 npm run e2e   # 10 passed

  # repository checks (repo root):
  python3 -m unittest discover -s qa/tests -v   # 16 tests OK
  bash qa/gates/pr_gate.sh --mode contract      # PR GATE: PASS (contract mode)
  ```

## Observed results

- Terminal state: `SUCCEEDED`.
- Product/artifact/UI evidence: 10 sanitized browser captures in
  `artifacts/browser/` (see `manifest.json` for per-file sha256), covering
  loading, healthy, empty/no-instance, recoverable failure, safe-stop, stale,
  model-unavailable terminal, refresh, mock→live switch, and a real-backend live
  health capture.
- Measurements: 39 unit/contract tests, 10 E2E tests, live health `ok`
  (database `ok`, `gpu_viability=NOT_VERIFIED`, `inference_mode=local_only`).
- Failures, retries, and recovery: the first live E2E failed on a cross-origin
  (CORS) fetch because the E1-A backend sets no CORS headers. Fixed by shipping a
  same-origin Vite `/api` dev/preview proxy; the browser now stays same-origin
  and the backend stays loopback-only. Re-run passed.
- Truthfulness checks enforced by tests: progress `percent` is always rendered
  with its work-unit basis (`40%（2/5 工作单元）`) and no ETA/countdown is ever
  shown (AC-17); confirmed/unresolved counts derive from statement/question
  state, not visuals; stale state derives from real invalidation markers;
  tool-call proposals render with `permission_granted=false`.
- Unverified areas: real W7900/ROCm model viability (Lane A / Issue #5); live
  asset/progress/terminal endpoints not yet served by the backend (live mode
  truthfully reports `not_served`); `npm ci` against a committed lockfile.

## Decision and history

- Result class: `PASS` (frontend foundation gate; not a product-AC pass and not
  a Baseline).
- Known risks and conditional owner/deadline: E1-A contract checkpoint (PR #7)
  is still draft/unmerged — contracts vendored verbatim with sha256 provenance,
  merge order E1-A→E1-B preserved; `ProgressEventV1` omits `percent_basis`
  required by `check_progress_invariants.py` artifact mode (Lane A cross-lane
  note). Owner `1olaqua616-web`.
- Rollback/known-good profile: last green scaffold/contract version; deleting
  `web/` returns to pre-E1-B `main`. No backend/schema was modified.
- Supersedes/prior packet: none (first E1-B checkpoint).
- Raw/large evidence location and checksum: full-resolution Playwright media and
  the E1-A backend raw logs stay under `/workspace` or session scratch, not Git;
  the sanitized PNGs here are the retained public captures.
