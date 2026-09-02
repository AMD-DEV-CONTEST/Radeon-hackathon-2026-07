# UI-3 risk and report center — Test Report

- Spec ID: `ui-risk-report-center-260726-1000`
- Change level: S2
- Environment: local frontend build and existing backend test suite.

## Verification

| Command | Result | Evidence |
| --- | --- | --- |
| `npm --prefix web run build` | Passed | TypeScript check and Vite production build completed. |
| `npm --prefix web test` | Passed (80) | API-client, DTO contract, and auth-guard regression passed; includes UI-3 risk/report route coverage. |
| `python scripts/validate_ui_contract.py` | Passed | DTO fields and UI paths match backend models/routes. |
| `python scripts/validate_specs.py --strict` | Passed | Required spec records validated. |
| `python -m pytest -q` | Passed (527 passed, 6 skipped) | Full backend regression. |

## Deferred scope

Structured report citation records and version snapshots are not available
from the backend report API, so UI-3 does not claim to provide them.
