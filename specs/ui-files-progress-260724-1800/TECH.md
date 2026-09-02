# UI-1b: files and progress — Technical Record

- Level: S2
- Status: implemented
- Depends-on: ui-project-runs-260724-1400

## Scope

- Add a project-scoped `GET /api/projects/{project_id}/files` metadata API.
- Keep upload and download under the same protected project route family.
- Add typed multipart upload and protected blob download to the Web API client.
- Add a material library to the project workbench with source and task-list
  upload controls, loading/error states, and server-reported processing state.

## Status semantics

- `uploaded`: saved in the controlled project source area but no indexed
  document-version record exists yet.
- `indexed`: a current document-version record exists with an index version.
- No guessed parse failure is shown. A per-file failure state will be added
  only when the backend persists a reliable failure record.

## Security

- The browser sends a Bearer token for upload/download requests.
- The backend resolves source paths with `ensure_project_path`; it does not
  accept an absolute path or permit traversal outside the current project.
- The UI renders only API data and cannot infer or access other projects.

## Rollback

Revert this feature branch. UI-1a remains functional without the material
library.
