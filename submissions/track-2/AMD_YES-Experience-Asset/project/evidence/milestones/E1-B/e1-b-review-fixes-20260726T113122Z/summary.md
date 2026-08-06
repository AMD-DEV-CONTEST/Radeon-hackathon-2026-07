# E1-B PR #8 review-fix evidence

Packet: `E1-B-review-fixes-20260726T113122Z`
Issue: #6 · PR: #8 · implementation: `c3318db8a97b49136b692b5d8fec7774d5e27516`

## Outcome

This append-only packet covers only the three blockers adopted by the owner in
review `4781442252`:

1. Live browser status now always uses same-origin `/api`. Query/env base URL
   overrides are removed, and the Vite proxy rejects anything except a pure
   loopback HTTP(S) origin using `localhost`, `127.0.0.1`, or `::1`.
2. The live provider fails closed and distinguishes HTTP, timeout, caller
   cancellation, network/body transport failure, invalid JSON, and a payload
   incompatible with the minimum `HealthStatusV1` contract.
3. Delayed mock requests remove the exact registered abort listener on both
   completion and cancellation, and pre-cancelled requests reject immediately.

No backend, vendored contract, relation/status business rule, dependency, GPU,
performance, E2+, PR metadata, or merge behavior changed.

## Verification

| Gate | Result |
|---|---|
| Contract provenance | PASS — 15/15 |
| TypeScript / ESLint / production build | PASS |
| Vitest | PASS — 9 files, 89 tests |
| Mock Playwright | PASS — 15; 1 live test skipped without live URL |
| AC-30 retained traces | PASS — 5/5 |
| Repository QA | PASS — shell/Python checks, 31/31 unit tests, contract gate |
| Diff/credential boundary | PASS |

The packet retains three development failures: an invalid jsdom/Vite-config
test boundary, an independently found JSON-body cancellation classification
gap, and one body-phase fake-timer ordering error. Each was diagnosed rather
than retried blindly, and the final suites above passed.

## Decision, risk, and rollback

- **Result:** `CONDITIONAL`; local gates pass, while post-push CI and owner
  re-review remain pending.
- **Review threads:** all three remain unresolved until the reviewer accepts
  the pushed fixes.
- **Dependency risk:** inherited development-tool audit findings remain outside
  scope; no `npm audit fix --force` or lockfile change was made.
- **Rollback:** normal revert of
  `c3318db8a97b49136b692b5d8fec7774d5e27516`; never reset or force-push the
  shared branch.
- **Supersedes:** conclusions of
  `E1-B-final-contract-20260726T092032Z` for the newer implementation head;
  that historical packet remains unchanged.
