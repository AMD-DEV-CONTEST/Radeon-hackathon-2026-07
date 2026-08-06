# Quality Framework Hardening

## Status

- Route: FEATURE
- Requirement status: APPROVED by the user's instruction to continue and
  finish the Claude Code QA work on 2026-07-24 AEST.
- Engineering status: IMPLEMENTED
- Verification status: PASS
- Iteration status: CLOSED
- User acceptance: ACCEPTED on 2026-07-24 AEST
- Product implementation status: NOT STARTED; this checkpoint does not claim
  any product AC has passed.

## Engineering proposal

- Why: turn the quality-owner draft into a fail-closed, versioned public/private
  framework before teammate implementation begins.
- Affected areas: public fixtures/contracts, deterministic checks, PR and
  milestone gates, performance evidence manifests, CI, private runner safety,
  and owner documentation.
- Checkpoints: public contract gate; artifact gate; performance admissibility;
  private preflight; documentation and CI.
- Verification: positive/negative unit tests, JSON/Shell/Python checks, gate
  runtime checks, disclosure scan, and original repository checks.
- Material decisions: public QA is versioned in the team repository; private
  blind material stays outside Git/shared pod; metrics remain adjustable only
  through prospective versioned plans; baseline-derived thresholds remain
  unset until the first real W7900 baseline.
- Risks and rollback: CI may block incomplete PR metadata; rollback by reverting
  this isolated feature branch. No production, model, database, or public
  service is changed.
- Explicit non-goals: no product code, no fake benchmark numbers, no private
  scoring in Git, no dependency installation on Radeon Cloud, no deployment.

## Acceptance criteria for this checkpoint

| ID | Criterion |
|---|---|
| QAF-01 | Seven public fixture categories and teammate-visible invariants are versioned without private gold/thresholds. |
| QAF-02 | Contract mode runs before product code and does not claim product acceptance. |
| QAF-03 | Artifact mode fails when asset, fixture, or progress evidence is absent and rejects unsafe examples. |
| QAF-04 | Performance manifests and prospective plans are internally validated; undeclared comparison drift fails. |
| QAF-05 | VRAM sampling normalizes captured AMD-SMI JSON or fails without emitting misleading evidence. |
| QAF-06 | CI runs deterministic public checks and PR metadata enforcement. |
| QAF-07 | Private evaluation requires a local endpoint, explicit post-baseline thresholds, and real product outputs. |
| QAF-08 | The owner has a phase-by-phase runbook and the team has a stable spec entrypoint. |

## Evidence

| Criterion | Evidence | Status | Remaining risk |
|---|---|---|---|
| QAF-01 | Fixture inventory checker and seven fixture/expected pairs; disclosure scan | PASS | Private backup remains an owner operation |
| QAF-02 | `pr_gate.sh --mode contract` reports that product ACs are not claimed | PASS | None |
| QAF-03 | Positive artifact-gate test plus missing-artifact and unsupported-claim negative tests | PASS | Real product artifacts do not exist yet |
| QAF-04 | Manifest/plan unit tests and declared/undeclared comparison tests | PASS | Real W7900 runs remain future product evidence |
| QAF-05 | AMD-SMI normalization unit test and fail-without-output behavior | PASS | Exact live AMD-SMI shape will be reconfirmed on the pod |
| QAF-06 | Workflow and PR template inspection; same commands pass locally | PASS | First remote GitHub Actions run is not yet observed |
| QAF-07 | Private wrapper rejects missing endpoint/config; judge code has no hard-coded numeric threshold | PASS | DeepEval correctly remains blocked until product output/baseline |
| QAF-08 | `qa/README.md`, runbook, coverage map, perf guide, and `spec/README.md` entrypoint | PASS | Human adoption by teammates |

### Commands and observed results

- `python3 -m unittest discover -s qa/tests -v` — PASS, 16 tests.
- `bash qa/gates/pr_gate.sh --mode contract` — PASS.
- `bash -n scripts/*.sh qa/gates/*.sh qa/perf/*.sh` — PASS.
- `python3 -m py_compile scripts/*.py qa/scripts/*.py qa/tests/*.py` — PASS.
- All public QA JSON files parsed with `jq empty` — PASS.
- `git diff --check` — PASS.
- Private wrapper with no endpoint/config — expected FAIL before any blind test
  could be misreported as green.
- Credential/private-path scan — PASS; no quality-owner-only path is included.

### Verdict

`PASS` for the bounded quality-framework checkpoint. Product AC-01..AC-29
remain `NOT VERIFIED`; they require implementation and representative runtime
evidence. No release or deployment was performed.

Historical note: AC-30 (phase-gated cross-asset RAG) was approved later on
2026-07-24 and is governed by the current iteration plus the public retrieval
trace checker; it was not part of this earlier checkpoint verdict.

## User acceptance

- Decision: ACCEPTED
- Evidence: the user replied “确认接受” on 2026-07-24 AEST.
- Boundary: acceptance closes only this QA-framework checkpoint. It does not
  approve the pending product engineering proposal or mark product ACs passed.
