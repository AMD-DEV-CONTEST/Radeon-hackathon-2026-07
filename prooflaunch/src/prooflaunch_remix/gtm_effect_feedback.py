from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Mapping

from .ledger import canonical_json


class EffectFeedbackError(ValueError):
    pass


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_KINDS = frozenset(
    {
        "first_party_analytics",
        "official_platform_export",
        "authorized_manual_entry",
    }
)
_ASSIGNMENT_METHODS = frozenset({"observational", "randomized_controlled"})
_METRIC_KEYS = frozenset(
    {
        "eligible_reach",
        "qualified_actions",
        "evidence_engagements",
        "complaints",
        "conversions",
        "revenue_usd",
        "spend_usd",
    }
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "observation_id",
        "experiment_id",
        "strategy_plan_sha256",
        "source_kind",
        "source_reference_sha256",
        "channel",
        "window_start",
        "window_end",
        "assignment_method",
        "metrics",
        "baseline_metrics",
        "deduplicated",
        "bot_filter_applied",
    }
)


def _parse_time(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise EffectFeedbackError(f"{field_name} must be a bounded ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EffectFeedbackError(f"{field_name} must be valid ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EffectFeedbackError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise EffectFeedbackError(f"{field_name} is invalid")
    return value


def _metrics(value: object, *, field_name: str) -> dict[str, int | float]:
    if not isinstance(value, Mapping) or set(value) != _METRIC_KEYS:
        raise EffectFeedbackError(
            f"{field_name} must contain exactly {sorted(_METRIC_KEYS)}"
        )
    result: dict[str, int | float] = {}
    reach = value["eligible_reach"]
    if type(reach) is not int or reach < 1 or reach > 1_000_000_000:
        raise EffectFeedbackError(f"{field_name}.eligible_reach is outside its bound")
    result["eligible_reach"] = reach
    for key in (
        "qualified_actions",
        "evidence_engagements",
        "complaints",
        "conversions",
    ):
        observed = value[key]
        if type(observed) is not int or observed < 0 or observed > reach:
            raise EffectFeedbackError(f"{field_name}.{key} must be in [0, eligible_reach]")
        result[key] = observed
    for key in ("revenue_usd", "spend_usd"):
        observed = value[key]
        if type(observed) not in {int, float} or not math.isfinite(observed):
            raise EffectFeedbackError(f"{field_name}.{key} must be finite")
        if observed < 0 or observed > 1_000_000_000:
            raise EffectFeedbackError(f"{field_name}.{key} is outside its bound")
        result[key] = round(float(observed), 6)
    return result


def _rates(metrics: Mapping[str, int | float]) -> dict[str, float]:
    reach = int(metrics["eligible_reach"])
    return {
        "qualified_action_rate": round(int(metrics["qualified_actions"]) / reach, 8),
        "evidence_engagement_rate": round(
            int(metrics["evidence_engagements"]) / reach, 8
        ),
        "unsubscribe_or_complaint_rate": round(
            int(metrics["complaints"]) / reach, 8
        ),
        "conversion_rate": round(int(metrics["conversions"]) / reach, 8),
        "revenue_per_eligible_reach_usd": round(
            float(metrics["revenue_usd"]) / reach, 8
        ),
    }


def compile_effect_observation(
    payload: Mapping[str, object],
    *,
    expected_experiment_id: str,
    expected_strategy_plan_sha256: str,
    registered_minimum_samples: Mapping[str, int],
    zero_budget: bool,
    received_at: datetime | None = None,
) -> dict[str, object]:
    """Validate one aggregate result and produce a bounded next-cycle decision.

    The result contains counts and source hashes only. It never accepts audience
    identifiers, content bodies or free-form testimonials, and it never mutates
    a strategy or represents an observational comparison as causal evidence.
    """

    if not isinstance(payload, Mapping) or set(payload) != _TOP_LEVEL_KEYS:
        raise EffectFeedbackError(
            "effect observation fields are incomplete or contain unknown data"
        )
    observation_id = _identifier(payload["observation_id"], field_name="observation_id")
    experiment_id = _identifier(payload["experiment_id"], field_name="experiment_id")
    if experiment_id != expected_experiment_id:
        raise EffectFeedbackError("observation is not bound to the preregistered experiment")
    strategy_digest = payload["strategy_plan_sha256"]
    if (
        not isinstance(strategy_digest, str)
        or not _SHA256.fullmatch(strategy_digest)
        or strategy_digest != expected_strategy_plan_sha256
    ):
        raise EffectFeedbackError("observation is not bound to the approved strategy plan")
    source_kind = payload["source_kind"]
    if source_kind not in _SOURCE_KINDS:
        raise EffectFeedbackError("source_kind is not admitted")
    source_reference = payload["source_reference_sha256"]
    if not isinstance(source_reference, str) or not _SHA256.fullmatch(source_reference):
        raise EffectFeedbackError("source_reference_sha256 must be a lowercase SHA-256")
    channel = _identifier(payload["channel"], field_name="channel")
    assignment = payload["assignment_method"]
    if assignment not in _ASSIGNMENT_METHODS:
        raise EffectFeedbackError("assignment_method is not admitted")
    if payload["deduplicated"] is not True or payload["bot_filter_applied"] is not True:
        raise EffectFeedbackError("deduplication and bot filtering must be attested")

    window_start = _parse_time(payload["window_start"], field_name="window_start")
    window_end = _parse_time(payload["window_end"], field_name="window_end")
    if window_end <= window_start or window_end - window_start > timedelta(days=31):
        raise EffectFeedbackError("observation window must be positive and at most 31 days")
    received = (received_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if window_end > received + timedelta(minutes=5):
        raise EffectFeedbackError("observation window cannot end in the future")

    observed = _metrics(payload["metrics"], field_name="metrics")
    baseline_raw = payload["baseline_metrics"]
    baseline = (
        _metrics(baseline_raw, field_name="baseline_metrics")
        if baseline_raw is not None
        else None
    )
    rates = _rates(observed)
    baseline_rates = _rates(baseline) if baseline is not None else None
    registered_floor = max(
        (
            minimum
            for metric, minimum in registered_minimum_samples.items()
            if metric in {"qualified_action_rate", "evidence_engagement_rate"}
        ),
        default=1,
    )
    observed_sample_passed = int(observed["eligible_reach"]) >= registered_floor
    baseline_sample_passed = bool(
        baseline is not None and int(baseline["eligible_reach"]) >= registered_floor
    )
    comparison_ready = observed_sample_passed and baseline_sample_passed
    zero_budget_breach = zero_budget and float(observed["spend_usd"]) > 0

    if zero_budget_breach:
        decision = "stop_and_review"
        reason = "observed spend conflicts with the approved zero-budget contract"
    elif not observed_sample_passed:
        decision = "collect_more_data"
        reason = "the preregistered minimum sample has not been reached"
    elif baseline is None or not baseline_sample_passed:
        decision = "establish_comparable_baseline"
        reason = "the observation is descriptive because a sufficient baseline is absent"
    elif baseline_rates is not None and (
        rates["unsubscribe_or_complaint_rate"]
        > baseline_rates["unsubscribe_or_complaint_rate"]
    ):
        decision = "stop_and_review"
        reason = "the preregistered complaint guardrail worsened versus baseline"
    elif baseline_rates is not None and (
        rates["qualified_action_rate"] > baseline_rates["qualified_action_rate"]
        and rates["evidence_engagement_rate"]
        > baseline_rates["evidence_engagement_rate"]
    ):
        decision = "continue_candidate_for_human_review"
        reason = "both preregistered positive metrics improved without a complaint increase"
    else:
        decision = "revise_one_variable_then_retest"
        reason = "the sufficient comparison did not improve both preregistered positive metrics"

    evidence_class = (
        "randomized_comparison_pending_statistical_review"
        if assignment == "randomized_controlled" and comparison_ready
        else "observational_attribution"
    )
    input_sha256 = hashlib.sha256(
        canonical_json(dict(payload)).encode("utf-8")
    ).hexdigest()
    core: dict[str, object] = {
        "schema": "ProofLaunchEffectObservationV1",
        "observation_id": observation_id,
        "input_sha256": input_sha256,
        "experiment_id": experiment_id,
        "strategy_plan_sha256": strategy_digest,
        "source_kind": source_kind,
        "source_reference_sha256": source_reference,
        "channel": channel,
        "window_start": window_start.isoformat().replace("+00:00", "Z"),
        "window_end": window_end.isoformat().replace("+00:00", "Z"),
        "received_at": received.isoformat().replace("+00:00", "Z"),
        "assignment_method": assignment,
        "metrics": observed,
        "derived_rates": rates,
        "baseline_metrics": baseline,
        "baseline_derived_rates": baseline_rates,
        "registered_minimum_sample": registered_floor,
        "observed_sample_gate_passed": observed_sample_passed,
        "baseline_sample_gate_passed": baseline_sample_passed,
        "comparison_ready": comparison_ready,
        "zero_budget_contract_breach": zero_budget_breach,
        "evidence_class": evidence_class,
        "next_cycle_decision": decision,
        "decision_reason": reason,
        "causal_outcome_claim_allowed": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_external_publish_executed": False,
        "human_review_required": True,
        "truth_boundary": (
            "This receipt binds aggregate first-party or authorized results to one "
            "preregistered experiment. It does not prove causal lift, annual breakout "
            "performance, revenue causality, Top-1 status or 4A-level effect."
        ),
    }
    core["observation_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core
