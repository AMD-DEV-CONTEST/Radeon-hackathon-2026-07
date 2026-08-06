# Contextual strategy-memory arbitration V1

## Product outcome

ProofLaunch no longer treats the newest approved memory as the next campaign's
strategy. Every new run freezes the signed project context, compares each
human-promoted aggregate learning with the new operating context, and emits a
content-addressed decision receipt before the production pack, channel plan,
calendar or experiment can reference the memory.

The governed dimensions are industry, B2B/B2C model, lifecycle, budget,
industry risk, market, and the channels selected by the deterministic strategy
compiler.

## Hard transfer boundaries

- A B2B learning cannot be recommended to a B2C run, or vice versa.
- A small/scaled-budget learning cannot enter a zero-budget run.
- A standard-risk learning cannot enter a high-regulation run.
- A legacy portable memory without a frozen applicability context remains
  visible and reviewable but is ineligible for strategy application.
- Two eligible memories with different directives on the same channel create a
  blocking conflict. No winner is chosen until named-human arbitration.

## Named-human conflict closure

A blocked decision can now be resolved through
`POST /v1/runs/{run_id}/strategy-memory-resolutions`. The command requires the
authenticated tenant, the operator approval token, an idempotency key, the
exact frozen `decision_sha256`, one conflict channel, one memory ID already in
that conflict, and a bounded reason. The append-only record binds the resolver,
timestamp, complete conflict set, selected winner, source run and content hash.

The source run is never rewritten. Its strategy, schedule, experiment and
resolution-context artifact stay byte-identical and its effective application
remains blocked. The Cockpit instead exposes
`future_resolution_recorded=true` and directs the operator to create a new run.
Only that later run freezes the project resolution context. If its learning
context, operating context and deterministic channel set reproduce the exact
base decision digest, the application becomes
`resolved_pending_named_human_application`; otherwise the resolution is not
used. A resolution still cannot publish, schedule, spend, or silently mutate
strategy.

Exact industry, business model, lifecycle, budget, risk, market and channel
matches increase the deterministic applicability score. An adjacent lifecycle
or a zero-budget learning transferred into a resourced run receives a bounded,
disclosed partial score. A score below 8 is not recommendable.

## Unified decision spine

The same `ProofLaunchStrategyMemoryDecisionV1` digest is bound into:

- `gtm-strategy.json` as the complete inspectable receipt;
- `content-calendar.json` and `seven-day-schedule.json` as schedule summaries;
- `experiment.json` as the preregistered next-cycle memory reference;
- the GTM Cockpit as inherited, eligible, conflicting and recommended counts;
- the signed device-A/device-B synthetic lifecycle demonstration.

This connects cross-device memory, strategy, content scheduling, channel
selection and measurement without creating an autonomous mutation path.

The separate `ProofLaunchStrategyMemoryApplicationV1` binds the base decision,
the frozen `ProofLaunchStrategyMemoryResolutionContextV1`, unresolved channels,
selected directives and any applied resolution hashes. Keeping decision,
resolution and application as three receipts makes retroactive mutation
detectable rather than blending human adjudication into model output.

## Authority boundary

`eligible_pending_human_application` means only that one prior aggregate
learning is contextually relevant. It does not apply copy, change a channel,
move a calendar slot, activate budget, publish, send or establish causal lift.
All such fields remain false. Synthetic demonstration data remains synthetic
and cannot support 4A, Top-1, breakout or production-revenue claims.

## Executable evidence

- Unit and conflict tests: `tests/test_gtm_learning_memory.py`
- Runtime inheritance tests: `tests/test_v10_submission_runtime.py`
- Tenant/idempotency API tests: `tests/test_v10_submission_production_api.py`
- Read-only device A/B demo: `scripts/run_gtm_revenue_memory_demo.py`
- Sealed receipt: `evidence/v10/gtm-revenue-memory-demo.json`
- Device-B cockpit: `artifacts/gtm-revenue-memory-demo-v1/device-b-next-cycle-gtm-cockpit.json`
