# Test report

- Level: S1
- Status: implemented

## Automated verification

- `cd web && npm run build` — passed.
- `cd web && npm test -- --run` — passed: 92 tests.
- `python -m pytest -q` — passed: 528 passed, 6 skipped.
- `python scripts/validate_specs.py --strict` — passed: 0 validation errors.

## Manual verification checklist

- Sign in as a project administrator and verify member management plus all project work controls are available.
- Sign in as a project manager and verify risk assignment/lifecycle and report approval are available, while member management is unavailable.
- Sign in as a member and verify uploads, task work, report drafts, and discussion are available, while risk lifecycle and approval controls are unavailable.
- Sign in as a guest and verify reports, evidence, and audit information remain visible while all mutation controls are absent.
