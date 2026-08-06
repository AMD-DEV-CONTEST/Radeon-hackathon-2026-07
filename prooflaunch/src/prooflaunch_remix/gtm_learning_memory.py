from __future__ import annotations

import hashlib
import re
from typing import Mapping, Sequence

from .ledger import canonical_json


class LearningMemoryError(ValueError):
    pass


_APPLICABILITY_FIELDS = {
    "industry",
    "business_model",
    "lifecycle",
    "budget",
    "industry_risk",
    "market",
}
_BUSINESS_MODELS = {"b2b", "b2c"}
_LIFECYCLES = ("pre_pmf", "launch", "growth", "mature")
_BUDGETS = {"zero", "small", "scaled"}
_INDUSTRY_RISKS = {"standard", "high_regulation"}


def _bounded_context_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise LearningMemoryError(f"{field_name} must be a string")
    normalized = re.sub(r"\s+", " ", value.strip()).casefold()
    if not normalized or len(normalized) > 200:
        raise LearningMemoryError(f"{field_name} must be a bounded non-empty value")
    return normalized


def _normalize_applicability_context(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _APPLICABILITY_FIELDS:
        raise LearningMemoryError(
            "learning applicability context must contain exactly the governed dimensions"
        )
    normalized = {
        field: _bounded_context_text(value[field], field_name=field)
        for field in sorted(_APPLICABILITY_FIELDS)
    }
    if normalized["business_model"] not in _BUSINESS_MODELS:
        raise LearningMemoryError("business_model is not admitted")
    if normalized["lifecycle"] not in _LIFECYCLES:
        raise LearningMemoryError("lifecycle is not admitted")
    if normalized["budget"] not in _BUDGETS:
        raise LearningMemoryError("budget is not admitted")
    if normalized["industry_risk"] not in _INDUSTRY_RISKS:
        raise LearningMemoryError("industry_risk is not admitted")
    return normalized


def promoted_memory_payload(
    observation: Mapping[str, object],
    *,
    revenue_economics: Mapping[str, object] | None = None,
    applicability_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    required = {
        "observation_id",
        "observation_sha256",
        "experiment_id",
        "strategy_plan_sha256",
        "channel",
        "derived_rates",
        "baseline_derived_rates",
        "evidence_class",
        "next_cycle_decision",
        "observed_sample_gate_passed",
        "baseline_sample_gate_passed",
        "comparison_ready",
        "zero_budget_contract_breach",
    }
    if not isinstance(observation, Mapping) or not required.issubset(observation):
        raise LearningMemoryError("effect observation is incomplete")
    if observation["zero_budget_contract_breach"] is True:
        raise LearningMemoryError(
            "a zero-budget contract breach cannot be promoted as strategy learning"
        )
    if observation["comparison_ready"] is not True:
        raise LearningMemoryError(
            "learning promotion requires candidate and baseline sample gates"
        )
    if not isinstance(observation["derived_rates"], Mapping) or not isinstance(
        observation["baseline_derived_rates"], Mapping
    ):
        raise LearningMemoryError("learning promotion requires aggregate rate evidence")
    metrics = observation.get("metrics")
    revenue_evidence_required = bool(
        isinstance(metrics, Mapping)
        and (
            int(metrics.get("conversions", 0)) > 0
            or float(metrics.get("revenue_usd", 0.0)) > 0
        )
    )
    if revenue_evidence_required and revenue_economics is None:
        raise LearningMemoryError(
            "closed conversions or revenue require bound unit-economics evidence"
        )

    economics_summary: dict[str, object] | None = None
    if revenue_economics is not None:
        required_economics = {
            "economics_sha256",
            "effect_observation_id",
            "effect_observation_sha256",
            "candidate_derived",
            "next_cycle_decision",
            "revenue_positive_feedback_ready",
            "zero_budget_contract_breach",
            "pipeline_counted_as_revenue",
            "causal_revenue_claim_allowed",
            "automatic_budget_activation_executed",
        }
        if not required_economics.issubset(revenue_economics):
            raise LearningMemoryError("revenue economics evidence is incomplete")
        if (
            revenue_economics["effect_observation_id"]
            != observation["observation_id"]
            or revenue_economics["effect_observation_sha256"]
            != observation["observation_sha256"]
        ):
            raise LearningMemoryError("revenue economics is bound to another observation")
        if revenue_economics["zero_budget_contract_breach"] is True:
            raise LearningMemoryError(
                "revenue economics with a zero-budget breach cannot be promoted"
            )
        if revenue_economics["pipeline_counted_as_revenue"] is not False:
            raise LearningMemoryError("qualified pipeline cannot be promoted as revenue")
        if revenue_economics["causal_revenue_claim_allowed"] is not False:
            raise LearningMemoryError("descriptive economics cannot claim causal revenue")
        if revenue_economics["automatic_budget_activation_executed"] is not False:
            raise LearningMemoryError("revenue evidence cannot activate budget")
        candidate_derived = revenue_economics["candidate_derived"]
        if not isinstance(candidate_derived, Mapping):
            raise LearningMemoryError("candidate unit-economics summary is invalid")
        economics_summary = {
            "economics_sha256": revenue_economics["economics_sha256"],
            "next_cycle_decision": revenue_economics["next_cycle_decision"],
            "revenue_positive_feedback_ready": revenue_economics[
                "revenue_positive_feedback_ready"
            ],
            "contribution_profit_usd": candidate_derived.get(
                "contribution_profit_usd"
            ),
            "contribution_margin_rate": candidate_derived.get(
                "contribution_margin_rate"
            ),
            "contribution_per_eligible_reach_usd": candidate_derived.get(
                "contribution_per_eligible_reach_usd"
            ),
            "pipeline_counted_as_revenue": False,
            "causal_revenue_claim_allowed": False,
            "automatic_budget_activation_executed": False,
        }

    payload = {
        "schema": "ProofLaunchPromotedLearningMemoryV1",
        "source_observation_id": observation["observation_id"],
        "source_observation_sha256": observation["observation_sha256"],
        "experiment_id": observation["experiment_id"],
        "strategy_plan_sha256": observation["strategy_plan_sha256"],
        "channel": observation["channel"],
        "derived_rates": dict(observation["derived_rates"]),
        "baseline_derived_rates": dict(observation["baseline_derived_rates"]),
        "evidence_class": observation["evidence_class"],
        "next_cycle_decision": observation["next_cycle_decision"],
        "observed_sample_gate_passed": True,
        "baseline_sample_gate_passed": True,
        "comparison_ready": True,
        "human_promotion_required": True,
        "automatic_strategy_mutation_executed": False,
        "automatic_external_publish_executed": False,
        "truth_boundary": (
            "This memory preserves one human-promoted aggregate experiment learning. "
            "It is a reviewable next-cycle input, not a causal result, audience truth, "
            "content corpus or permission to publish."
        ),
    }
    if economics_summary is not None:
        payload["revenue_economics"] = economics_summary
    if applicability_context is not None:
        payload["applicability_context"] = _normalize_applicability_context(
            applicability_context
        )
    return payload


def compile_project_learning_context(
    memories: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for memory in memories:
        required = {
            "memory_id",
            "memory_sha256",
            "source_run_id",
            "observation_id",
            "approved_at",
            "payload",
        }
        if not isinstance(memory, Mapping) or not required.issubset(memory):
            raise LearningMemoryError("project learning memory record is incomplete")
        memory_id = str(memory["memory_id"])
        if memory_id in seen:
            raise LearningMemoryError("project learning context contains a duplicate memory")
        seen.add(memory_id)
        payload = memory["payload"]
        if not isinstance(payload, Mapping) or payload.get("schema") != (
            "ProofLaunchPromotedLearningMemoryV1"
        ):
            raise LearningMemoryError("project learning memory payload is not admitted")
        item = {
                "memory_id": memory_id,
                "memory_sha256": memory["memory_sha256"],
                "source_run_id": memory["source_run_id"],
                "observation_id": memory["observation_id"],
                "approved_at": memory["approved_at"],
                "experiment_id": payload["experiment_id"],
                "channel": payload["channel"],
                "evidence_class": payload["evidence_class"],
                "next_cycle_decision": payload["next_cycle_decision"],
                "derived_rates": dict(payload["derived_rates"]),
                "baseline_derived_rates": dict(payload["baseline_derived_rates"]),
                "automatic_strategy_mutation_executed": False,
            }
        revenue_economics = payload.get("revenue_economics")
        if revenue_economics is not None:
            if not isinstance(revenue_economics, Mapping):
                raise LearningMemoryError(
                    "project learning memory revenue economics is invalid"
                )
            item["revenue_economics"] = dict(revenue_economics)
        applicability_context = payload.get("applicability_context")
        if applicability_context is not None:
            item["applicability_context"] = _normalize_applicability_context(
                applicability_context
            )
        normalized.append(item)
    normalized.sort(key=lambda item: (str(item["approved_at"]), str(item["memory_id"])))
    core: dict[str, object] = {
        "schema": "ProofLaunchProjectLearningContextV1",
        "memory_count": len(normalized),
        "memories": normalized,
        "latest_next_cycle_decision": (
            normalized[-1]["next_cycle_decision"] if normalized else None
        ),
        "latest_source_observation_id": (
            normalized[-1]["observation_id"] if normalized else None
        ),
        "human_promoted_only": True,
        "automatic_strategy_mutation_executed": False,
        "human_review_required_before_application": True,
        "truth_boundary": (
            "This immutable snapshot contains approved aggregate project learnings "
            "available when the run was created. It excludes raw creative, audience "
            "identifiers and later memories, and does not automatically change strategy."
        ),
    }
    core["context_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core


def validate_project_learning_context(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise LearningMemoryError("project learning context must be an object")
    expected_keys = {
        "schema",
        "memory_count",
        "memories",
        "latest_next_cycle_decision",
        "latest_source_observation_id",
        "human_promoted_only",
        "automatic_strategy_mutation_executed",
        "human_review_required_before_application",
        "truth_boundary",
        "context_sha256",
    }
    if set(value) != expected_keys or value.get("schema") != (
        "ProofLaunchProjectLearningContextV1"
    ):
        raise LearningMemoryError("project learning context schema is invalid")
    memories = value.get("memories")
    count = value.get("memory_count")
    if not isinstance(memories, list) or type(count) is not int or count != len(memories):
        raise LearningMemoryError("project learning context count is invalid")
    if value.get("human_promoted_only") is not True:
        raise LearningMemoryError("project learning context lost its human promotion gate")
    if value.get("automatic_strategy_mutation_executed") is not False:
        raise LearningMemoryError("project learning context claims automatic mutation")
    for item in memories:
        if not isinstance(item, Mapping) or not {
            "memory_id",
            "memory_sha256",
            "source_run_id",
            "observation_id",
            "approved_at",
            "experiment_id",
            "channel",
            "evidence_class",
            "next_cycle_decision",
            "derived_rates",
            "baseline_derived_rates",
            "automatic_strategy_mutation_executed",
        }.issubset(item):
            raise LearningMemoryError("project learning context contains an invalid memory")
        if item.get("automatic_strategy_mutation_executed") is not False:
            raise LearningMemoryError("promoted memory claims automatic mutation")
        applicability_context = item.get("applicability_context")
        if applicability_context is not None:
            _normalize_applicability_context(applicability_context)
    core = dict(value)
    claimed = core.pop("context_sha256")
    observed = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    if claimed != observed:
        raise LearningMemoryError("project learning context integrity failed")
    return dict(value)


def compile_strategy_memory_decision(
    learning_context: Mapping[str, object],
    *,
    operating_context: Mapping[str, object],
    selected_channels: Sequence[str],
) -> dict[str, object]:
    """Rank human-promoted learning without silently mutating strategy.

    A memory is only recommendable when its source operating context is
    compatible with the new run. Paid learnings cannot flow into a zero-budget
    run, and standard-risk learnings cannot flow into a high-regulation run.
    Conflicting eligible directives on the same channel fail closed for named
    human arbitration.
    """

    context = validate_project_learning_context(learning_context)
    target = _normalize_applicability_context(operating_context)
    channels: list[str] = []
    for raw in selected_channels:
        channel = _bounded_context_text(raw, field_name="selected_channel")
        if channel not in channels:
            channels.append(channel)
    if len(channels) > 8:
        raise LearningMemoryError("selected channel set is outside its bound")

    lifecycle_index = {value: index for index, value in enumerate(_LIFECYCLES)}
    candidates: list[dict[str, object]] = []
    for memory in context["memories"]:
        source_raw = memory.get("applicability_context")
        hard_blockers: list[str] = []
        matched: list[str] = []
        transfer: list[str] = []
        mismatched: list[str] = []
        score = 0
        if source_raw is None:
            hard_blockers.append("legacy_memory_missing_applicability_context")
            source = None
        else:
            source = _normalize_applicability_context(source_raw)
            if source["business_model"] != target["business_model"]:
                hard_blockers.append("business_model_mismatch")
            else:
                matched.append("business_model")
                score += 3

            if target["budget"] == "zero" and source["budget"] != "zero":
                hard_blockers.append("paid_or_mixed_learning_cannot_enter_zero_budget")
            elif source["budget"] == target["budget"]:
                matched.append("budget")
                score += 2
            elif source["budget"] == "zero":
                transfer.append("zero_budget_learning_to_resourced_run")
                score += 1
            else:
                mismatched.append("budget")

            if (
                target["industry_risk"] == "high_regulation"
                and source["industry_risk"] != "high_regulation"
            ):
                hard_blockers.append(
                    "standard_risk_learning_cannot_enter_high_regulation"
                )
            elif source["industry_risk"] == target["industry_risk"]:
                matched.append("industry_risk")
                score += 2
            else:
                mismatched.append("industry_risk")

            if source["industry"] == target["industry"]:
                matched.append("industry")
                score += 3
            else:
                mismatched.append("industry")

            lifecycle_distance = abs(
                lifecycle_index[source["lifecycle"]]
                - lifecycle_index[target["lifecycle"]]
            )
            if lifecycle_distance == 0:
                matched.append("lifecycle")
                score += 2
            elif lifecycle_distance == 1:
                transfer.append("adjacent_lifecycle")
                score += 1
            else:
                mismatched.append("lifecycle")

            if source["market"] == target["market"]:
                matched.append("market")
                score += 1
            else:
                mismatched.append("market")

        channel = _bounded_context_text(memory["channel"], field_name="memory.channel")
        if channel in channels:
            matched.append("channel")
            score += 2
        elif channels:
            mismatched.append("channel")
        eligible = not hard_blockers and score >= 8
        candidates.append(
            {
                "memory_id": memory["memory_id"],
                "memory_sha256": memory["memory_sha256"],
                "approved_at": memory["approved_at"],
                "channel": channel,
                "next_cycle_decision": memory["next_cycle_decision"],
                "evidence_class": memory["evidence_class"],
                "applicability_score": score,
                "minimum_applicability_score": 8,
                "matched_dimensions": sorted(matched),
                "bounded_transfer_rules": sorted(transfer),
                "mismatched_dimensions": sorted(mismatched),
                "hard_blockers": sorted(hard_blockers),
                "eligible_for_human_application": eligible,
                "source_context": source,
            }
        )

    candidates.sort(
        key=lambda item: (
            -int(item["applicability_score"]),
            str(item["channel"]),
            str(item["approved_at"]),
            str(item["memory_id"]),
        )
    )
    eligible = [item for item in candidates if item["eligible_for_human_application"]]
    conflicts: list[dict[str, object]] = []
    for channel in sorted({str(item["channel"]) for item in eligible}):
        channel_items = [item for item in eligible if item["channel"] == channel]
        directives = sorted({str(item["next_cycle_decision"]) for item in channel_items})
        if len(directives) > 1:
            conflicts.append(
                {
                    "channel": channel,
                    "memory_ids": sorted(str(item["memory_id"]) for item in channel_items),
                    "directives": directives,
                    "resolution_required": "named_human_arbitration",
                }
            )

    recommended: list[dict[str, object]] = []
    if eligible and not conflicts:
        for channel in sorted({str(item["channel"]) for item in eligible}):
            channel_items = [item for item in eligible if item["channel"] == channel]
            winner = max(
                channel_items,
                key=lambda item: (
                    int(item["applicability_score"]),
                    str(item["approved_at"]),
                    str(item["memory_id"]),
                ),
            )
            recommended.append(
                {
                    "memory_id": winner["memory_id"],
                    "channel": winner["channel"],
                    "next_cycle_decision": winner["next_cycle_decision"],
                    "applicability_score": winner["applicability_score"],
                }
            )

    status = (
        "blocked_conflicting_human_memories"
        if conflicts
        else "eligible_pending_human_application"
        if recommended
        else "no_applicable_human_memory"
    )
    core: dict[str, object] = {
        "schema": "ProofLaunchStrategyMemoryDecisionV1",
        "learning_context_sha256": context["context_sha256"],
        "operating_context": target,
        "selected_channels": channels,
        "candidate_count": len(candidates),
        "eligible_memory_count": len(eligible),
        "candidates": candidates,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "recommended_directives": recommended,
        "status": status,
        "human_application_required": True,
        "automatic_strategy_mutation_executed": False,
        "automatic_schedule_mutation_executed": False,
        "automatic_budget_activation_executed": False,
        "automatic_external_publish_executed": False,
        "truth_boundary": (
            "This deterministic decision ranks only human-promoted aggregate learnings "
            "against the frozen run context. A recommendation is not an applied "
            "strategy change; conflicts and consequential actions require named humans."
        ),
    }
    core["decision_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core


def validate_strategy_memory_decision(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise LearningMemoryError("strategy memory decision must be an object")
    expected = {
        "schema",
        "learning_context_sha256",
        "operating_context",
        "selected_channels",
        "candidate_count",
        "eligible_memory_count",
        "candidates",
        "conflict_count",
        "conflicts",
        "recommended_directives",
        "status",
        "human_application_required",
        "automatic_strategy_mutation_executed",
        "automatic_schedule_mutation_executed",
        "automatic_budget_activation_executed",
        "automatic_external_publish_executed",
        "truth_boundary",
        "decision_sha256",
    }
    if set(value) != expected or value.get("schema") != (
        "ProofLaunchStrategyMemoryDecisionV1"
    ):
        raise LearningMemoryError("strategy memory decision schema is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value["learning_context_sha256"])):
        raise LearningMemoryError("strategy memory decision context digest is invalid")
    _normalize_applicability_context(value["operating_context"])
    if not isinstance(value["selected_channels"], list) or len(
        value["selected_channels"]
    ) > 8:
        raise LearningMemoryError("strategy memory selected channels are invalid")
    for channel in value["selected_channels"]:
        _bounded_context_text(channel, field_name="selected_channel")
    candidates = value["candidates"]
    conflicts = value["conflicts"]
    recommended = value["recommended_directives"]
    if not all(isinstance(rows, list) for rows in (candidates, conflicts, recommended)):
        raise LearningMemoryError("strategy memory decision collections are invalid")
    if type(value["candidate_count"]) is not int or value["candidate_count"] != len(
        candidates
    ):
        raise LearningMemoryError("strategy memory candidate count is invalid")
    eligible_ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, Mapping) or not {
            "memory_id",
            "applicability_score",
            "eligible_for_human_application",
            "hard_blockers",
            "channel",
            "next_cycle_decision",
        }.issubset(item):
            raise LearningMemoryError("strategy memory candidate is invalid")
        if type(item["applicability_score"]) is not int:
            raise LearningMemoryError("strategy memory applicability score is invalid")
        if type(item["eligible_for_human_application"]) is not bool:
            raise LearningMemoryError("strategy memory eligibility flag is invalid")
        if not isinstance(item["hard_blockers"], list):
            raise LearningMemoryError("strategy memory blockers are invalid")
        if item["eligible_for_human_application"]:
            eligible_ids.add(str(item["memory_id"]))
    if type(value["eligible_memory_count"]) is not int or value[
        "eligible_memory_count"
    ] != len(eligible_ids):
        raise LearningMemoryError("strategy memory eligible count is invalid")
    if type(value["conflict_count"]) is not int or value["conflict_count"] != len(
        conflicts
    ):
        raise LearningMemoryError("strategy memory conflict count is invalid")
    if any(
        not isinstance(item, Mapping)
        or str(item.get("memory_id")) not in eligible_ids
        for item in recommended
    ):
        raise LearningMemoryError("strategy memory recommendation is not eligible")
    status = value["status"]
    if conflicts:
        if status != "blocked_conflicting_human_memories" or recommended:
            raise LearningMemoryError("conflicting strategy memory did not fail closed")
    elif recommended:
        if status != "eligible_pending_human_application":
            raise LearningMemoryError("eligible strategy memory status is invalid")
    elif status != "no_applicable_human_memory":
        raise LearningMemoryError("empty strategy memory status is invalid")
    if value["human_application_required"] is not True or any(
        value[field] is not False
        for field in (
            "automatic_strategy_mutation_executed",
            "automatic_schedule_mutation_executed",
            "automatic_budget_activation_executed",
            "automatic_external_publish_executed",
        )
    ):
        raise LearningMemoryError("strategy memory authority boundary is invalid")
    core = dict(value)
    claimed = core.pop("decision_sha256")
    observed = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    if claimed != observed:
        raise LearningMemoryError("strategy memory decision integrity failed")
    return dict(value)


def strategy_memory_resolution_payload(
    decision: Mapping[str, object],
    *,
    source_run_id: str,
    channel: str,
    winner_memory_id: str,
    resolved_by: str,
    reason: str,
    resolved_at: str,
) -> dict[str, object]:
    """Create one immutable, named-human resolution of a frozen conflict.

    A resolution never edits the source run.  It is bound to the exact base
    decision digest and can only be considered by a later run that freezes the
    resulting project resolution context.
    """

    governed = validate_strategy_memory_decision(decision)
    normalized_channel = _bounded_context_text(channel, field_name="channel")
    if (
        not isinstance(winner_memory_id, str)
        or not winner_memory_id.strip()
        or len(winner_memory_id) > 200
    ):
        raise LearningMemoryError("winner_memory_id must be a bounded non-empty value")
    winner = winner_memory_id.strip()
    if (
        not isinstance(resolved_by, str)
        or not resolved_by.strip()
        or len(resolved_by) > 200
    ):
        raise LearningMemoryError("resolved_by must be a bounded non-empty value")
    actor = resolved_by.strip()
    rationale = re.sub(r"\s+", " ", reason.strip()) if isinstance(reason, str) else ""
    if not rationale or len(rationale) > 4096:
        raise LearningMemoryError("resolution reason must be a bounded non-empty value")
    if not isinstance(source_run_id, str) or not source_run_id.strip():
        raise LearningMemoryError("resolution source_run_id is required")
    if not isinstance(resolved_at, str) or not resolved_at.strip():
        raise LearningMemoryError("resolution timestamp is required")

    conflict = next(
        (
            item
            for item in governed["conflicts"]
            if isinstance(item, Mapping) and item.get("channel") == normalized_channel
        ),
        None,
    )
    if conflict is None:
        raise LearningMemoryError("resolution channel is not a frozen conflict")
    conflict_ids = sorted(str(item) for item in conflict["memory_ids"])
    if winner not in conflict_ids:
        raise LearningMemoryError("resolution winner is outside the frozen conflict")

    core: dict[str, object] = {
        "schema": "ProofLaunchStrategyMemoryResolutionV1",
        "source_run_id": source_run_id,
        "base_decision_sha256": governed["decision_sha256"],
        "learning_context_sha256": governed["learning_context_sha256"],
        "channel": normalized_channel,
        "conflict_memory_ids": conflict_ids,
        "winner_memory_id": winner,
        "resolved_by": actor,
        "reason": rationale,
        "resolved_at": resolved_at,
        "source_run_mutated": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_schedule_mutation_executed": False,
        "automatic_budget_activation_executed": False,
        "automatic_external_publish_executed": False,
        "truth_boundary": (
            "This named-human record resolves one frozen memory conflict for "
            "consideration by later runs. It does not mutate the source run, apply "
            "strategy, schedule content, activate budget, or publish externally."
        ),
    }
    core["resolution_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core


def validate_strategy_memory_resolution(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise LearningMemoryError("strategy memory resolution must be an object")
    expected = {
        "schema",
        "source_run_id",
        "base_decision_sha256",
        "learning_context_sha256",
        "channel",
        "conflict_memory_ids",
        "winner_memory_id",
        "resolved_by",
        "reason",
        "resolved_at",
        "source_run_mutated",
        "automatic_strategy_mutation_executed",
        "automatic_schedule_mutation_executed",
        "automatic_budget_activation_executed",
        "automatic_external_publish_executed",
        "truth_boundary",
        "resolution_sha256",
    }
    if set(value) != expected or value.get("schema") != (
        "ProofLaunchStrategyMemoryResolutionV1"
    ):
        raise LearningMemoryError("strategy memory resolution schema is invalid")
    for field in (
        "base_decision_sha256",
        "learning_context_sha256",
        "resolution_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value[field])):
            raise LearningMemoryError(f"strategy memory resolution {field} is invalid")
    if (
        not isinstance(value["source_run_id"], str)
        or not value["source_run_id"].strip()
        or len(value["source_run_id"]) > 200
    ):
        raise LearningMemoryError("strategy memory resolution source run is invalid")
    _bounded_context_text(value["channel"], field_name="channel")
    winner = value["winner_memory_id"]
    if not isinstance(winner, str) or not winner.strip() or len(winner) > 200:
        raise LearningMemoryError("strategy memory resolution winner is invalid")
    if (
        not isinstance(value["resolved_by"], str)
        or not value["resolved_by"].strip()
        or len(value["resolved_by"]) > 200
    ):
        raise LearningMemoryError("strategy memory resolution actor is invalid")
    if (
        not isinstance(value["reason"], str)
        or not value["reason"].strip()
        or len(value["reason"]) > 4096
        or not isinstance(value["resolved_at"], str)
        or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z",
            value["resolved_at"],
        )
    ):
        raise LearningMemoryError("strategy memory resolution rationale or time is invalid")
    conflict_ids = value["conflict_memory_ids"]
    if (
        not isinstance(conflict_ids, list)
        or not all(isinstance(item, str) and item.strip() for item in conflict_ids)
        or len(conflict_ids) < 2
        or conflict_ids != sorted(set(conflict_ids))
        or winner not in conflict_ids
    ):
        raise LearningMemoryError("strategy memory resolution conflict set is invalid")
    if any(
        value[field] is not False
        for field in (
            "source_run_mutated",
            "automatic_strategy_mutation_executed",
            "automatic_schedule_mutation_executed",
            "automatic_budget_activation_executed",
            "automatic_external_publish_executed",
        )
    ):
        raise LearningMemoryError("strategy memory resolution authority boundary is invalid")
    core = dict(value)
    claimed = core.pop("resolution_sha256")
    observed = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    if claimed != observed:
        raise LearningMemoryError("strategy memory resolution integrity failed")
    return dict(value)


def compile_strategy_memory_resolution_context(
    resolutions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    normalized = [validate_strategy_memory_resolution(item) for item in resolutions]
    normalized.sort(
        key=lambda item: (
            str(item["resolved_at"]),
            str(item["base_decision_sha256"]),
            str(item["channel"]),
            str(item["resolution_sha256"]),
        )
    )
    identities: set[tuple[str, str]] = set()
    for item in normalized:
        identity = (str(item["base_decision_sha256"]), str(item["channel"]))
        if identity in identities:
            raise LearningMemoryError(
                "resolution context contains multiple winners for one frozen conflict"
            )
        identities.add(identity)
    core: dict[str, object] = {
        "schema": "ProofLaunchStrategyMemoryResolutionContextV1",
        "resolution_count": len(normalized),
        "resolutions": normalized,
        "named_human_only": True,
        "source_runs_immutable": True,
        "automatic_strategy_mutation_executed": False,
        "truth_boundary": (
            "This immutable snapshot contains named-human conflict resolutions "
            "available when a later run was created. It grants no execution authority."
        ),
    }
    core["context_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core


def validate_strategy_memory_resolution_context(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise LearningMemoryError("strategy memory resolution context must be an object")
    expected = {
        "schema",
        "resolution_count",
        "resolutions",
        "named_human_only",
        "source_runs_immutable",
        "automatic_strategy_mutation_executed",
        "truth_boundary",
        "context_sha256",
    }
    if set(value) != expected or value.get("schema") != (
        "ProofLaunchStrategyMemoryResolutionContextV1"
    ):
        raise LearningMemoryError("strategy memory resolution context schema is invalid")
    rows = value["resolutions"]
    if (
        not isinstance(rows, list)
        or type(value["resolution_count"]) is not int
        or value["resolution_count"] != len(rows)
    ):
        raise LearningMemoryError("strategy memory resolution context count is invalid")
    if (
        value["named_human_only"] is not True
        or value["source_runs_immutable"] is not True
        or value["automatic_strategy_mutation_executed"] is not False
    ):
        raise LearningMemoryError("strategy memory resolution context boundary is invalid")
    compile_strategy_memory_resolution_context(
        [validate_strategy_memory_resolution(item) for item in rows]
    )
    core = dict(value)
    claimed = core.pop("context_sha256")
    observed = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    if claimed != observed:
        raise LearningMemoryError("strategy memory resolution context integrity failed")
    return dict(value)


def compile_strategy_memory_application(
    decision: Mapping[str, object],
    resolution_context: Mapping[str, object],
) -> dict[str, object]:
    """Compile the effective, still-human-gated recommendation for a new run."""

    governed = validate_strategy_memory_decision(decision)
    resolutions = validate_strategy_memory_resolution_context(resolution_context)
    matching = [
        item
        for item in resolutions["resolutions"]
        if item["base_decision_sha256"] == governed["decision_sha256"]
        and item["learning_context_sha256"] == governed["learning_context_sha256"]
    ]
    by_channel = {str(item["channel"]): item for item in matching}
    selected: list[dict[str, object]] = []
    unresolved: list[str] = []
    applied_resolution_ids: list[str] = []

    if governed["conflicts"]:
        for conflict in governed["conflicts"]:
            channel = str(conflict["channel"])
            resolution = by_channel.get(channel)
            if resolution is None or resolution["conflict_memory_ids"] != conflict["memory_ids"]:
                unresolved.append(channel)
                continue
            winner = next(
                (
                    item
                    for item in governed["candidates"]
                    if item["memory_id"] == resolution["winner_memory_id"]
                    and item["eligible_for_human_application"] is True
                ),
                None,
            )
            if winner is None:
                unresolved.append(channel)
                continue
            selected.append(
                {
                    "memory_id": winner["memory_id"],
                    "channel": winner["channel"],
                    "next_cycle_decision": winner["next_cycle_decision"],
                    "applicability_score": winner["applicability_score"],
                    "selection_basis": "named_human_conflict_resolution",
                    "resolution_sha256": resolution["resolution_sha256"],
                    "resolved_by": resolution["resolved_by"],
                }
            )
            applied_resolution_ids.append(str(resolution["resolution_sha256"]))
        if unresolved:
            selected = []
            applied_resolution_ids = []
            status = "blocked_pending_named_human_resolution"
        else:
            status = "resolved_pending_named_human_application"
    elif governed["recommended_directives"]:
        selected = [
            {
                **dict(item),
                "selection_basis": "deterministic_contextual_ranking",
                "resolution_sha256": None,
                "resolved_by": None,
            }
            for item in governed["recommended_directives"]
        ]
        status = "eligible_pending_named_human_application"
    else:
        status = "no_applicable_human_memory"

    core: dict[str, object] = {
        "schema": "ProofLaunchStrategyMemoryApplicationV1",
        "base_decision_sha256": governed["decision_sha256"],
        "resolution_context_sha256": resolutions["context_sha256"],
        "status": status,
        "conflict_count": governed["conflict_count"],
        "resolved_conflict_count": (
            governed["conflict_count"] - len(unresolved)
            if not unresolved
            else 0
        ),
        "unresolved_conflict_channels": sorted(unresolved),
        "selected_directives": selected,
        "applied_resolution_sha256": sorted(applied_resolution_ids),
        "human_application_required": True,
        "source_run_mutated": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_schedule_mutation_executed": False,
        "automatic_budget_activation_executed": False,
        "automatic_external_publish_executed": False,
        "truth_boundary": (
            "This application record selects only context-eligible aggregate memory. "
            "Even a named resolution remains a recommendation requiring explicit human "
            "application; it does not mutate strategy or execute a consequential action."
        ),
    }
    core["application_sha256"] = hashlib.sha256(
        canonical_json(core).encode("utf-8")
    ).hexdigest()
    return core


def validate_strategy_memory_application(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise LearningMemoryError("strategy memory application must be an object")
    expected = {
        "schema",
        "base_decision_sha256",
        "resolution_context_sha256",
        "status",
        "conflict_count",
        "resolved_conflict_count",
        "unresolved_conflict_channels",
        "selected_directives",
        "applied_resolution_sha256",
        "human_application_required",
        "source_run_mutated",
        "automatic_strategy_mutation_executed",
        "automatic_schedule_mutation_executed",
        "automatic_budget_activation_executed",
        "automatic_external_publish_executed",
        "truth_boundary",
        "application_sha256",
    }
    if set(value) != expected or value.get("schema") != (
        "ProofLaunchStrategyMemoryApplicationV1"
    ):
        raise LearningMemoryError("strategy memory application schema is invalid")
    for field in (
        "base_decision_sha256",
        "resolution_context_sha256",
        "application_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value[field])):
            raise LearningMemoryError(f"strategy memory application {field} is invalid")
    if not all(
        isinstance(value[field], list)
        for field in (
            "unresolved_conflict_channels",
            "selected_directives",
            "applied_resolution_sha256",
        )
    ):
        raise LearningMemoryError("strategy memory application collections are invalid")
    if type(value["conflict_count"]) is not int or type(
        value["resolved_conflict_count"]
    ) is not int:
        raise LearningMemoryError("strategy memory application counts are invalid")
    conflict_count = value["conflict_count"]
    resolved_count = value["resolved_conflict_count"]
    unresolved = value["unresolved_conflict_channels"]
    selected = value["selected_directives"]
    applied = value["applied_resolution_sha256"]
    if conflict_count < 0 or resolved_count < 0 or resolved_count > conflict_count:
        raise LearningMemoryError("strategy memory application count bounds are invalid")
    if not all(
        isinstance(item, str) and item.strip() for item in unresolved
    ) or unresolved != sorted(set(unresolved)):
        raise LearningMemoryError("strategy memory unresolved channel set is invalid")
    if not all(re.fullmatch(r"[0-9a-f]{64}", str(item)) for item in applied):
        raise LearningMemoryError("strategy memory applied resolution set is invalid")
    for item in selected:
        if not isinstance(item, Mapping) or not {
            "memory_id",
            "channel",
            "next_cycle_decision",
            "applicability_score",
            "selection_basis",
            "resolution_sha256",
            "resolved_by",
        }.issubset(item):
            raise LearningMemoryError("strategy memory selected directive is invalid")
    status = value["status"]
    if status == "blocked_pending_named_human_resolution":
        if not unresolved or not conflict_count or selected or applied or resolved_count:
            raise LearningMemoryError(
                "unresolved strategy memory application did not fail closed"
            )
    elif status == "resolved_pending_named_human_application":
        if (
            not conflict_count
            or resolved_count != conflict_count
            or unresolved
            or len(selected) != conflict_count
            or len(applied) != conflict_count
        ):
            raise LearningMemoryError("resolved strategy memory application is invalid")
    elif status == "eligible_pending_named_human_application":
        if conflict_count or resolved_count or unresolved or not selected or applied:
            raise LearningMemoryError("ranked strategy memory application is invalid")
    elif status == "no_applicable_human_memory":
        if conflict_count or resolved_count or unresolved or selected or applied:
            raise LearningMemoryError("empty strategy memory application is invalid")
    else:
        raise LearningMemoryError("strategy memory application status is invalid")
    if value["human_application_required"] is not True or any(
        value[field] is not False
        for field in (
            "source_run_mutated",
            "automatic_strategy_mutation_executed",
            "automatic_schedule_mutation_executed",
            "automatic_budget_activation_executed",
            "automatic_external_publish_executed",
        )
    ):
        raise LearningMemoryError("strategy memory application authority boundary is invalid")
    core = dict(value)
    claimed = core.pop("application_sha256")
    observed = hashlib.sha256(canonical_json(core).encode("utf-8")).hexdigest()
    if claimed != observed:
        raise LearningMemoryError("strategy memory application integrity failed")
    return dict(value)
