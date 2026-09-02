# UI-5 Technical Specification

- Level: S2
- Status: implemented

## Backend boundary

- All `/monitor/*` routes use `require_system_admin` at router level.
- Existing `/admin/*` routes already use the same dependency.
- SCM preview and execute remain separate POST routes. The backend validates that execution matches the previously previewed payload and consumes the confirmation ID once.

## Frontend boundary

- `IntegrationAdminCenter` has no webhook, password, token, or secret field.
- `AdminOperations` queries protected APIs and renders nothing after an HTTP 403. It only presents a safe model summary; it deliberately omits `model_path`.
- Browser confirmation is an additional UX guard, not an authorization control; backend role and one-time-ID checks remain authoritative.

## Verification

- Python test proves an authenticated non-admin gets 403 from `/monitor/queue`.
- Vitest proves preview and execute use distinct API endpoints and that the operations client uses protected backend paths.
