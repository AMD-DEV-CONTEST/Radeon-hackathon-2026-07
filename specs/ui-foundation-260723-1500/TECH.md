# UI-0 工作台基础与契约冻结 — Technical Record

- Level: S2
- Status: implemented
- Depends-on: ui-workbench-plan-260723-1430

## Components

- `web/package.json`: React + Vite + TypeScript + Vitest dependencies and
  scripts.
- `web/vite.config.ts`: test config (node env, per-file run) + build.
- `web/vite.dev.config.ts`: dev-only proxy for the backend's non-uniform
  prefixes (`/api`, `/auth`, `/projects`, `/notifications`).
- `web/src/api/paths.ts`: all API path constants (validated against backend).
- `web/src/api/errors.ts`: `ApiError` + status→readable-message mapping.
- `web/src/api/dto.ts`: TypeScript DTOs, each mapped to a backend model via a
  `// maps:` annotation.
- `web/src/api/client.ts`: `ApiClient` (baseUrl / Bearer / timeout / error map).
- `web/src/api/mock.ts`: mock data + mock fetch (test/offline only).
- `web/src/auth/AuthContext.tsx`: login-state recovery; token only in
  localStorage.
- `web/src/auth/RequireAuth.tsx`: protected-route guard (redirect to login).
- `web/src/components/Layout.tsx`, `feedback.tsx`: shell + loading/empty/error.
- `web/src/pages/*`: Login, Dashboard (project selector + overview), NotFound.
- `scripts/validate_ui_contract.py`: DTO field + path consistency vs backend.
- `tests/test_ui_api_contract.py`: runs the contract validator under unittest.
- `docs/UI_API_CONTRACT.md`: frozen contract.

## API client

- Constructor: `baseUrl` (default `""`, same-origin), `timeoutMs` (default
  15000), `getToken()`, `fetchImpl` (injectable for tests).
- Every request: `url = baseUrl + path`; attaches `Authorization: Bearer
  <token>` when a token exists.
- Timeout via `AbortController`; `abort` is treated as a network error.
- `fetch` throwing → `ApiError(status=0, isNetworkError)`.
- Non-2xx → parse body and call `mapError(status, body)`:
  - Structured `ErrorDetail` (`error_code`/`user_message`): prefer
    `user_message`.
  - 422 FastAPI `detail[]`: concatenate `loc`/`msg` into a readable string.
  - Otherwise fall back to a status-based default message.

## DTO contract

- Rule: DTO field names MUST NOT diverge from the backend Pydantic models; the
  backend serializes snake_case, so DTOs use snake_case (no rename layer).
- Each mapped interface is annotated `// maps: <PydanticModel>`; the contract
  validator asserts every field name exists on that model.
- `ProjectOverview`'s `task_stats`/`risk_stats`/`recent_*` are `dict`/
  `list[dict]` on the backend, so their structural sub-types are intentionally
  unmapped.

## Routing & permission

- `RequireAuth`: unauthenticated → `<Navigate to="/login" replace state={{from}}>`;
  while `loading`, shows a restoring-session state.
- Login redirects back to `from` (when not `/login`).
- Token stored in `localStorage["radeon_workbench_token"]`; never printed.

## Error handling

- `ErrorBanner` shows only `ApiError.userMessage || message`, with an optional
  Retry; the raw body/stack is never rendered.
- Pages uniformly handle loading (`LoadingBlock`), empty (`EmptyState`), and
  error (`ErrorBanner`).

## Mock data

- `mock.ts` provides `MOCK_*` samples and `createMockFetch(rules)`. Run samples
  use a `mock-` prefix and are clearly mock; they are used only in tests/offline
  regression and are never wired into the running app.

## Testing strategy

- Frontend (Vitest, run per file to avoid the Vitest worker memory leak on
  Node 25 + Windows): `client.test.ts` (baseUrl/Bearer/error matrix/network/
  timeout), `guard.test.tsx` (redirect, via `react-test-renderer` — no DOM, no
  leak), `contract.test.ts` (`// maps:` annotations present).
- Backend (unittest): `tests/test_ui_api_contract.py` calls
  `scripts/validate_ui_contract.py` to assert DTO fields and API paths match the
  backend.

## Dependencies & build

- No new Python runtime dependency is introduced, so `pyproject.toml` is
  unchanged. Frontend deps live in `web/package.json`.
- Build: `cd web && npm install && npm run build` (runs `tsc --noEmit` +
  `vite build`).
- Test: `cd web && npm test`; repo gate: `make test-governance`.
