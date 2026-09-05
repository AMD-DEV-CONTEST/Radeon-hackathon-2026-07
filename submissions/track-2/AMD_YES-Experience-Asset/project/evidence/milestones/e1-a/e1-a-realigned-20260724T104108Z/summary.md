# Evidence packet: `e1-a-realigned-20260724T104108Z-29e4e8a`

## Outcome and scope

- Engineering outcome: PR #7 is aligned to `main@db3a534` and now contains the
  latest E1-A1 contracts plus an E1-A2 durable fake loop.
- The realignment adds `AgentRunStateV1`, `WorkPlanV1`,
  `PolicyDecision`, `ToolExecutionRecord`, `VerificationReport`, migration 2
  run checkpoints, scoped retrieval contracts and deterministic Runtime policy.
- Public progress now uses
  `percent_basis=milestones_done/milestones_total`; indeterminate progress omits
  percentage fields.
- Explicit non-goals remain M1 product ingestion, production RAG/indexing,
  frontend work, route/export implementation and performance optimization.
- Commit / Issue / PR: `29e4e8a`; Issue #5; Draft PR #7.

## Reproduction

- Public scenario: `e1-a-public-tool-smoke-v1` version 1.1.0.
- Base contract: merged hardening checkpoint `main@db3a534`.
- Commands:
  - `bash -n scripts/*.sh` — PASS
  - `python3 -m py_compile scripts/*.py` — PASS
  - `python3 -m unittest discover -s qa/tests -v` — 31 passed
  - `bash qa/gates/pr_gate.sh --mode contract` — PASS
  - `.venv/bin/python scripts/export_contracts.py --check` — PASS
  - `.venv/bin/ruff check .` — PASS
  - `.venv/bin/pytest` — 34 passed

## Observed results

- E1-A1 local contract checkpoint: PASS, pending cross-lane review.
- E1-A2 durable fake loop: PASS.
- Persisted phases: `PLANNED`, `PROPOSED`, `POLICY_DECIDED`,
  `TOOL_RECORDED`, `VERIFIED_TERMINAL`.
- Restart restores the latest Agent run checkpoint and unchanged canonical
  version.
- Runtime denial produces `POLICY_BLOCKED`, no tool observation and a
  verification report.
- Cross-asset candidate search is denied before Knowledge Card readiness.
- Detailed historical retrieval is denied without a confirmed related asset.
- Empty query and invalid `top_k` fail closed.
- E1-A3: `NOT_VERIFIED`; no local result is presented as W7900 evidence.

## Decision and history

- Result class: `NOT VERIFIED` for complete E1-A.
- E1-A1/A2 are ready for teammate review; E1-A3 still blocks promotion.
- Supersedes: `e1-a-local-20260724T052631Z-9b03730`.
- Raw real-model evidence remains restricted to
  `/workspace/amd-track2-agent/evidence/<run_id>/raw/`.
