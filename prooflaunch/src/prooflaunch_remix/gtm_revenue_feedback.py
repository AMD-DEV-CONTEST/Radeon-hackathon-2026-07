from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Mapping

from .ledger import canonical_json


class RevenueFeedbackError(ValueError):
    """Aggregate unit-economics evidence is incomplete, inconsistent, or unsafe."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOP_LEVEL_KEYS = frozenset(
    {
        "economics_id",
        "effect_observation_id",
        "effect_observation_sha256",
        "source_reference_sha256",
        "currency",
        "measurement_basis",
        "candidate",
        "baseline",
    }
)
_ECONOMICS_KEYS = frozenset(
    {
        "conversions",
        "gross_revenue_usd",
        "discounts_usd",
        "refunds_usd",
        "chargebacks_usd",
        "variable_cogs_usd",
        "fulfillment_cost_usd",
        "platform_fees_usd",
        "media_spend_usd",
        "model_cost_usd",
        "operator_cost_usd",
        "qualified_pipeline_usd",
    }
)
_MEASUREMENT_BASES = frozenset({"cash_collected", "accrual_recognized"})


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise RevenueFeedbackError(f"{name} is invalid")
    return value


def _money(value: object, name: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise RevenueFeedbackError(f"{name} must be finite")
    observed = float(value)
    if observed < 0 or observed > 1_000_000_000:
        raise RevenueFeedbackError(f"{name} is outside its bound")
    return round(observed, 6)


def _economics(value: object, name: str) -> dict[str, int | float]:
    if not isinstance(value, Mapping) or set(value) != _ECONOMICS_KEYS:
        raise RevenueFeedbackError(f"{name} must contain exactly {sorted(_ECONOMICS_KEYS)}")
    conversions = value["conversions"]
    if type(conversions) is not int or conversions < 0 or conversions > 1_000_000_000:
        raise RevenueFeedbackError(f"{name}.conversions is outside its bound")
    output: dict[str, int | float] = {"conversions": conversions}
    for key in sorted(_ECONOMICS_KEYS - {"conversions"}):
        output[key] = _money(value[key], f"{name}.{key}")
    return output


def _derived(
    row: Mapping[str, int | float], *, eligible_reach: int
) -> dict[str, int | float | None | bool]:
    gross = float(row["gross_revenue_usd"])
    net = gross - float(row["discounts_usd"]) - float(row["refunds_usd"]) - float(
        row["chargebacks_usd"]
    )
    costs = sum(
        float(row[key])
        for key in (
            "variable_cogs_usd",
            "fulfillment_cost_usd",
            "platform_fees_usd",
            "media_spend_usd",
            "model_cost_usd",
            "operator_cost_usd",
        )
    )
    contribution = net - costs
    conversions = int(row["conversions"])
    return {
        "net_revenue_usd": round(net, 6),
        "total_attributed_variable_cost_usd": round(costs, 6),
        "contribution_profit_usd": round(contribution, 6),
        "contribution_margin_rate": round(contribution / net, 8) if net > 0 else None,
        "gross_revenue_per_conversion_usd": round(gross / conversions, 6)
        if conversions
        else None,
        "contribution_per_conversion_usd": round(contribution / conversions, 6)
        if conversions
        else None,
        "net_revenue_per_eligible_reach_usd": round(net / eligible_reach, 8),
        "contribution_per_eligible_reach_usd": round(
            contribution / eligible_reach, 8
        ),
        "refund_chargeback_rate_on_gross": round(
            (float(row["refunds_usd"]) + float(row["chargebacks_usd"])) / gross,
            8,
        )
        if gross > 0
        else None,
        "positive_contribution_observed": contribution > 0,
        "qualified_pipeline_usd": float(row["qualified_pipeline_usd"]),
        "pipeline_counted_as_revenue": False,
    }


def compile_revenue_economics(
    payload: Mapping[str, object],
    *,
    effect_observation: Mapping[str, object],
    zero_budget: bool,
    minimum_closed_conversions: int = 3,
) -> dict[str, object]:
    """Bind contribution economics to an existing aggregate effect observation.

    Qualified pipeline remains a diagnostic field and never enters recognized
    revenue, contribution profit, or the positive-feedback decision.
    """

    if not isinstance(payload, Mapping) or set(payload) != _TOP_LEVEL_KEYS:
        raise RevenueFeedbackError("revenue economics fields are incomplete or unknown")
    economics_id = _identifier(payload["economics_id"], "economics_id")
    if payload["effect_observation_id"] != effect_observation.get("observation_id"):
        raise RevenueFeedbackError("economics is not bound to the effect observation ID")
    observation_sha = payload["effect_observation_sha256"]
    if (
        not isinstance(observation_sha, str)
        or not _SHA256.fullmatch(observation_sha)
        or observation_sha != effect_observation.get("observation_sha256")
    ):
        raise RevenueFeedbackError("economics is not bound to the effect observation digest")
    source_sha = payload["source_reference_sha256"]
    if not isinstance(source_sha, str) or not _SHA256.fullmatch(source_sha):
        raise RevenueFeedbackError("source_reference_sha256 must be a lowercase SHA-256")
    if payload["currency"] != "USD":
        raise RevenueFeedbackError("the current economics contract requires normalized USD")
    if payload["measurement_basis"] not in _MEASUREMENT_BASES:
        raise RevenueFeedbackError("measurement_basis is not admitted")
    if type(minimum_closed_conversions) is not int or minimum_closed_conversions < 1:
        raise RevenueFeedbackError("minimum_closed_conversions must be positive")

    metrics = effect_observation.get("metrics")
    baseline_metrics = effect_observation.get("baseline_metrics")
    if not isinstance(metrics, Mapping):
        raise RevenueFeedbackError("effect observation lacks aggregate metrics")
    candidate = _economics(payload["candidate"], "candidate")
    baseline = (
        _economics(payload["baseline"], "baseline")
        if payload["baseline"] is not None
        else None
    )
    for label, row, bound in (
        ("candidate", candidate, metrics),
        ("baseline", baseline, baseline_metrics),
    ):
        if row is None and bound is None:
            continue
        if row is None or not isinstance(bound, Mapping):
            raise RevenueFeedbackError(f"{label} economics and effect metrics disagree")
        if row["conversions"] != bound.get("conversions"):
            raise RevenueFeedbackError(f"{label} conversions do not match effect evidence")
        if abs(float(row["gross_revenue_usd"]) - float(bound.get("revenue_usd", -1))) > 1e-6:
            raise RevenueFeedbackError(f"{label} gross revenue does not match effect evidence")
        if abs(float(row["media_spend_usd"]) - float(bound.get("spend_usd", -1))) > 1e-6:
            raise RevenueFeedbackError(f"{label} media spend does not match effect evidence")

    eligible_reach = metrics.get("eligible_reach")
    if type(eligible_reach) is not int or eligible_reach < 1:
        raise RevenueFeedbackError("candidate eligible reach is invalid")
    candidate_derived = _derived(candidate, eligible_reach=eligible_reach)
    baseline_derived = None
    if baseline is not None and isinstance(baseline_metrics, Mapping):
        baseline_reach = baseline_metrics.get("eligible_reach")
        if type(baseline_reach) is not int or baseline_reach < 1:
            raise RevenueFeedbackError("baseline eligible reach is invalid")
        baseline_derived = _derived(baseline, eligible_reach=baseline_reach)

    zero_budget_breach = zero_budget and float(candidate["media_spend_usd"]) > 0
    refund_worsened = bool(
        baseline_derived is not None
        and candidate_derived["refund_chargeback_rate_on_gross"] is not None
        and baseline_derived["refund_chargeback_rate_on_gross"] is not None
        and candidate_derived["refund_chargeback_rate_on_gross"]
        > baseline_derived["refund_chargeback_rate_on_gross"]
    )
    comparison_ready = bool(
        baseline_derived is not None
        and int(candidate["conversions"]) >= minimum_closed_conversions
        and int(baseline["conversions"]) >= minimum_closed_conversions
    )
    contribution_improved = bool(
        comparison_ready
        and baseline_derived is not None
        and candidate_derived["contribution_per_eligible_reach_usd"]
        > baseline_derived["contribution_per_eligible_reach_usd"]
        and candidate_derived["net_revenue_per_eligible_reach_usd"]
        > baseline_derived["net_revenue_per_eligible_reach_usd"]
    )
    feedback_ready = bool(
        comparison_ready
        and not zero_budget_breach
        and candidate_derived["positive_contribution_observed"]
        and contribution_improved
        and not refund_worsened
    )
    if zero_budget_breach:
        decision = "stop_and_review_zero_budget_breach"
    elif candidate_derived["contribution_profit_usd"] <= 0:
        decision = "stop_and_review_negative_contribution"
    elif int(candidate["conversions"]) < minimum_closed_conversions:
        decision = "collect_more_closed_conversion_data"
    elif baseline_derived is None or not comparison_ready:
        decision = "establish_comparable_unit_economics_baseline"
    elif refund_worsened:
        decision = "stop_and_review_refund_or_chargeback_regression"
    elif feedback_ready:
        decision = "continue_candidate_for_human_revenue_review"
    else:
        decision = "revise_one_variable_then_retest_unit_economics"

    input_sha = hashlib.sha256(canonical_json(dict(payload)).encode("utf-8")).hexdigest()
    core: dict[str, object] = {
        "schema": "ProofLaunchRevenueEconomicsObservationV1",
        "economics_id": economics_id,
        "input_sha256": input_sha,
        "effect_observation_id": effect_observation["observation_id"],
        "effect_observation_sha256": observation_sha,
        "experiment_id": effect_observation["experiment_id"],
        "strategy_plan_sha256": effect_observation["strategy_plan_sha256"],
        "source_reference_sha256": source_sha,
        "currency": "USD",
        "measurement_basis": payload["measurement_basis"],
        "candidate": candidate,
        "candidate_derived": candidate_derived,
        "baseline": baseline,
        "baseline_derived": baseline_derived,
        "minimum_closed_conversions": minimum_closed_conversions,
        "comparison_ready": comparison_ready,
        "zero_budget_contract_breach": zero_budget_breach,
        "refund_or_chargeback_regression": refund_worsened,
        "contribution_improved_vs_baseline": contribution_improved,
        "revenue_positive_feedback_ready": feedback_ready,
        "next_cycle_decision": decision,
        "pipeline_counted_as_revenue": False,
        "annualized_projection_allowed": False,
        "causal_revenue_claim_allowed": False,
        "automatic_budget_activation_executed": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_external_publish_executed": False,
        "human_revenue_review_required": True,
        "truth_boundary": (
            "This receipt reports source-bound aggregate unit economics for one short "
            "observation window. Positive contribution or a better comparison does not "
            "establish causal revenue, annual breakout performance, universal 4A quality "
            "or permission to increase budget. Qualified pipeline is excluded from revenue."
        ),
    }
    core["economics_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core
