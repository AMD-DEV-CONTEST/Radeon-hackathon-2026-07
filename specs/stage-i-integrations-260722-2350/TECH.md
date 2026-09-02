# Technical Specification — Stage I: External Integrations & Controlled Automation

- Level: S1
- Status: implemented

## Scope

Implement the connector abstraction, email, webhook, SCM integrations, token manager, automation tasks, and their API surfaces following existing project patterns (FastAPI APIRouter, sqlite3 persistence, unified error codes, path security).

## Implementation Plan

### 1. Connector Abstraction (`app/integrations/base.py`)
- Abstract base class `BaseConnector` with six lifecycle methods:
  `read()`, `preview_diff()`, `request_confirmation()`, `execute()`, `rollback()`, `audit()`
- Concrete connector classes implement each step.

### 2. Email Integration (`app/integrations/email.py`)
- `EmailConnector(BaseConnector)`: SMTP-backed email sending.
- Rate limiter: sliding window, configurable max per hour.
- Template-based body rendering for task_report, risk_alert, project_summary.

### 3. Webhook Integration (`app/integrations/webhook.py`)
- `WebhookRegistry`: stores registered URLs with event subscriptions in SQLite.
- `WebhookDispatcher`: sends signed JSON payloads with retry and dead-letter.
- HMAC-SHA256 signing with a shared secret per webhook.
- Retry config: max 3 attempts with delays [5, 30, 300] seconds.

### 4. SCM Integration (`app/integrations/scm.py`)
- `SCMConnector(BaseConnector)`: supports GitHub Issues and Jira backends.
- Stub implementations that pass through the full lifecycle.
- `SCMTarget` enum: GITHUB_ISSUES, JIRA.

### 5. CI/CD Trigger (`app/integrations/ci.py`)
- `CITriggerConnector(BaseConnector)`: triggers benchmark on file change.
- Reuses confirmation and audit patterns.

### 6. Token Manager (`app/services/token_manager.py`)
- `TokenManager` class: SQLite-backed, encrypted storage.
- AES-256-GCM encryption via `cryptography` library.
- Token isolation: scoped to service + project.
- `sanitize_for_log()`: redacts tokens for safe logging.

### 7. Automation Tasks (`app/services/automation_tasks.py`)
- `AutomationTaskService`: full CRUD + pause/resume + dry-run.
- SQLite persistence with tables: `automation_tasks`, `automation_task_runs`, `automation_audit_log`.
- Status machine: active → paused → active (pause) | active → cancelled (delete).

### 8. API Routers
- `app/api/integrations.py`: authenticated preview/execute pairs for email and SCM, plus project-scoped webhook registration.
- `app/api/automation_tasks.py`: CRUD + pause/resume/dry-run for automation tasks.

### 9. Error Codes
- INTEGRATION_EMAIL_FAILED, INTEGRATION_WEBHOOK_FAILED, INTEGRATION_SCM_FAILED
- INTEGRATION_RATE_LIMITED, INTEGRATION_CONFIRMATION_REQUIRED
- AUTOMATION_TASK_NOT_FOUND, AUTOMATION_TASK_ALREADY_PAUSED, AUTOMATION_TASK_ALREADY_ACTIVE
- TOKEN_NOT_FOUND, TOKEN_INVALID, TOKEN_ENCRYPTION_FAILED

### 10. Testing
- `tests/test_stage_i_integrations.py`: email, webhook, SCM connector tests.
- `tests/test_stage_i_automation.py`: automation task lifecycle tests.
- All tests use existing `tmp_path` + `TestClient` + `Settings` patterns.

## Dependencies
- `cryptography` added to `pyproject.toml` for token encryption.
- No new third-party deps beyond that — SMTP uses stdlib `smtplib`, webhooks use `httpx` (already present).

## Risks and Rollback
- Connector stubs do not call real external APIs; production activation requires backend config injection.
- Rollback: revert the commit range for this spec.

## Verification
- `python -m pytest tests/test_stage_i_*.py -v`
- `make check-specs`
- `make check-governance`
- Full test suite: `python -m pytest tests/ -q`
