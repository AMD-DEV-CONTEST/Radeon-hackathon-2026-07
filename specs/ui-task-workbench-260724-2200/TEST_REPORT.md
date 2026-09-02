# UI-2: task workbench and human confirmation — Test Report

- Spec ID: `ui-task-workbench-260724-2200`
- Change level: S2
- Environment: local development environment with mocked browser requests and
  a temporary SQLite/project store for the acceptance smoke run. No cloud
  model, user material, or token was used.

## Automated verification

| Command | Result | Evidence |
| --- | --- | --- |
| `npm --prefix web test` | PASS | 71 tests passed (40 API-client incl. 23 new task cases, 28 contract, 3 auth-guard). Covers URL/verb/payload for every task method, multipart import, nested and flat structured error mapping, and the lifecycle mirror. |
| `npm --prefix web run build` | PASS | TypeScript check and Vite production build completed. |
| `python scripts/validate_ui_contract.py` | PASS | All `// maps:` DTO fields are subsets of the backend Pydantic models; every `API_PATHS` entry matches a backend route. |
| `python scripts/validate_task_ui.py` | PASS | 7 statuses and 15 transitions in sync with `ALLOWED_TRANSITIONS` / `PhaseFTaskStatus`. |
| `python -m unittest discover -s tests -p "test_*.py"` (make test-governance) | PASS | 11 tests OK, including the new `tests/test_task_ui_contract.py` mirror tests. |
| `python -m pytest -q` | PASS | 525 passed, 6 skipped (full backend suite). |
| `git diff --check` + `python scripts/validate_specs.py --strict` (make check-governance) | PASS | No whitespace damage; spec metadata and required records validated. |

## Acceptance smoke (temporary script, removed after the run)

A scripted end-to-end pass replayed the exact UI call sequence against a real
app instance (FastAPI TestClient, temporary storage): CSV `import-preview`
(diff shown, nothing persisted) → `import-confirm` (2 imported, operator
recorded) → list + server-side status filter → allowed transition accepted →
invalid transition rejected with `TASK_INVALID_TRANSITION` → history records
who/when/why → extraction produced 2 candidates → `submit-candidates` →
pending queue listed → accept recorded operator and basis →
double-processing rejected with `CONFIRMATION_ALREADY_PROCESSED` → audit log
contained import/transition/confirmation operations. Result: 14/14 checks
passed.

## Covered behavior

- Task list filtering (status server-side; owner/priority/due client-side).
- Task detail with acceptance criteria, source reference, confirmation basis,
  and history.
- Preview-then-confirm CSV/XLSX import with duplicate/conflict flags.
- Confirmation queue accept / modify / ignore with operator, basis, notes.
- Lifecycle mirror pinned to the backend graph; server stays authoritative.
- Structured error bodies (flat and `detail`-nested) map to one `ApiError`.

## Cloud verification boundary

Backend task routes require project guest access for reads and project member
access for writes. Confirmation, import confirmation, and status-transition
audit identities are derived from the authenticated server-side user, not a
browser-supplied value. Real XLSX parsing was exercised via the backend's
existing import pipeline tests; browser-level manual testing on a deployed
instance remains a follow-up.
