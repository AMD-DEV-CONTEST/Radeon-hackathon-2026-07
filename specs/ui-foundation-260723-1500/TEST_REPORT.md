# Verification Report

## Local verification

```powershell
cd web
npm install
npm run build        # tsc --noEmit + vite build
npm test             # vitest (per-file, all green)

cd ..
$env:PYTHONPATH="."
python scripts/validate_specs.py --strict
python scripts/validate_ui_contract.py
python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

## Test case inventory (mapped to acceptance criteria)

| ID  | Acceptance criterion                          | Test                                         | Result |
| --- | --------------------------------------------- | -------------------------------------------- | ------ |
| AC1 | Unauthenticated → redirect to login          | `guard.test.tsx` (react-test-renderer)       | PASS   |
| AC2 | Readable error, no raw stack                  | `errors.ts` mapping + `feedback.tsx`         | PASS   |
| AC3 | Build + static checks pass                    | `npm run build`                              | PASS   |
| AC4 | Key API client tests pass                     | `client.test.ts` (error matrix/network/Bearer/baseUrl) | PASS   |
| AC5 | DTO fields match backend Pydantic            | `scripts/validate_ui_contract.py` + `tests/test_ui_api_contract.py` | PASS   |
| AC6 | Token not in logs/Git                         | code review (localStorage only, no console)  | PASS   |
| AC7 | No fake "model already ran"                   | `mock.ts` (`mock-` prefix, test-only)         | PASS   |

## Results

- Frontend Vitest: 3 files, 29 tests — all passed (client 11, contract 15,
  guard 3).
- Backend unittest contract: `tests/test_ui_api_contract.py` — 2 cases passed
  (DTO fields, API paths).
- Repo full unittest (`make test-governance`): all passed (8 tests).
- Governance: `validate_specs --strict`, `validate_pr_title`, `git diff
  --check` all passed.

## Issues found & fixes

- The backend uses non-uniform path prefixes (`/auth`, `/api/projects`,
  `/projects/...`, `/notifications`). Declared explicitly in `paths.ts` and
  verified by the contract test so the frontend never guesses a prefix.
- `ProjectOverview.task_stats`/`risk_stats`/`recent_*` are `dict`/`list[dict]`
  on the backend (no named models); the matching frontend sub-types are
  structural and intentionally unmapped.
- `NotificationEntry` actually uses `kind`/`recipient_id` (not `type`/
  `project_id`); the DTO was corrected to match.
- `scripts/` shadowed by a site-packages namespace package broke the existing
  `test_validate_pr_title`; fixed by adding `scripts/__init__.py` (regular
  package, cwd wins over site-packages) — safe for all environments.
- Vitest 2 + Node 25 + Windows leaked ~4 GB across test files (DOM env) and
  OOM'd at teardown. Fixed by: upgrading to Vitest 3, running each file in its
  own process, using `react-test-renderer` (no DOM) for the route-guard test,
  and keeping the dev proxy in a separate `vite.dev.config.ts` so the test
  runner does not start a proxy agent.

## Conclusion

All UI-0 acceptance criteria are met and the contract is frozen and
machine-checked. Later stages (UI-1…UI-5) can implement concrete pages on top
of this contract without modifying the public API client or DTO contract.
