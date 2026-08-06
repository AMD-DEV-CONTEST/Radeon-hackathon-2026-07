# E7 deterministic delivery — isolated evidence

## Outcome and scope

- Implementation commit: `ca53e8d5b1c11bf2e55cfe54f64d62bbfb20dd57` on
  `codex/e7-deterministic-delivery`, based on open PR #28 head
  `a0b042d812d1358814b3f7743a58541e653acff0`.
- Result: `ISOLATED_READY`. E7's canonical route-draft envelope, deterministic
  private preview/HTML/Markdown/JSON, exact approval gating, supersession,
  idempotent export and restart-safe two-phase deletion are implemented and
  locally verified.
- The implementation stays within E7 modules, renderers, fixtures, tests and a
  feature-scoped UI. It does not modify the frozen domain schema, OpenAPI,
  migration numbering, shared repository, API root or `web/src/App.tsx`.
- Track 2 relevance: makes the Agent's final delivery private by default,
  permission-bound, auditable and reproducible. It creates no new W7900/ROCm,
  vLLM, model-quality or performance claim.

## Reproduction

- Public inputs: the `complete`, `privacy-risk`, `correction` and
  `route-ineligible` scenarios in `tests/fixtures/e7_delivery_scenarios.json`.
- Python: isolated Python 3.12.12 environment at `/private/tmp/amd-e7-venv`.
- Reproduce the Agent and repository checks:

  ```bash
  PYTHONPYCACHEPREFIX=/private/tmp/amd-e7-pycache /private/tmp/amd-e7-venv/bin/ruff check .
  PYTHONPYCACHEPREFIX=/private/tmp/amd-e7-pycache /private/tmp/amd-e7-venv/bin/pytest
  bash -n scripts/*.sh
  PATH=/private/tmp/amd-e7-venv/bin:$PATH PYTHONPYCACHEPREFIX=/private/tmp/amd-e7-pycache python3 -m py_compile scripts/*.py
  PATH=/private/tmp/amd-e7-venv/bin:$PATH PYTHONPYCACHEPREFIX=/private/tmp/amd-e7-pycache python3 -m unittest discover -s qa/tests -v
  PATH=/private/tmp/amd-e7-venv/bin:$PATH PYTHONPYCACHEPREFIX=/private/tmp/amd-e7-pycache bash qa/gates/pr_gate.sh --mode contract
  ```

- Reproduce the frontend and browser checks:

  ```bash
  cd web
  NODE_OPTIONS=--no-experimental-webstorage npm test
  NODE_OPTIONS=--no-experimental-webstorage npm run verify:contracts
  NODE_OPTIONS=--no-experimental-webstorage npm run typecheck
  NODE_OPTIONS=--no-experimental-webstorage npm run lint
  NODE_OPTIONS=--no-experimental-webstorage npm run build
  npx playwright test --config e2e/e7.playwright.config.ts
  NODE_OPTIONS=--no-experimental-webstorage npm run e2e
  ```

## Observed results

- Ruff: PASS.
- Pytest: 229 passed; one third-party deprecation warning.
- Public QA and contract gates: 34 passed; disclosure/credential and all seven
  public fixture contracts passed.
- Frontend: 136 tests passed; contract provenance, typecheck, ESLint and
  production build passed.
- Browser: the exact checked-in renderer output passed a no-server Chromium
  identity/self-contained/interaction check; the full browser suite passed 16
  executable cases with four existing live-backend cases skipped by design.
- Recovery tests cover export replay, deletion second confirmation, file and
  SQLite failure, partial effects, retry after restart and content-free audit
  terminal state.

Retained failures are listed in `manifest.json`: an incompatible host Python,
sandbox DNS/Chromium restrictions and Node 25 experimental `localStorage`
interference were each reproduced and recovered without changing product
behavior.

## Decision and history

- Result class: `PASS` at the isolated E7 boundary only.
- Mock boundary: `FrozenE6ApprovalAdapter` validates the frozen exact-binding
  contract but is not the real E6 service.
- Unverified: live E6→E7 integration, shared repository/API/app-root wiring,
  independent review, W7900/ROCm/vLLM, production deployment and external
  publication.
- Required next gate: independent teammate or separate Codex-session review of
  the Draft PR, followed by real E6 integration after PR #28/E6 are available.
- Rollback: normal `git revert ca53e8d5b1c11bf2e55cfe54f64d62bbfb20dd57`.
  No shared migration, deployment or external publication occurred.
