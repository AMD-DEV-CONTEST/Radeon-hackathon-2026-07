# Quality Owner Runbook

> **Final-sprint override (2026-08-05):** this historical runbook no longer
> creates E5–E9 private runs, deep-audit waits, or owner promotion locks. Use
> [`spec/FINAL_SPRINT_EXECUTION_PACKAGE.md`](../spec/FINAL_SPRINT_EXECUTION_PACKAGE.md).
> No executable private suite or hidden answer key exists. Review is
> asynchronous and proportional; only substantive code, business, safety,
> locality, evidence, or submission problems block.

This runbook describes the work that remains with the quality owner. It does
not expose hidden cases or numerical scoring.

## Phase 0 — before product code

1. Keep `main` as the public source of truth and require task branches + PRs.
2. Run `bash qa/gates/pr_gate.sh --mode contract` on proposed QA-contract
   changes.
3. Review changes to `qa/schema/experience_asset.schema.json` with the product
   engineer. A schema change is prospective and versioned; it never rewrites
   old evidence.
4. Keep the quality-owner workspace outside this repository and backed up to an
   approved encrypted location.

## Phase 1 — first runnable vertical slice

Ask the developer for:

- the command or endpoint that accepts a fixture and emits the canonical asset;
- the matching progress/state event;
- a terminal status, model-call count, and trace/run identifier;
- the exact commit SHA and local W7900/ROCm serving profile.

Run artifact mode for the implemented fixture. If the complete fixture reaches
one rendered output end to end, use `qa/perf/BASELINE_READINESS.md`; do not
invent performance floors before this point.

## Phase 2 — risk-based PR review and combined milestone audits

For each PR:

1. Read the outcome, diff, linked Issue/evidence, affected behavior, risk and
   rollback. Do not block only because a template field, comment, wording or
   historical status is imperfect when the needed information is otherwise
   clear.
2. Run public CI and the tests for the affected behavior. Secret disclosure,
   functional regressions, contracts, data safety, privacy/permission, phased
   RAG, local inference and competition-critical evidence remain hard gates.
3. Classify findings as `BLOCKER`, `CONDITIONAL`, or `NIT/BACKLOG`. Every
   blocker names the affected public requirement, observable evidence and the
   minimum fix. Critical/High blocks; Medium needs an owner, residual risk and
   deadline; Low never blocks by itself.
4. Run a private blind subset only at a deep-audit window or when concrete
   evidence indicates a Critical/High boundary regression. Routine PRs do not
   require a private run or the user's synchronous attendance.
5. After the first complete review round, do not introduce new format-only or
   wording-only blockers. Newly observed substantive risk may still block.

The normal cadence through functional freeze is:

| Gate | Review mode | Private blind work | User synchronous review |
|---|---|---|---|
| E2 / M1 | Deep technical audit of first useful slice | Required | Asynchronous product review; feedback is due before E4 promotion and does not block E3 unless it identifies P0 drift |
| E3 / M2 | Lightweight asynchronous technical gate | Deferred to E4 | Not required |
| E4 / M3 | Deep combined audit of E3+E4 and the judge-visible Agent loop | Required | Not required unless a material product choice appears |
| E5 / M4 | Lightweight asynchronous technical gate; public RAG denial/non-pollution tests remain hard | Deferred to E6 | Not required |
| E6 / M5 | Deep combined audit of E5+E6 knowledge, route, privacy and permission behavior | Required | Optional only for a new policy choice |
| E7 | Full end-to-end functional-freeze audit | Required | Required final product acceptance |

This means three deep-audit windows before E7 starts and four through E7
acceptance. Before E7, the user has one asynchronous E2 product review and no
planned synchronous hard lock; E7 is the one required final user acceptance.
Code review, CI, W7900 checks and private-suite execution are asynchronous by
default. While E2 feedback is pending, E3 may continue after the E2 technical
gate, but unresolved user feedback must be incorporated or explicitly resolved
before E4 promotion.

At a deep-audit milestone freeze:

```bash
bash qa/gates/milestone_gate.sh M2 \
  --asset path/to/asset.json \
  --fixture-id chair_public_complete \
  --progress path/to/progress.json \
  --output /tmp/m2-signoff.md
```

For M4 and M5, also pass `--retrieval-trace path/to/retrieval-trace.json`.
Verify publicly that current-source retrieval remains available while
cross-asset summary search is denied before card readiness, detail is denied
before relation confirmation, and a no-match/decline path remains usable. Run a
separate private variant against the same public invariants without disclosing
its payload, expected output or score.

Complete the private result and decision manually. The generated draft must
not be committed if it contains private-run details.

## Phase 3 — performance work

Before a run, copy `qa/perf/candidate_plan.template.json`, declare the affected
component, primary metric, quality floors, all intentional configuration
changes, and rollback. Freeze manifests before looking at results.

Run server, Agent-task, and refinement-UX measurements separately. Preserve
failures and raw records. A candidate may improve one layer while regressing
another; it is not promoted when a Critical/High quality floor regresses.

## Phase 4 — submission

- Map all ACs to public evidence and private sign-off status.
- Retain W7900/ROCm proof, vLLM arguments, model revision/license, manifests,
  sample sizes, failure rates, mean/median/p95 where meaningful, and rollback.
- Publish only scrubbed evidence. Never publish raw private input, blind cases,
  secrets, model caches, or hidden scoring.
