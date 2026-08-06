# Evidence packet: `e1-contract-20260724T084655Z-14a43a4`

## Outcome and scope

- Engineering/user outcome: PR #9 aligns the P0 product contract, L1/L2/L3,
  bounded Agent Runtime, competition proof, and public QA with phase-gated
  cross-asset RAG.
- Explicit non-goals: no product implementation, milestone acceptance, remote
  model installation, benchmark delta, public tunnel, production deployment,
  or private blind-test disclosure.
- Commit / Issue / PR: `14a43a4`; Issue #5; PR #9.
- AC / L1 / L2: AC-03/04/09/10/18/22/23/25/30; M4/M5/cross-cutting;
  Evidence discipline, Retrieval phase integrity, Runtime permission,
  Persistence and resume, Local inference, Failure behavior, Observability.

## Reproduction

- Fixture or approved sanitized scenario: `chair_public_complete` and
  `chair_resume` public contract fixtures.
- Environment/model/profile: repository-only contract verification; proposed
  Qwen2.5-14B BF16 profile is frozen but not claimed as installed or verified.
- Commands and exit status: all commands in `manifest.json` exited 0; 29 public
  unit tests passed and the contract PR gate passed.

## Observed results

- Terminal state: `CONDITIONAL`.
- Product/artifact/UI evidence: public AC-30 retrieval trace schema/checker,
  expected fixture contracts, teammate architecture/specification documents.
- Measurements: 29 public unit tests; contract gate PASS.
- Failures, retries, and recovery: the first PR-create call produced an empty
  body because of shell expansion order; the body was then replaced using a
  file-backed GitHub edit and rechecked.
- Unverified areas: replacement-pod SSH, ROCm/W7900, model snapshot, vLLM Tool
  Call, full Agent Runtime trace, and all performance/Bonus claims.

## Decision and history

- Result class: `CONDITIONAL` — repository contract is ready for review, but
  no GPU/model/product milestone is accepted.
- Known risks and conditional owner/deadline: PR #7/#8 must realign after PR #9
  reaches `main`; the quality/integration owner must verify that before E1 merge.
- Rollback/known-good profile: `git revert 14a43a4`; `origin/main` at `efa5adb`
  remains the pre-hardening base.
- Supersedes/prior packet: none.
- Raw/large evidence location and checksum: none; no private/raw payload was
  added to Git.
