# Test report

- Level: S1
- Status: implemented

## Verification

- `npm --prefix web run build` — passed.
- `npm --prefix web test -- --run` — passed: 92 tests.
- `python scripts/validate_specs.py --strict` — passed: 0 validation errors.

## Manual scenarios

- New writable project: guide starts at project-material upload.
- Project with material but no imported tasks: guide directs the user to the task import tab.
- Project with tasks but no report run: guide directs the user to the report action.
- Empty risk/report data: only a compact explanatory card is shown.
