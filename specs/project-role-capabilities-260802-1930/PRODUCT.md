# Product specification

- Level: S1
- Status: implemented

## Goal

Make the project workbench communicate and enforce the distinct capabilities of project administrators, project managers, members, and read-only guests.

## Behaviour

- Project administrators manage membership and roles, and can work with project content, risks, reports, and runs.
- Project managers maintain content and tasks, start runs, manage risks, and approve reports, but cannot administer members.
- Members maintain project material, tasks, report drafts, and discussions, but cannot manage risks, approve reports, or administer members.
- Guests can inspect project data, reports, evidence, audit history, and downloadable report artifacts, but cannot create, edit, submit, retry, cancel, import, upload, or comment.

## Acceptance criteria

- The active role and its capabilities are visible in the project workbench.
- Guest users do not see controls that would create or mutate project state.
- Manager-only risk and report approval controls remain unavailable to members.
- Server-side authorization remains the source of truth; UI restrictions are a usability safeguard.
