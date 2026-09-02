# UI-1a technical design

- Level: S2
- Status: implemented

## Dependencies

- `feat/ui-foundation` for the typed API client and authenticated app shell.
- `fix/project-api-authorization` must merge before this feature is released,
  so the project list and run endpoints enforce membership server-side.

## Planned implementation

- Extend TypeScript DTOs and API client for project overview, run list, run
  detail/progress, execute, cancel, retry, and artifact URLs.
- Add project selection, dashboard cards, run history/detail panel, polling,
  and controlled artifact downloads.
- Add API-client and UI behavior tests with mocked fetch; use cloud only for
  final real-model acceptance.

## Implementation notes

- The project overview reads only `/projects/{project_id}/overview` and the
  project list reads only `/api/projects`; both are membership-protected by
  the production authorization configuration.
- Artifact links are not exposed as server paths. The client downloads blobs
  from `/api/projects/{project_id}/runs/{run_id}/artifacts/{artifact_name}`
  with its Bearer token.
- Active runs are polled every three seconds and all mutating controls are
  disabled while their request is in progress.

## Rollback

Revert this feature branch; UI-0 remains a standalone foundation.

## Cloud acceptance boundary

Real-model and RAG acceptance is intentionally pending until the cloud
instance is available. This does not block the local UI contract, build, and
mocked API regression checks recorded in `TEST_REPORT.md`.
