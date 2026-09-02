# UI-0 工作台基础与契约冻结 (Unified Web Workbench — Foundation & Contract Freeze)

## Goal

Deliver stage **UI-0** of the unified web workbench: the foundation and a
frozen contract. Later stages (UI-1…UI-5) build on this contract and must not
change it. See `docs/UNIFIED_WORKBENCH_UI_PLAN.zh-CN.md` and
`specs/ui-workbench-plan-260723-1430/`.

## User-visible behavior

- An unauthenticated user hitting a protected route is redirected to the login
  page instead of seeing a blank error screen.
- Network/API failures surface as a human-readable message, never a raw stack
  trace.
- Frontend DTOs have a contract test against the backend Pydantic Schema; pages
  are not built by guessing field names.
- A single unified API client handles the auth header, timeout, and error
  mapping so business pages only deal with data.

## Scope

- New standalone frontend directory `web/` (React + TypeScript + Vite) with
  build, dev proxy, and static checks.
- Unified API client: `baseUrl`, Bearer token, request timeout, network error,
  and 401/403/404/409/422/5xx error mapping.
- TypeScript DTOs for project / runs / tasks / risk / report / auth interfaces,
  with field names identical to the backend Pydantic models.
- App shell: login-state recovery, top nav, project selector, and
  loading/empty/error pages.
- Mock data and API contract tests; usable for offline UI regression.
- Frozen contract document: `docs/UI_API_CONTRACT.md`.

## Non-goals

- Do not modify the public Schema (`app/schemas`); new public types require a
  spec first.
- Do not build UI-1…UI-5 pages (project import, run/task/risk/report detail,
  confirmation queue, retina/heatmap viewers, compliance dashboard, sync).

## Acceptance criteria

- AC1: Unauthenticated access to a protected route redirects to login.
- AC2: Network/API exceptions show a user-readable prompt (no raw stack).
- AC3: Frontend build and static checks pass (`npm run build`).
- AC4: Key API client tests pass (401/403/404/409/422/5xx + network + Bearer +
  baseUrl).
- AC5: DTO field names match the backend Pydantic Schema (contract test).
- AC6: The token is never written to logs or Git.
- AC7: Mock data never fakes that the model has already run.

## Dependencies

- Backend: `app/api` (auth/projects/overview/runs/tasks/risks/reports/
  notifications) and `app/schemas.models`.
- Upstream spec: `ui-workbench-plan-260723-1430`.

## Out of scope (deferred)

Project-import/file-upload UI, run/task/risk/report detail pages, confirmation
queue, retina/heatmap viewers, compliance dashboard, and online/offline sync.
Their DTOs and path constants are declared in the frozen contract so later
stages build on a stable base.
