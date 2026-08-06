# Research Ledger V1

Research Ledger V1 freezes the 25 studies mapped one-to-one to TODO 0107–0131.
Each row records a primary source, version date, official implementation status,
hardware scale, original task scope, known failures, transferable mechanism and
a bounded local experiment.

The ledger separates four decisions:

- `direct_adopt`: adopt a schema, workflow or released component without
  inheriting a paper's result claim;
- `equivalent_simplification`: test a budget-equivalent mechanism instead of a
  foundation-scale reproduction;
- `ablation_only`: run only as a controlled comparison;
- `infeasible_current_budget`: preserve the source and rejection reason without
  pretending a single Radeon reproduced a multi-node result.

Every hypothesis has equal-budget controls, objective gates, a finite GPU/wall/API
budget and an explicit stop condition. Subjective-example-only experiments are
invalid. Paper-reported numbers never populate observed metrics. Only a live
`reproduced` or `radeon_observed` receipt can enter the result leaderboard or the
innovation-combination selector.

The frozen V1 ledger intentionally records zero executed studies, zero result
leaders and zero promoted combinations. This is the correct starting state: the
registry and experiment contracts exist, but no academic result has been
reproduced in this workspace.

Negative results are immutable entries under `research/negative_experiments/`.
The empty V1 manifest means no live research experiment was run; it does not mean
the candidate mechanisms have no failure modes.
