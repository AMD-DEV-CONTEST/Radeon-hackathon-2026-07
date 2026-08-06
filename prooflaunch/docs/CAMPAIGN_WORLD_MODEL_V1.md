# Campaign World Model V1

Campaign World Model V1 is an auditable decision-state contract for a GTM employee. It is not a narrative simulator and does not claim a learned world model, Radeon execution, campaign uplift, or future-state accuracy.

## State and action boundary

Every snapshot contains twelve typed components: campaign, evidence, audience, market, brand, creative, asset, channel, risk, memory, uncertainty, and cost. The whole snapshot is content-addressed. Evidence distinguishes supported and invalid claims; market observations cannot be relabeled synthetic input; assets carry rights and identity locks; memory exposes stale/conflicted atoms; cost separates budget, spent, projected, token, and GPU use.

Seven action families are whitelisted: research, plan, creative, generate, audit, repair, and rollback. Each has explicit mutation scopes. Publish, send, and release are deliberately outside the world-model action set. State-stale, scope-breaking, over-budget, hard-risk-blocked, or unapproved high-risk actions are rejected before transition.

Terminal, blocked, and awaiting-human states are distinct. Hard risk blocks permit only research, audit, repair, or rollback. High uncertainty creates an approval boundary. Human approval is represented by a content-addressed receipt and never inferred from model text.

## Prediction and trajectory boundary

Each prediction exposes a projected next-state hash and six non-collapsed values: expected 4A quality, risk, latency, diversity, cost, and uncertainty. It is always `simulated`. The controller generates exactly three profiles—conservative, balanced, and exploratory—from the same initial state. Counterfactual pairs hold the state, seed, assumptions, and predictor settings constant while changing only the action.

Pareto selection maximizes 4A value and diversity while minimizing risk, latency, cost, and uncertainty. No scalar weighted sum is used to hide tradeoffs.

## Ledger, calibration, and learning loop

Every accepted transition records the parent record hash, action hash, state hash, and diff hash. The ledger verifies continuity before replay. Snapshots can be compressed losslessly and visualized as a small Mermaid operational graph.

Prediction/actual receipts keep unobserved results empty. Observed deviations are measured by dimension and large deviations become content-addressed hard samples. Attribution is exclusive and ordered:

1. missing or stale actual input → data error;
2. action mismatch or execution failure → executor error;
3. matched successful execution on fresh data → world-model error.

Future-state accuracy reports per-dimension MAE and the rate for which all core dimensions stay within the preregistered tolerance. Uncertainty calibration compares predicted uncertainty with observed error events. These formulas are tested on synthetic fixtures, but the frozen card leaves all real metrics and checkpoint selection null.

## Artifacts

- `src/prooflaunch_remix/v10_world_model.py`
- `tests/test_v10_world_model.py`
- `config/cortex_x_v10_world_model_v1.json`
- `evidence/v10/world-model-v1-mechanical-fixture.json`
