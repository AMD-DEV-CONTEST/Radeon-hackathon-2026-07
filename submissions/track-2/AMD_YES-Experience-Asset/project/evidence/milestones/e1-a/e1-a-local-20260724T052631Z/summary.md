# Evidence packet: `e1-a-local-20260724T052631Z-9b03730`

## Outcome and scope

- Engineering/user outcome: the first E1-A canonical-state, local-runtime,
  SQLite, local-vLLM, observability, health, JSON Schema and OpenAPI contracts
  are implemented at commit `9b03730bbc8e7c7daa0bd6df6b237edfa6cbd0b5`.
- Explicit non-goals: no M1 ingestion/workflow, React UI, route/export feature,
  deletion, performance Candidate, remote fallback, or Baseline claim.
- Commit / Issue / PR: implementation commit `9b03730`; Issue
  [#5](https://github.com/kinnyuww/amd-devmaster-track2-agent/issues/5);
  PR not created at packet time.
- AC / L1 / L2: AC-03, AC-04, AC-11, AC-17, AC-19, AC-22; cross-cutting
  foundation; Canonical state, Persistence and resume, Local inference,
  Failure behavior, Observability, Runtime permission.

## Reproduction

- Fixture or approved sanitized scenario:
  `e1-a-public-tool-smoke-v1`, derived only from the checked-in synthetic tool
  proposal example; SHA-256
  `1dd19eb3a8045ce2e95d942d62677994ba7118f16182c0a44d17677a3f6f26a8`.
- Environment/model/profile: macOS 15.6 Apple Silicon, Python 3.12.13;
  intended real profile Qwen2.5-14B-Instruct BF16/8K through loopback vLLM.
  No AMD GPU or model artifact was present locally.
- Commands and exit status:
  - `bash -n scripts/*.sh` — 0
  - `python3 -m py_compile scripts/*.py` — 0
  - `python3 -m unittest discover -s qa/tests -v` — 0, 16 passed
  - `bash qa/gates/pr_gate.sh --mode contract` — 0, PASS
  - `.venv/bin/python scripts/export_contracts.py --check` — 0
  - `.venv/bin/ruff check .` — 0
  - `.venv/bin/pytest` — 0, 27 passed

## Observed results

- Terminal state: `NOT_VERIFIED` for the complete E1-A gate.
- Product/artifact/UI evidence: nine checked-in contract/example files;
  public adapters, immutable snapshot history, restart, stale-write, explicit
  terminal result, loopback-only model endpoint, inert tool proposals, default
  raw-log removal and health/OpenAPI behavior are covered by public tests.
- Measurements: 16 existing QA tests and 27 Lane A tests passed.
- Failures, retries, and recovery: no local test failure remains. Stale writes
  fail closed and preserve the current version; invalid model/tool output grants
  no permission. The rollback target is merged E0 commit `efa5adb`.
- Unverified areas: W7900/ROCm identity, real model revision/license/load,
  localhost vLLM structured/tool smoke, GPU use, OOM and restart behavior.

## Decision and history

- Result class: `NOT VERIFIED`
- Known risks and conditional owner/deadline: Eas000n must run and retain the
  Issue #5 Radeon Cloud viability commands before E1-A readiness or combined E1
  promotion. Lane B must review the first frozen contracts.
- Rollback/known-good profile: revert implementation commit `9b03730` or return
  to E0 `efa5adb`; no main-branch change has occurred.
- Supersedes/prior packet: none. The future W7900 packet must be append-only and
  reference this packet.
- Raw/large evidence location and checksum: no raw GPU evidence exists on this
  Mac. When run, use
  `/workspace/amd-track2-agent/evidence/<run_id>/raw/`; do not put raw model
  content in Git.
