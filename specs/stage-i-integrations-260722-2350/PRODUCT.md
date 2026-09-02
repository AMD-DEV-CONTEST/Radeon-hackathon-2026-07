# Product Specification — Stage I: External Integrations & Controlled Automation

| Field | Value |
|---|---|
| Spec ID | `stage-i-integrations-260722-2350` |
| Level | S1 |
| Date | 2026-07-22 |
| Status | implemented |

## Background

Stage I adds safe, auditable external integrations to the Office Agent. Every connector follows a uniform lifecycle: read → preview diff → request human confirmation → execute → rollback on failure → audit. No action reaches an external system without explicit confirmation.

## User-Visible Behavior

### 1. Email Integration
- `POST /api/integrations/email/preview` creates a reviewed preview and one-time confirmation ID; `POST /api/integrations/email/execute` sends that exact confirmed payload.
- Accepts `{type, project_id, recipient, subject, body, attachments[]}`.
- Rate-limited: max 10 emails per hour per recipient domain.
- Only confirmed, reviewed content is sent — no raw internal data.

### 2. Webhook Integration
- `POST /api/integrations/webhook/register` registers an external callback URL for a project; it does not dispatch during registration and never returns the shared secret.
- Subscribes to event types: `task_status_change`, `risk_lifecycle_change`, `project_member_change`.
- Delivers JSON payloads with HMAC signature for verification.
- Failed deliveries retry 3× with exponential backoff (5 s → 30 s → 300 s), then dead-letter.

### 3. SCM Integration
- `POST /api/integrations/scm/preview` and `POST /api/integrations/scm/execute` create and apply an exact confirmed SCM change.
- Read-only sync first: fetch external state, preview diff.
- Confirmed write-back: after user approval, commit/push.
- Supports GitHub Issues and Jira as target types.

### 4. CI/CD Trigger
- Triggers a quality benchmark run after file change in a project.
- Accessible via the automation task system (below).

### 5. Automation Tasks
- `GET /api/projects/{id}/automation-tasks` lists all automation tasks for a project.
- `POST /api/automation-tasks` creates a new scheduled or trigger-based task.
- `POST /api/automation-tasks/{id}/pause` pauses an active task.
- `POST /api/automation-tasks/{id}/resume` resumes a paused task.
- `POST /api/automation-tasks/{id}/dry-run` simulates the task without side effects.
- Every task has an audit log, trigger records, and notification records.

### 6. Token Manager
- API keys and tokens are stored server-side with AES-256-GCM encryption.
- Tokens are never exposed in logs, reports, error messages, or browser.
- Access requires explicit service authorization.

## Non-Goals
- No OAuth 2.0 flow (API keys only for this phase).
- No real GitHub/Jira API calls — connectors are stubbed with the full lifecycle, ready for real backends.
- No Slack/Teams integration (email covers notifications for now).
- No multi-step CI pipeline orchestration — single trigger only.

## Acceptance Criteria

| # | Criterion | Status |
|---|-----------|--------|
| I.1 | Email endpoint sends structured content with rate limiting | [x] |
| I.2 | Webhook registry with HMAC-signed delivery + retry + dead-letter | [x] |
| I.3 | SCM connector supports read/preview/confirm/commit lifecycle | [x] |
| I.4 | CI/CD trigger via automation task | [x] |
| I.5 | Automation tasks: create, pause, resume, dry-run, audit log | [x] |
| I.6 | Token manager encrypts keys at rest, blocks log exposure | [x] |
| I.7 | All integration actions require confirmation step | [x] |
| I.8 | Dead-letter queue for unprocessable webhook/email payloads | [x] |
| I.9 | All endpoints return unified error codes | [x] |
