# GTM Revenue-Positive Feedback V1

Observed: 2026-08-01  
Deadline path: 2026-08-03

## Outcome

ProofLaunch no longer treats gross revenue, attributed pipeline or a model's optimistic narrative as revenue-positive learning. A delivered, human-approved experiment may record an aggregate effect observation. If that observation reports a closed conversion or revenue, promotion into project memory is blocked until a second, source-bound unit-economics receipt exists.

The receipt reconciles candidate and comparable baseline across:

- gross revenue, discounts, refunds and chargebacks;
- variable COGS, fulfillment cost and platform fees;
- media spend, model cost and operator cost;
- closed conversions and eligible reach;
- qualified pipeline as a diagnostic field that is explicitly excluded from revenue.

## Decision algorithm

For each candidate and baseline:

```text
net revenue
  = gross revenue - discounts - refunds - chargebacks

attributed variable cost
  = variable COGS + fulfillment + platform fees
  + media spend + model cost + operator cost

contribution profit
  = net revenue - attributed variable cost
```

The system also records contribution margin, contribution per closed conversion, net revenue per eligible reach, contribution per eligible reach and refund-plus-chargeback rate. Positive feedback is ready only when:

1. candidate and baseline each have at least three closed conversions;
2. candidate contribution is positive;
3. candidate net revenue and contribution per eligible reach both beat baseline;
4. refund/chargeback rate does not regress;
5. a zero-media-budget contract has no media spend;
6. the observation and source hashes match exactly.

Passing this gate produces `continue_candidate_for_human_revenue_review`. It does not establish causal revenue and cannot activate budget, mutate strategy, select creative or publish externally.

## Runtime contract

- `POST /v1/runs/{run_id}/outcomes/{observation_id}/economics` requires the operator token and idempotency key.
- `GET /v1/runs/{run_id}/economics` exposes the aggregate collection and bounded truth flags.
- `revenue-economics.json` is resealed into the production bundle.
- A learning promotion with reported conversions/revenue fails closed if economics is absent.
- A promoted learning stores only a bounded economics summary and receipt hash; it does not copy customer identifiers or raw order data.

## Stop decisions

- `stop_and_review_zero_budget_breach`
- `stop_and_review_negative_contribution`
- `collect_more_closed_conversion_data`
- `establish_comparable_unit_economics_baseline`
- `stop_and_review_refund_or_chargeback_regression`
- `revise_one_variable_then_retest_unit_economics`

## Truth boundary

The contract proves deterministic reconciliation and a conservative promotion gate. It does not prove that production revenue has been observed, that the campaign caused revenue, that annual performance will persist, or that the product has achieved 4A/Top-1 business effect. Those claims require real source exports, human review and a valid experimental or causal design.
