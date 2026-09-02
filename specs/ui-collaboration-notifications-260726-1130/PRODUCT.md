# UI-4 collaboration and notifications — Product Record

- Spec ID: `ui-collaboration-notifications-260726-1130`
- Change level: S2
- Status: implemented
- Depends on: `ui-risk-report-center-260726-1000`

## Goal

Expose the existing project membership and current-user inbox APIs in the
workbench, so a small team can manage project access and follow notifications
created by assignments, approvals, comment replies, and @mentions.

## Acceptance

- Every member can see the project member roster; only admins see mutation
  controls, while the API remains the authority for every write.
- Project notifications show only notifications whose server-provided internal
  link belongs to the selected project; no external link is opened.
- Users can filter unread notifications and mark one or all as read.
- Existing risk/report discussion components continue to create server-side
  comments and @mentions, whose notification records are shown in the inbox.
