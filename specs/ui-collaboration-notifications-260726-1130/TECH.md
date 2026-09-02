# UI-4 collaboration and notifications — Technical Record

- Spec ID: `ui-collaboration-notifications-260726-1130`
- Level: S2
- Status: implemented

## Design

- `CollaborationCenter` is mounted below the selected project dashboard.
- Member list and mutations use `/projects/{project_id}/members`; admin-only
  visibility is derived from the current project member record, but backend
  `admin` role guards remain mandatory.
- The notification API is current-user scoped rather than project scoped. The
  UI locally includes only records whose server link is an internal
  `/projects/{selected_project}/...` route. Records without a matching link
  are not exposed in the selected-project inbox.
- Existing comments API extracts @mentions server-side and creates the
  notification records; UI-4 does not parse identity claims in the browser.

## Rollback

Revert this branch. It adds no schema or migration and does not alter existing
authorization rules.
