# Public QA Framework

> **Final-sprint disclosure (2026-08-05):** the owner has removed the separate
> private blind-test and stage-promotion loop for E5–E9. Repository review found
> no implemented private runner, hidden fixture, Gold Answer, secret weight, or
> unpublished threshold. All known evaluation requirements are now public in
> [`spec/FINAL_SPRINT_EXECUTION_PACKAGE.md`](../spec/FINAL_SPRINT_EXECUTION_PACKAGE.md).
> Developers may use that matrix directly and continue after self-verification;
> only substantive product, safety, locality, evidence, or submission failures
> block. Never publish credentials or genuine private user data.

This directory is the teammate-visible quality and benchmark contract for the
Experience Asset P0. It contains no blind cases, gold answers, private scoring
weights, or pass thresholds.

## What runs now

The contract gate is runnable before product code exists:

```bash
bash qa/gates/pr_gate.sh --mode contract
python3 -m unittest discover -s qa/tests -v
```

It validates the seven public fixture categories, public expected invariants,
schemas, scripts, and repository disclosure boundary.

Once an implementation emits a canonical asset and progress event, run the
artifact gate:

```bash
bash qa/gates/pr_gate.sh --mode artifact \
  --asset path/to/asset.json \
  --fixture-id chair_public_complete \
  --progress path/to/progress.json \
  --retrieval-trace path/to/retrieval-trace.json
```

Artifact mode is fail-closed: omitting the asset or fixture identifier is a
blocking error. A green contract gate does **not** claim that the product or an
acceptance criterion has passed.

`--retrieval-trace` is optional for M1-M3 artifact checks and mandatory in
`milestone_gate.sh` for M4/M5. The public checker enforces AC-30 without
publishing hidden cases: current-source retrieval may run early, but cross-asset
summary search waits for `KnowledgeCardReady`, detailed history waits for user
relation confirmation, and historical retrieval cannot silently mutate current
statements.

## Review cadence

The historical cadence table below is superseded for E5–E9 by the final-sprint
package. There is one consolidated functional-freeze/A0 integration boundary,
one Stage 2 evaluation, and one E9 submission boundary; no private run or
synchronous user approval is required between them.

| Time | Team-visible action | Quality-owner action |
|---|---|---|
| Every PR | Contract gate; attach public evidence and AC/L1/L2 mapping | Review failure class and decide block/conditional/backlog |
| Runnable vertical slice | Artifact gate on affected fixtures | Run matching blind variants locally |
| Milestone freeze | Generate a public sign-off draft | Complete private result and promotion decision |
| Performance candidate | Submit a prospective experiment plan and complete manifests | Confirm quality floors before promotion |

## Public/private boundary

For the final sprint, there is no private evaluation gate. The seven public
fixture contracts plus the disclosed adversarial/failure checklist are the
complete functional validation contract currently available.

- Public fixtures explain categories and invariant behavior, not exact answers.
- The private suite stays outside this Git checkout and off the shared Radeon
  pod. Only the result class, affected public AC, severity, and a minimal public
  reproduction are shared with developers.
- LLM-as-judge may triage qualitative output. It cannot be the sole evidence
  for fabrication, privacy bypass, lost state, unauthorized execution,
  non-local inference, or concealed failure.

See [QUALITY_OWNER_RUNBOOK.md](QUALITY_OWNER_RUNBOOK.md) for the owner's exact
workflow, [AC_COVERAGE.md](AC_COVERAGE.md) for what can and cannot be verified
before product code, and [perf/README.md](perf/README.md) for
baseline/candidate rules.
