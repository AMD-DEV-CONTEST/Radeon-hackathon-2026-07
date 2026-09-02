# UI-1a: project dashboard and run center — Test Report

- Spec ID: `ui-project-runs-260724-1400`
- Change level: S2
- Environment: local Windows development environment; mocked browser API
  responses only. No model, source document, token, or cloud data was used.

## Automated verification

| Command | Result | Evidence |
| --- | --- | --- |
| `npm --prefix web test` | PASS | 31 tests passed: API client/auth guard, API contract annotations, controlled run API and artifact download client behavior. |
| `npm --prefix web run build` | PASS | TypeScript type check and Vite production build completed. |
| `.venv\\Scripts\\python.exe scripts\\validate_ui_contract.py` | PASS | Frontend DTO fields and registered backend paths match. |
| `.venv\\Scripts\\python.exe -m pytest -q` | PASS | 521 passed, 6 skipped. |
| `.venv\\Scripts\\python.exe scripts\\validate_specs.py --strict` | PASS | Spec metadata and required records validated. |
| `git diff --check` | PASS | No whitespace errors. |

## Covered behavior

- Project list and overview use authenticated project APIs.
- A report run is created and then dispatched through controlled run endpoints.
- Run status is polled only while it is non-terminal.
- Cancel/retry requests disable duplicate clicks while pending.
- Artifact data is fetched with the Bearer token from the controlled artifact
  endpoint; no filesystem path is rendered or used as a browser link.

## Deferred cloud verification

The following needs an available cloud instance and real model service:

1. Create a real project with source material and tasks.
2. Start a run from the Web workbench and observe all live progress states.
3. Download the generated Markdown report, risk CSV, and next-week plan.
4. Confirm unauthorized users receive `403` and cannot see or download another
   project's run data.
