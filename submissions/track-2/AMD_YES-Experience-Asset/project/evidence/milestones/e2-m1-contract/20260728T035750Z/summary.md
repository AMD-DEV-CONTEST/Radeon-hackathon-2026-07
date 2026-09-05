# E2 / M1 Contract Checkpoint Evidence

Result: `READY_FOR_QUALITY_OWNER_CONFIRMATION`

This packet describes implementation commit
`7fcfc3bde34e6075bff4f90dea7e0a595e27ba31` on
`codex/e2-m1-experience-brief` and Draft PR
[#16](https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/16).

## What is ready for confirmation

- M1 request, output, error, progress and invalidation contracts;
- `Experience Brief v0.1`, M1 Workspace JSON Schema and OpenAPI;
- complete, incomplete, contradictory, correction and resume Fixture behavior;
- named negative cases and current-source-only retrieval boundary;
- AC/L1/L2/Track 2 mapping, owners, review boundary and rollback.

The authoritative review files are:

- `contracts/checkpoints/e2-m1-contract-fixtures-v1.json`;
- `docs/kinnyu/E2_M1_CONTRACT_CHECKPOINT.md`.

## Reproduction result

- public QA: 31/31;
- backend: 77/77 and Ruff PASS;
- frontend: 95/95, vendored contracts 15/15, typecheck/lint/build PASS;
- real loopback FastAPI/React Playwright: 17/17;
- repository contract gate: PASS.

No W7900 or real model was required for this checkpoint. The implementation
commit preserves a localhost-only inference boundary and treats real
W7900/vLLM verification as later E2 work.

The first GitHub static check and its manual re-run retained an AC-22 failure:
the original PR event used `Public QA:` instead of the checker's exact
`Test/fixture result:` field, and GitHub re-used that old event payload on
manual re-run. The visible PR body is corrected. The evidence follow-up commit
creates a new synchronize event so CI reads the current body.

That synchronize run passed the metadata step and then exposed two redundant
blank lines at EOF through `git show --check`. They were removed without a
behavior change; the observation remains recorded here rather than being
hidden.

## Decision boundary

This packet is not a quality-owner `PASS`. Until `kinnyuww` confirms the first
checkpoint, E3 remains blocked. After confirmation, E3 may prepare only its
contract, Mock, public Fixture, negative tests and isolated modules. E3 cannot
integrate unmerged E2 state, become Ready, merge or claim completion before E2
promotion.

The Draft PR also contains Backend/UI WIP. Confirming this packet does not
accept E2 checkpoints 2–3, Serving Reference S1, Vertical Slice V1, E2
promotion, E8 Baseline or any performance claim.
