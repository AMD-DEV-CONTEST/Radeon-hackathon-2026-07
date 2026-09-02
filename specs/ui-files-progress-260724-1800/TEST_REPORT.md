# UI-1b: files and progress — Test Report

- Spec ID: `ui-files-progress-260724-1800`
- Change level: S2
- Environment: local development environment with mocked browser requests and
  temporary project storage. No cloud model, user material, or token was used.

## Automated verification

| Command | Result | Evidence |
| --- | --- | --- |
| `.venv\\Scripts\\python.exe -m pytest tests/test_ui_files_api.py tests/test_project_api_authorization.py tests/test_projects.py -q` | PASS | 6 passed; verifies project-scoped file listing, member download, and guest/no-login rejection. |
| `npm --prefix web test` | PASS | 35 tests passed, including multipart upload and controlled source download behavior. |
| `npm --prefix web run build` | PASS | TypeScript check and Vite production build completed. |
| `.venv\\Scripts\\python.exe scripts\\validate_ui_contract.py` | PASS | DTO fields and routes match the backend contract. |
| `.venv\\Scripts\\python.exe -m pytest -q` | PASS | 522 passed, 6 skipped. |
| `.venv\\Scripts\\python.exe scripts\\validate_specs.py --strict` | PASS | Spec metadata and required records validated. |

## Covered behavior

- Source file metadata is project-scoped and never contains an absolute path.
- Unauthenticated and non-member requests are rejected.
- Members upload reference material or one task file via multipart requests.
- Downloads use an authenticated blob request to the controlled API endpoint.
- The UI differentiates `uploaded` from a backend-recorded `indexed` state.

## Cloud verification boundary

An available cloud instance is required only to verify real parsing/indexing
timing with model-backed runs. The UI intentionally does not claim a per-file
failure state until the backend persists one.
