# TECH.md — Phase F 任务生命周期 & 人工确认

- Level: S2
- Status: implemented

## 1. Overview

Phase F introduces a formal task persistence layer (SQLite) and a
human-in-the-loop confirmation workflow.  Tasks are stored in a
per-project SQLite database at `{sqlite_path}/projects/{project_id}/tasks.db`.

Key components:

| Layer       | Module                                |
|-------------|---------------------------------------|
| Schema/DDL  | `app/schemas/task_sql.py`            |
| Pydantic    | `app/schemas/models.py` (Phase F block) |
| Service     | `app/services/task_lifecycle.py`      |
| API         | `app/api/tasks.py`                    |

## 2. Data Model

### 2.1 Core tables

```
task
├── id (TEXT PK)              # UUID4
├── project_id (TEXT)         # FK to project concept
├── title (TEXT NOT NULL)
├── owner (TEXT?)
├── due_date (TEXT?)          # ISO date string
├── priority (TEXT?)
├── acceptance_criteria (TEXT?)
├── dependencies (TEXT?)      # JSON array string
├── source_ref (TEXT?)
├── status (TEXT)             # ENUM (see state machine)
├── confirmed_by / confirmed_at / confirmation_basis / confirmation_notes
├── created_at / updated_at

task_change
├── id (INTEGER PK AUTO)
├── task_id (TEXT FK → task.id)
├── project_id (TEXT)
├── from_status (TEXT?)
├── to_status (TEXT NOT NULL)
├── changed_by / change_reason
├── changed_at

confirmation
├── id (INTEGER PK AUTO)
├── task_id (TEXT FK → task.id)
├── project_id (TEXT)
├── candidate_* fields (title, owner, due_date, priority, acceptance, dependencies)
├── source_ref / source_kind / confidence
├── status (pending | accepted | ignored)
├── confirmed_by / confirmation_basis / confirmation_notes / confirmed_at
├── created_at

operation_audit
├── id (INTEGER PK AUTO)
├── project_id / entity_type / entity_id
├── operation / operator / details
├── created_at

task_import_fingerprint
├── id (INTEGER PK AUTO)
├── project_id / fingerprint (unique composite index)
├── task_id (FK → task.id)
├── imported_at
```

### 2.2 State machine

```
         ┌──────────────────┐
         │pending_confirmation│
         └───┬──────────┬───┘
    accept   │          │  ignore
             ▼          ▼
         ┌──────┐   ┌─────────┐
         │not   │   │cancelled│  ← terminal
         │started│  └─────────┘
         └──┬─┬─┘
    start    │ │ cancel
             ▼ │
       ┌──────────┐
       │in_progress├──── delay ──► ┌────────┐
       └──┬──┬──┬─┘               │ delayed │
   most │  │  │cancel              └──┬─┬─┬──┘
       ▼  │  └──────────►┌───────┐   │ │ │
┌──────────────┐         │cancelled│◄─┘ │ └─ in_progress
│mostly_completed│       └────────┘     │
└──┬───────┬───┘                        │
   │done   │ back                        ▼
   ▼       ▼                      ┌─────────┐
┌─────────┐                    ┌─────────┐  completed│
│cancelled│                    │ completed│
└─────────┘                    └─────────┘
```

Key rules:
- `cancelled` is **terminal** — no transition out
- `completed` is **terminal** — no transition out
- `mostly_completed` can go back to `in_progress` (rework)
- `delayed` can return to `in_progress` or be cancelled/completed

## 3. API Design

Base path: `/api/projects/{project_id}/tasks`

### 3.1 Route ordering (CRITICAL)

Static routes MUST be declared before `{task_id}` dynamic routes to prevent
path capture:

```
GET    .../tasks/confirmation-queue   ← static (MUST come first)
POST   .../tasks/confirmation/{id}    ← static
GET    .../tasks/audit-log            ← static
POST   .../tasks/extract             ← static
POST   .../tasks/submit-candidates   ← static
POST   .../tasks/import-preview      ← static
POST   .../tasks/import-confirm      ← static
GET    .../tasks/{task_id}            ← dynamic (AFTER all statics)
PATCH  .../tasks/{task_id}            ← dynamic
POST   .../tasks/{task_id}/transition ← dynamic
GET    .../tasks/{task_id}/history    ← dynamic
```

### 3.2 Endpoint summary

| Method | Path                              | Purpose                       |
|--------|-----------------------------------|-------------------------------|
| POST   | `/tasks`                          | Create task                   |
| GET    | `/tasks`                          | List tasks (filter by status) |
| GET    | `/tasks/confirmation-queue`       | List pending confirmations    |
| POST   | `/tasks/confirmation/{task_id}`   | Accept / modify / ignore      |
| GET    | `/tasks/audit-log`                | Operation audit trail         |
| POST   | `/tasks/extract`                  | Extract candidates from text  |
| POST   | `/tasks/submit-candidates`        | Submit candidates to queue    |
| POST   | `/tasks/import-preview`           | Preview CSV/XLSX import       |
| POST   | `/tasks/import-confirm`           | Confirm and execute import    |
| GET    | `/tasks/{task_id}`                | Get task by ID                |
| PATCH  | `/tasks/{task_id}`                | Update task fields            |
| POST   | `/tasks/{task_id}/transition`     | Change task status            |
| GET    | `/tasks/{task_id}/history`        | Status change history         |

## 4. Implementation Notes

### 4.1 Service layer (`TaskLifecycleService`)

- Initialises tables on first `_connect()` via `conn.executescript(DDL)`
- All DB writes within a context manager block; commits are explicit
- Import fingerprint uses SHA256 over `{title}|{owner}|{due_date}|{priority}`

### 4.2 Import flow

```
upload CSV/XLSX → _parse_csv / _parse_xlsx → build candidate list
  → preview endpoint returns TaskImportDiff (new/dupe/conflict counts + preview rows)
  → confirm endpoint re-parses the file, applies dedup + overwrite rules
  → writes tasks with status="not_started" (bypasses confirmation queue)
  → records fingerprints for future dedup
```

### 4.3 Report integration

`phase_c.py::load_tasks()` now:

1. Tries SQLite task DB first (reads confirmed, non-pending, non-cancelled tasks)
2. Falls back to CSV/XLSX files in `source/` directory
3. Converts `TaskRecord` → `Task` model for downstream report generation

## 5. Testing

39 tests in `tests/test_phase_f.py`:

| Category               | Count | Examples                                  |
|------------------------|-------|-------------------------------------------|
| Unit — state machine   | 4     | All valid transitions, invalid, edge cases |
| Unit — CSV/XLSX parse  | 3     | CSV parse, XLSX parse, empty files        |
| Service — CRUD         | 5     | Create, list, update, delete              |
| Service — state        | 3     | Transition, history, invalid transition   |
| Integration — API CRUD | 7     | Create, read, list, update, 404 cases     |
| Integration — confirm  | 4     | Queue, accept, modify, ignore             |
| Integration — import   | 6     | CSV/XLSX preview, confirm, dedup          |
| Integration — audit    | 2     | Audit log, extraction                     |
| Integration — report   | 2     | Task DB priority, empty fallback          |
| Contract — models      | 2     | Schema validation, enum values            |
| **Total**              | **39**|                                           |

Run: `python -m pytest tests/test_phase_f.py -v`

## 6. Security / Operational Concerns

- File upload uses `python-multipart` with `UploadFile`; files are
  processed in-memory only (no temp file spill)
- Project isolation is enforced per-project per SQLite database
- Audit trail is append-only (no delete or update on `operation_audit`)
- All DB access is serialised within a single SQLite file; no concurrent
  write contention expected at current scale

## 7. References

- `docs/FULL_PRODUCT_ROADMAP.zh-CN.md` — Phase F section
- `app/schemas/task_sql.py` — DDL and state machine definition
- `app/services/task_lifecycle.py` — service implementation
- `tests/test_phase_f.py` — test coverage
