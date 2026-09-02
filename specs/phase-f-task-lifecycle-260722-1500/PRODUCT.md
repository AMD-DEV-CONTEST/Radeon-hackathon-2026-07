# Feature: Phase F — Task Lifecycle & Human Confirmation

Stage: Phase F (Alpha)
Version: 1.0
Author: dev-team
Created: 2026-07-22
Updated: 2026-07-22

## Objective

Introduce a **formal task lifecycle management system** with SQLite-backed
persistence. Tasks can be created from meeting notes, design docs, or
requirement specs, queued for **human confirmation**, and tracked through
a well-defined **state machine** with a full audit trail.

CSV/XLSX bulk import is also supported, with diff preview, deduplication,
and optional conflict overwrite.

## Non-Objectives

- Real-time collaborative editing
- Push notifications or email alerts
- Gantt-chart visualization (belongs to frontend)
- Integration with external project-management tools (Jira, Notion, etc.)
- Replacing the existing report generation pipeline — reports still
  consume the task DB but fall back to CSV/XLSX files

## User Scenarios

### 1. Extract tasks from meeting notes

- User pastes meeting notes into the API or CLI
- System extracts candidate tasks via rule-based or LLM-augmented
  parsing, tagging each with confidence and source reference
- Candidates land in the **confirmation queue** as `pending_confirmation`

### 2. Human confirmation queue

- User reviews the pending queue (list / filter by status)
- For each candidate the user can **accept** (promote to `not_started`),
  **modify** (correct fields then accept), or **ignore** (discard)
- The confirmation record captures who confirmed, when, and on what basis

### 3. Bulk import with dedup

- User uploads a CSV or XLSX file containing task rows
- System returns a **diff preview**: new rows, duplicates (via
  content-based fingerprint), and conflicts (title clashes with existing
  tasks)
- User confirms the import, optionally skipping duplicates or overwriting
  conflicts
- Imported rows skip the confirmation queue and start as `not_started`

### 4. Task lifecycle management

- User changes task status through allowed transitions
- Every status change is recorded in `task_change` (event log)
- Cancelled tasks **cannot be reactivated** (terminal state)

## Acceptance Criteria

| ID      | Criterion                                                                 | Status |
|---------|---------------------------------------------------------------------------|--------|
| F-AC-01 | SQLite tables `task`, `task_change`, `confirmation`, `operation_audit`, `task_import_fingerprint` exist with proper indexes | ✅ |
| F-AC-02 | Task CRUD API: create, read, update, list (title, owner, due_date, priority, acceptance_criteria, dependencies) | ✅ |
| F-AC-03 | Candidate extraction from free-text source material                       | ✅ |
| F-AC-04 | Human confirmation queue with accept / modify / ignore actions            | ✅ |
| F-AC-05 | CSV/XLSX import: diff preview → confirm → execute, with fingerprint dedup | ✅ |
| F-AC-06 | State machine enforces allowed transitions; cancelled is final            | ✅ |
| F-AC-07 | Full audit trail records every status change and import operation         | ✅ |
| F-AC-08 | Report generation prioritizes task DB over CSV/XLSX, keeping backward compat | ✅ |
| F-AC-09 | All 39 unit + integration tests pass                                      | ✅ |
| F-AC-10 | Linter checklist passes with zero errors                                  | ✅ |

## Deliverables

| Artifact                                | Type       |
|-----------------------------------------|------------|
| `app/schemas/task_sql.py`              | Schema     |
| `app/schemas/models.py` (extended)     | Models     |
| `app/services/task_lifecycle.py`       | Service    |
| `app/api/tasks.py`                     | API Router |
| `tests/test_phase_f.py`               | Tests      |
| `specs/phase-f-task-lifecycle-*/PRODUCT.md` | This doc |
| `specs/phase-f-task-lifecycle-*/TECH.md`   | Tech spec  |
| `scripts/verify_phase_f.py`            | Verifier   |

## Dependencies

- **Phase C** (report generation) — `phase_c.py::load_tasks` now prefers
  the task DB
- `openpyxl` (already declared) — for XLSX import
- `fastapi` + `python-multipart` (already declared) — for file upload in
  import endpoints
- No new third-party packages required
