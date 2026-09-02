# PR: Track 2, PLASMA, ProjectPack Office Agent

## Summary

This PR implements **UI-0 — Unified Web Workbench Foundation & Contract
Freeze**, as defined in `docs/UNIFIED_WORKBENCH_UI_PLAN.zh-CN.md`. It lays down
the frontend foundation (React + TypeScript + Vite, under `web/`) and **freezes
the API contract** between the new workbench and the existing FastAPI backend,
so later UI stages (UI-1…UI-5) can build on a stable base without changing the
public contract.

> No backend runtime code or public Schema is modified — this stage is
> foundation only.

## What changed

### Frontend (`web/`)
- **Unified `ApiClient`** (`src/api/client.ts`): configurable `baseUrl`,
  Bearer-token injection, request timeout (`AbortController`), and a single
  `ApiError` mapping for `401 / 403 / 404 / 409 / 422 / 5xx` and network
  failures, each with a user-readable message.
- **TypeScript DTOs** (`src/api/dto.ts`) for auth / project / runs / tasks /
  risk / report, with field names mirrored 1:1 from the backend Pydantic models
  (snake_case, no rename layer). Each mapped interface is annotated with
  `// maps: <Model>`.
- **Centralized path constants** (`src/api/paths.ts`) covering the backend's
  non-uniform prefixes.
- **App shell**: `AuthContext` with login-state recovery (token only in
  `localStorage`), `RequireAuth` route guard (redirect to `/login`), top nav,
  project selector, and loading / empty / error feedback components.
- **Mock data + mock fetch** (`src/api/mock.ts`) for offline regression and
  tests only — clearly `mock-` prefixed and never wired into the live app.
- **Frozen contract doc**: `docs/UI_API_CONTRACT.md`.

### Contract verification (backend, server-less)
- `scripts/validate_ui_contract.py`: asserts every DTO field name exists on the
  corresponding backend Pydantic model, and every declared path constant
  matches a real backend route (`app/api/*.py`).
- `tests/test_ui_api_contract.py`: runs the validator under the repo unittest
  suite.

### Specs
- `specs/ui-foundation-260723-1500/` — `PRODUCT.md`, `TECH.md`,
  `TEST_REPORT.md` (change level **S2**; `TEST_REPORT` is required for S2).

## Acceptance criteria (UI-0)

| ID  | Criterion                                       | Coverage                                        |
| --- | ----------------------------------------------- | ----------------------------------------------- |
| AC1 | Unauthenticated → redirect to login            | `guard.test.tsx`                                |
| AC2 | Network/API errors → readable prompt, no stack | `errors.ts` + `feedback.tsx`                    |
| AC3 | Build + static checks pass                      | `npm run build`                                 |
| AC4 | Key API client tests pass                       | `client.test.ts` (error matrix / network / Bearer / baseUrl) |
| AC5 | DTO fields match backend Pydantic              | `scripts/validate_ui_contract.py`              |
| AC6 | Token never in logs / Git                       | `localStorage` only; no `console` of token     |
| AC7 | No fake "model already ran"                     | test-only `mock-` data, never in live app       |

## Testing

- **Frontend**: `cd web && npm install && npm run build && npm test` →
  `tsc --noEmit` + `vite build` clean, **29 Vitest tests pass** (client 11,
  contract 15, guard 3).
- **Backend gate**: `make test-governance` (i.e.
  `PYTHONPATH=. python -m unittest discover -s tests -p 'test_*.py'`) → all
  pass, including the new contract tests.
- **Governance**: `validate_specs --strict`, `validate_pr_title`, and
  `git diff --check` all pass.

## Notes / environment fixes
- The backend uses **non-uniform path prefixes** (`/auth`, `/api/projects`,
  `/projects/...`, `/notifications`); these are declared explicitly and
  contract-checked so the frontend never guesses a prefix.
- `scripts/__init__.py` was added (regular package) to fix a site-packages
  namespace-package shadow that broke the existing `test_validate_pr_title`.
- Vitest 2 + Node 25 + Windows leaked ~4 GB across test files (DOM env) and
  OOM'd at teardown. Mitigated by: upgrading to Vitest 3, running each test
  file in its own process, using `react-test-renderer` (no DOM) for the
  route-guard test, and moving the dev proxy to `vite.dev.config.ts` so the
  test runner does not start a proxy agent.

## Out of scope (deferred to UI-1…UI-5)
Project import / file upload, run / task / risk / report detail pages,
confirmation queue, retina / heatmap viewers, compliance dashboard, and
online/offline sync. Their DTOs and path constants are pre-declared in the
frozen contract so later stages build on a stable base.
