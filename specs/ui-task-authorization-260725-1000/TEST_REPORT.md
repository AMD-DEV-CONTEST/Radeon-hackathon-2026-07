# UI-2 task API authorization repair — Test Report

- Spec ID: `ui-task-authorization-260725-1000`
- Change level: S2
- Environment: local FastAPI TestClient with temporary SQLite/project storage.

## Verification

| Command | Result | Evidence |
| --- | --- | --- |
| `python -m pytest tests/test_task_api_authorization.py tests/test_phase_f.py tests/test_project_api_authorization.py -q` | Passed (45) | Covers authentication, guest write denial, and actor spoofing. |
| `npm --prefix web test` | Passed (71) | Confirms updated client payload contracts and omission of client-owned audit actors. |
| `npm --prefix web run build` | Passed | TypeScript check and Vite production build completed. |
| `python scripts/validate_ui_contract.py && python scripts/validate_task_ui.py` | Passed | API/DTO contract and 7-status, 15-transition lifecycle mirror remain in sync. |
| `python scripts/validate_specs.py --strict && git diff --check` | Passed | Governance records and whitespace checks passed. |
| `python -m pytest -q` | Passed (527 passed, 6 skipped) | Full backend regression completed. |

## Deferred scope

The task lifecycle currently persists source references rather than structured
evidence excerpts. This repair deliberately does not fabricate evidence data.
