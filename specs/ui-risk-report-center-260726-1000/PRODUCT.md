# UI-3 risk and report center — Product Record

- Spec ID: `ui-risk-report-center-260726-1000`
- Change level: S2
- Status: implemented
- Depends on: `ui-task-workbench-260724-2200`

## Goal

Provide a project-scoped workspace for reviewing detected risks, recording
human risk actions, authoring report drafts, and routing reports through the
existing member/PM approval boundary.

## Acceptance

- Risk records can be filtered by severity and lifecycle, inspected with their
  recorded description, assigned to a project member, and discussed.
- PM/admin users can acknowledge, resolve, dismiss, or reopen a risk. The UI
  asks for explicit confirmation before resolving or dismissing high/critical
  risks; the backend remains the permission authority.
- Members can create, edit, submit, and export report drafts. Only PM/admin
  users are offered approval actions; the API also enforces that restriction.
- Approval decisions and comments are retrieved from the server history.
- PDF/DOCX downloads use the protected report export endpoints.

## Boundary

The existing report API stores Markdown content but does not yet expose
structured report-citation records. UI-3 does not fabricate source links;
the preview states this limitation explicitly. Citation-level navigation is a
future backend/API change.
