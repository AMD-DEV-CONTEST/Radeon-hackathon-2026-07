# UI-2: task workbench and human confirmation

## Goal

Extend the authenticated project workbench with a task workbench. A member can
review tasks with filters, inspect a task's acceptance criteria, source reference and
change history, import a CSV/XLSX task list through an explicit
preview-then-confirm flow, decide on extracted candidate tasks in a
confirmation queue, and drive status changes that the server alone validates.
Every decision records who made it, when, and on what basis.

## Acceptance

- The task list can be narrowed by status (server-side query) and by owner,
  priority and due date (client-side refinement of server data).
- A task detail view shows status, acceptance criteria, dependencies, source
  reference, confirmation basis and the full change history (who / when /
  why) as recorded by the backend.
- A CSV/XLSX import always shows the server-computed diff (new / duplicate /
  conflict rows plus a row preview) before anything is persisted; the import
  happens only after an explicit confirmation that records the operator.
- Candidate tasks extracted from meeting notes wait in a confirmation queue;
  a human can accept, accept-with-changes, or ignore each item, and the
  decision stores the operator, basis and optional notes. A processed item
  cannot be processed twice.
- The UI offers only the status transitions allowed by the lifecycle state
  machine, and any server rejection (invalid transition, cancelled-is-final)
  is surfaced as a recoverable API error — the server remains the single
  authority.
- An audit view lists task-related operations (import, confirmation,
  transition) with operator and timestamp, read from the backend audit log.
- The UI never invents state: everything rendered comes from API responses.
