# UI API Contract (UI-0 — Foundation & Contract Freeze)

This document is the frozen contract between the **Unified Web Workbench**
(`web/`, React + TypeScript + Vite) and the FastAPI backend. It is the
deliverable of stage **UI-0** from `docs/UNIFIED_WORKBENCH_UI_PLAN.zh-CN.md`.

It is **machine-checked**: `scripts/validate_ui_contract.py` asserts that every
DTO field name exists on the corresponding backend Pydantic model and that every
declared path constant is a real backend route. The check runs under
`make test-governance` (`tests/test_ui_api_contract.py`).

## 1. Base URL and dev proxy

- In production the workbench is served from the same origin as the API, so the
  client `baseUrl` defaults to `""` (relative requests).
- In development, `web/vite.config.ts` proxies each top-level segment to the
  API target (`VITE_API_TARGET`, default `http://localhost:8000`):
  `/api`, `/auth`, `/projects`, `/notifications`.

## 2. Authentication

- All protected endpoints require `Authorization: Bearer <token>`.
- The token is obtained from `POST /auth/login` (`LoginRequest` →
  `TokenResponse`) and stored **only in `localStorage`** (per-session). It is
  never written to console, logs, or Git.
- On startup the app performs **login-state recovery**: it calls `GET /auth/me`
  with the persisted token. A `401` clears the token and forces re-login.
- An unauthenticated user hitting a protected route is redirected to `/login`
  (see `src/auth/RequireAuth.tsx`).

## 3. Error model

Most backend errors return a structured body:

```json
{ "error_code": "string", "message": "string", "user_message": "string", "details": {} }
```

FastAPI validation errors (`422`) return the default shape
`{ "detail": [ { "loc": [...], "msg": "string", "type": "string" } ] }`.

The client maps every outcome to a single `ApiError` with a user-readable
message (never a raw stack trace):

| Status | Friendly message (default)                         |
| ------ | -------------------------------------------------- |
| 0 (network / timeout) | Network error. Please check your connection. |
| 401    | Your session has expired. Please sign in again.   |
| 403    | You do not have permission to perform this action. |
| 404    | The requested resource was not found.              |
| 409    | This operation conflicts with the current state.  |
| 422    | The request was rejected (invalid fields).         |
| 5xx    | The server encountered an error. Please retry.     |

## 4. Endpoint catalog

> NOTE: the backend uses **non-uniform prefixes**. Some domains sit under
> `/api`, others do not. The paths below are authoritative (validated).

| Domain   | Method | Path                                      | Request      | Response (DTO)        | Backend model        |
| -------- | ------ | ----------------------------------------- | ------------ | --------------------- | -------------------- |
| Auth     | POST   | `/auth/login`                             | `LoginRequest` | `TokenResponse`     | `TokenResponse`      |
| Auth     | GET    | `/auth/me`                               | —            | `UserProfile`         | `UserProfile`        |
| Projects | GET    | `/api/projects`                          | —            | `Project[]`           | `Project`            |
| Projects | POST   | `/api/projects`                          | `ProjectCreate` | `Project`          | `Project`            |
| Projects | GET    | `/api/projects/{project_id}`             | —            | `Project`             | `Project`            |
| Overview | GET    | `/projects/{project_id}/overview`        | —            | `ProjectOverview`     | `ProjectOverview`    |
| Runs     | GET    | `/api/projects/{project_id}/runs`        | —            | `RunState[]`          | `RunState`           |
| Runs     | GET    | `/api/projects/{project_id}/runs/{run_id}` | —          | `RunState`            | `RunState`           |
| Runs     | GET    | `/api/projects/{project_id}/runs/{run_id}/progress` | — | `RunProgress`  | `RunProgress`        |
| Tasks    | GET    | `/api/projects/{project_id}/tasks`       | —            | `TaskRecord[]`        | `TaskRecord`         |
| Tasks    | GET    | `/api/projects/{project_id}/tasks/{task_id}` | —         | `TaskRecord`          | `TaskRecord`         |
| Risk     | GET    | `/projects/{project_id}/risks`           | —            | `RiskCenterEntry[]`   | `RiskCenterEntry`    |
| Reports  | GET    | `/projects/{project_id}/reports`         | —            | `ReportDraftEntry[]`  | `ReportDraftEntry`   |
| Reports  | GET    | `/projects/{project_id}/reports/{draft_id}` | —          | `ReportDraftEntry`    | `ReportDraftEntry`   |
| Notif.   | GET    | `/notifications`                         | —            | `NotificationEntry[]` | `NotificationEntry`  |

## 5. DTO catalog (`web/src/api/dto.ts`)

Every `export interface` that maps to a backend model is annotated with
`// maps: <PydanticModel>` and uses **snake_case** field names identical to the
backend (the backend serializes snake_case; there is no client-side key
renaming layer). Mapped models:

`LoginRequest`, `TokenResponse`, `UserProfile`, `ProjectCreate`, `Project`,
`ProjectOverview`, `StepTiming`, `RunState`, `RunProgress`, `TaskRecord`,
`TaskCreate`, `RiskCenterEntry`, `ReportDraftEntry`, `NotificationEntry`,
`ErrorDetail`.

Structural sub-shapes used inside `ProjectOverview`
(`TaskStats`, `RiskStats`, `DocChangeSummary`, `RunSummary`) are **not** mapped:
the backend returns those fields as `dict` / `list[dict]`, so there is no named
Pydantic model to diverge from.

## 6. Validation

```bash
# Python (runs in CI via `make test-governance`)
PYTHONPATH=. python scripts/validate_ui_contract.py

# Frontend (Vitest)
cd web && npm test
```

`scripts/validate_ui_contract.py`
1. Parses `web/src/api/dto.ts`, and for each `// maps:` interface asserts every
   field name exists on the backend model in `app.schemas.models`.
2. Parses `web/src/api/paths.ts` and asserts every path constant matches a
   registered route in `app/api/*.py` (prefix + route joined; `{param}` names
   ignored).

## 7. Out of scope for UI-0 (not implemented yet)

Per the plan, UI-0 freezes the foundation only. The following are deliberately
**not** built in this stage: project-import/file-upload UI, run/task/risk/report
detail pages, confirmation queue, retina/heatmap viewers, the spec-compliance
dashboard, and online/offline sync. Their DTOs and path constants are declared
here so later stages (UI-1..UI-5) build on a frozen contract.
