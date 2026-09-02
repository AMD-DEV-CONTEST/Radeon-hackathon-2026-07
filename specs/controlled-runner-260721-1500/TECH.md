# Controlled Run Lifecycle

- Level: S2
- Status: implemented

## Scope

- Add typed run states and a persisted run record under the configured output
  directory.
- Add a JSONL audit writer scoped to a single run.
- Add a `ControlledRunner` that accepts an explicit tool registry and follows
  the fixed pipeline only.
- Add project-scoped run creation and read endpoints.

## Implementation plan

- `app/services/runs.py` persists `RunState` as JSON under
  `outputs/<project_id>/runs/`.
- `app/observability/audit.py` appends structured event records under
  `logs/runs/`.
- `app/agent/runner.py` validates the fixed sequence and stops after at most
  the configured `agent_max_steps`.
- `app/api/runs.py` creates queued runs only. A later integration change will
  inject the real RAG, task, and report tools before execution.

## Risks and rollback

- Risk: persisted run metadata can outlive an interrupted request.
- Rollback: remove the run endpoints and leave generated JSON/JSONL files as
  non-executable diagnostic artifacts.

## Verification

- Unit tests cover API lifecycle persistence, audit JSONL records, fixed tool
  ordering, missing-tool failure, and the maximum-step boundary.
