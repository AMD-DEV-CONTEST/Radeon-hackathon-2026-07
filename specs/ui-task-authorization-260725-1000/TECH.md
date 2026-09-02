# UI-2 task API authorization repair — Technical Record

- Level: S2
- Status: implemented
- Depends-on: ui-task-workbench-260724-2200

## Design

- All task routes require at least project guest membership.
- All writes require project member membership.
- API handlers overwrite client-submitted actor fields with the authenticated
  username. Compatibility fallback applies only when the explicit legacy test
  authorization bypass is enabled.
- Structured evidence excerpts are not stored by the task lifecycle backend.
  UI-2 therefore displays the persisted source reference and confirmation
  basis only; a future evidence API is required before claiming excerpts.

## Rollback

Revert this repair branch before merging UI-2. The unprotected UI-2 branch
must not be merged into `main` on its own.
