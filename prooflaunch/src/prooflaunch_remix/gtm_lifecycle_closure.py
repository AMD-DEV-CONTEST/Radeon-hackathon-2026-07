from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Mapping

from .graph_loop_harness import production_graph_loop_harness
from .gtm_content_calendar import compile_content_calendar, verify_content_calendar
from .gtm_effect_feedback import compile_effect_observation
from .gtm_production_pack import GTMProductionPack
from .gtm_omnichannel_activation import compile_omnichannel_activation
from .gtm_revenue_feedback import compile_revenue_economics
from .gtm_strategy import BudgetTier, CampaignStrategyInput, GTMStrategy
from .ledger import canonical_json


class LifecycleClosureError(ValueError):
    """Raised when one end-to-end GTM lifecycle contract loses its binding."""


_SCENARIOS = (
    "qualified_positive_requires_human",
    "insufficient_sample",
    "complaint_regression",
    "negative_contribution",
    "zero_budget_spend_breach",
)


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _synthetic_post_selection_probe(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    pack: GTMProductionPack,
) -> dict[str, object]:
    """Exercise post-selection continuity without pretending a human selected it."""

    candidate: dict[str, object] = {
        "schema": "ProofLaunchTextCreativeCandidateV1",
        "territory_id": "synthetic_lifecycle_contract_probe",
        "strategy_id": strategy.strategy_id,
        "proof_claim_id": strategy.proof_claim_id,
        "cultural_tension": pack.big_idea.testable_tension,
        "organizing_idea": pack.big_idea.organizing_idea,
        "participation_mechanism": pack.breakout_growth_loop["steps"][1][
            "operator_action"
        ],
        "share_trigger": pack.breakout_growth_loop["share_trigger_hypothesis"],
        "proof_role": (
            "The approved proof controls the decision sequence and remains visible "
            "beside its limitation before any call to action."
        ),
        "falsifier": pack.breakout_growth_loop["steps"][1]["stop_condition"],
        "factual_claims": [strategy.proof],
        "channels": [
            {
                "channel": draft.channel.value,
                "native_format": draft.native_format,
                "hook": draft.hook,
                "body": list(draft.body),
                "cta": strategy.call_to_action,
                "disclosure": "draft_pending_human_review",
            }
            for draft in (pack.primary_copy, pack.secondary_copy)
        ],
        "winner_selected": False,
        "blind_review_completed": False,
        "external_publish_executed": False,
    }
    candidate["candidate_content_sha256"] = _digest(candidate)
    admission: dict[str, object] = {
        "schema": "ProofLaunchMultimodalProductionAdmissionV1",
        "campaign_id": request.campaign_id,
        "strategy_id": strategy.strategy_id,
        "challenger_plan_sha256": pack.text_creative_challenger_plan[
            "content_sha256"
        ],
        "proof_claim_id": strategy.proof_claim_id,
        "selected_territory_id": candidate["territory_id"],
        "selected_candidate_content_sha256": candidate[
            "candidate_content_sha256"
        ],
        "selected_candidate": candidate,
        "prompt_compilation_authorized": True,
        "gpu_execution_authorized": False,
        "spend_authorized": False,
        "external_publish_authorized": False,
        "effect_claim_eligible": False,
        "synthetic_human_selection_probe": True,
        "content_sha256": None,
    }
    admission["content_sha256"] = _digest(admission)
    multimodal: dict[str, object] = {
        "schema": "ProofLaunchMultimodalSeedCompilationV1",
        "multimodal_admission_sha256": admission["content_sha256"],
        "stages": [
            {"stage_id": stage_id, "execution_admitted": False}
            for stage_id in (
                "hero_image",
                "hero_video",
                "original_music",
                "speech",
            )
        ],
        "synthetic_contract_probe": True,
        "content_sha256": None,
    }
    multimodal["content_sha256"] = _digest(multimodal)
    activation = compile_omnichannel_activation(admission, multimodal)
    return {
        "schema": "ProofLaunchSyntheticPostSelectionProbeV1",
        "campaign_id": activation["campaign_id"],
        "strategy_id": activation["strategy_id"],
        "challenger_plan_sha256": activation["challenger_plan_sha256"],
        "activation_sha256": activation["content_sha256"],
        "lane_count": activation["lane_count"],
        "same_creative_system_across_lanes": activation[
            "same_creative_system_across_lanes"
        ],
        "same_evidence_spine_across_lanes": activation[
            "same_evidence_spine_across_lanes"
        ],
        "all_external_actions_disabled": activation[
            "external_actions_executed"
        ]
        == 0,
        "effect_claim_eligible": activation["effect_claim_eligible"],
        "synthetic_human_selection_probe": True,
        "human_selection_observed": False,
    }


def _metrics(
    *,
    eligible_reach: int,
    qualified_actions: int,
    evidence_engagements: int,
    complaints: int,
    conversions: int,
    revenue_usd: float,
    spend_usd: float,
) -> dict[str, int | float]:
    return {
        "eligible_reach": eligible_reach,
        "qualified_actions": qualified_actions,
        "evidence_engagements": evidence_engagements,
        "complaints": complaints,
        "conversions": conversions,
        "revenue_usd": revenue_usd,
        "spend_usd": spend_usd,
    }


def _economics_row(
    *,
    candidate: bool,
    spend_usd: float,
    negative_contribution: bool = False,
) -> dict[str, int | float]:
    return {
        "conversions": 5 if candidate else 3,
        "gross_revenue_usd": 250.0 if candidate else 150.0,
        "discounts_usd": 5.0 if candidate else 3.0,
        "refunds_usd": 5.0,
        "chargebacks_usd": 0.0,
        "variable_cogs_usd": 35.0 if candidate else 25.0,
        "fulfillment_cost_usd": 15.0 if candidate else 12.0,
        "platform_fees_usd": 7.0 if candidate else 5.0,
        "media_spend_usd": spend_usd,
        "model_cost_usd": 2.0 if candidate else 1.0,
        "operator_cost_usd": (
            500.0 if candidate and negative_contribution else (20.0 if candidate else 18.0)
        ),
        "qualified_pipeline_usd": 50000.0 if candidate else 20000.0,
    }


def _effect(
    request: CampaignStrategyInput,
    pack: GTMProductionPack,
    *,
    scenario: str,
    received_at: datetime,
) -> dict[str, object]:
    zero_budget = request.budget is BudgetTier.ZERO
    candidate_spend = 0.0 if zero_budget else 10.0
    baseline_spend = 0.0 if zero_budget else 5.0
    candidate = _metrics(
        eligible_reach=100,
        qualified_actions=12,
        evidence_engagements=18,
        complaints=0,
        conversions=5,
        revenue_usd=250.0,
        spend_usd=candidate_spend,
    )
    baseline = _metrics(
        eligible_reach=80,
        qualified_actions=8,
        evidence_engagements=12,
        complaints=0,
        conversions=3,
        revenue_usd=150.0,
        spend_usd=baseline_spend,
    )
    if scenario == "insufficient_sample":
        candidate.update(
            eligible_reach=20,
            qualified_actions=2,
            evidence_engagements=3,
            complaints=0,
            conversions=1,
            revenue_usd=50.0,
            spend_usd=0.0 if zero_budget else 2.0,
        )
    elif scenario == "complaint_regression":
        candidate["complaints"] = 5
    elif scenario == "zero_budget_spend_breach":
        if not zero_budget:
            raise LifecycleClosureError("zero-budget breach probe requires a zero budget")
        candidate["spend_usd"] = 10.0

    suffix = _digest({"campaign": request.campaign_id, "scenario": scenario})[:16]
    return compile_effect_observation(
        {
            "observation_id": f"obs-{suffix}",
            "experiment_id": pack.analytics.experiment_id,
            "strategy_plan_sha256": pack.source_strategy_sha256,
            "source_kind": "authorized_manual_entry",
            "source_reference_sha256": _digest(
                {"fixture": "synthetic-lifecycle-eval", "suffix": suffix}
            ),
            "channel": pack.primary_copy.channel.value,
            "window_start": "2026-07-01T00:00:00Z",
            "window_end": "2026-07-08T00:00:00Z",
            "assignment_method": "observational",
            "metrics": candidate,
            "baseline_metrics": baseline,
            "deduplicated": True,
            "bot_filter_applied": True,
        },
        expected_experiment_id=pack.analytics.experiment_id,
        expected_strategy_plan_sha256=pack.source_strategy_sha256,
        registered_minimum_samples={"qualified_action_rate": 50},
        zero_budget=zero_budget,
        received_at=received_at,
    )


def _revenue(
    request: CampaignStrategyInput,
    effect: Mapping[str, object],
    *,
    scenario: str,
) -> dict[str, object]:
    zero_budget = request.budget is BudgetTier.ZERO
    candidate_spend = float(effect["metrics"]["spend_usd"])  # type: ignore[index]
    baseline_spend = float(effect["baseline_metrics"]["spend_usd"])  # type: ignore[index]
    suffix = _digest({"effect": effect["observation_sha256"], "scenario": scenario})[:16]
    return compile_revenue_economics(
        {
            "economics_id": f"econ-{suffix}",
            "effect_observation_id": effect["observation_id"],
            "effect_observation_sha256": effect["observation_sha256"],
            "source_reference_sha256": _digest(
                {"fixture": "synthetic-lifecycle-economics", "suffix": suffix}
            ),
            "currency": "USD",
            "measurement_basis": "cash_collected",
            "candidate": _economics_row(
                candidate=True,
                spend_usd=candidate_spend,
                negative_contribution=scenario == "negative_contribution",
            ),
            "baseline": _economics_row(
                candidate=False,
                spend_usd=baseline_spend,
            ),
        },
        effect_observation=effect,
        zero_budget=zero_budget,
    )


def compile_lifecycle_closure_case(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    pack: GTMProductionPack,
    *,
    compiled_at: str,
    schedule_timezone: str,
    received_at: datetime | None = None,
) -> dict[str, object]:
    """Compile a synthetic, side-effect-free full-lifecycle regression case.

    The case proves contract integration. Synthetic observations are deliberately
    excluded from production, causal, annual-breakout and 4A evidence.
    """

    if not pack.verify_digest():
        raise LifecycleClosureError("production pack digest is invalid")
    if (
        pack.strategy_id != strategy.strategy_id
        or pack.campaign_id != request.campaign_id
        or pack.budget is not request.budget
    ):
        raise LifecycleClosureError("request, strategy and production pack disagree")
    calendar = compile_content_calendar(
        request,
        strategy,
        pack.channel_portfolio,
        source_draft_ids={
            pack.primary_copy.channel: pack.primary_copy.draft_id,
            pack.secondary_copy.channel: pack.secondary_copy.draft_id,
        },
        compiled_at=compiled_at,
        schedule_timezone=schedule_timezone,
    )
    verify_content_calendar(calendar, compiled_at=compiled_at)
    observed_at = received_at or datetime(2026, 7, 9, tzinfo=timezone.utc)
    post_selection_probe = _synthetic_post_selection_probe(
        request, strategy, pack
    )

    scenarios: list[dict[str, object]] = []
    for scenario in _SCENARIOS:
        if scenario == "zero_budget_spend_breach" and request.budget is not BudgetTier.ZERO:
            continue
        effect = _effect(request, pack, scenario=scenario, received_at=observed_at)
        revenue = None
        if scenario in {
            "qualified_positive_requires_human",
            "negative_contribution",
            "zero_budget_spend_breach",
        }:
            revenue = _revenue(request, effect, scenario=scenario)
        expected = {
            "qualified_positive_requires_human": (
                "continue_candidate_for_human_review",
                "continue_candidate_for_human_revenue_review",
            ),
            "insufficient_sample": ("collect_more_data", None),
            "complaint_regression": ("stop_and_review", None),
            "negative_contribution": (
                "continue_candidate_for_human_review",
                "stop_and_review_negative_contribution",
            ),
            "zero_budget_spend_breach": (
                "stop_and_review",
                "stop_and_review_zero_budget_breach",
            ),
        }[scenario]
        effect_decision = effect["next_cycle_decision"]
        revenue_decision = revenue["next_cycle_decision"] if revenue else None
        passed = effect_decision == expected[0] and revenue_decision == expected[1]
        if not passed:
            raise LifecycleClosureError(f"{scenario} produced an unsafe decision")
        scenarios.append(
            {
                "scenario": scenario,
                "effect_observation_sha256": effect["observation_sha256"],
                "effect_decision": effect_decision,
                "revenue_economics_sha256": (
                    revenue["economics_sha256"] if revenue else None
                ),
                "revenue_decision": revenue_decision,
                "human_review_required": effect["human_review_required"] is True
                and (
                    revenue is None
                    or revenue["human_revenue_review_required"] is True
                ),
                "automatic_strategy_mutation_executed": False,
                "automatic_budget_activation_executed": False,
                "automatic_external_publish_executed": False,
                "passed": True,
            }
        )

    harness = production_graph_loop_harness(
        maximum_actions=24,
        maximum_cost_usd=0.0,
    ).receipt()
    artifact_payloads = pack.artifact_payloads()
    landing_page = artifact_payloads["landing-page-draft.json"]
    lifecycle_email = artifact_payloads["lifecycle-email-draft.json"]
    workspace_artifacts = {
        name: artifact_payloads[name]
        for name in (
            "big-idea-and-message-hierarchy.json",
            "channel-copy.json",
            "landing-page-draft.json",
            "lifecycle-email-draft.json",
            "seo-geo-faq-drafts.json",
            "video-production-brief.json",
            "audio-production-brief.json",
            "analytics-plan.json",
        )
    }
    workspace_artifacts["content-calendar.json"] = calendar
    same_evidence_spine = landing_page["citation"] == lifecycle_email["citation"]
    all_activation_disabled = (
        landing_page["human_release_required"] is True
        and landing_page["automated_publish_allowed"] is False
        and landing_page["external_publish_executed"] is False
        and lifecycle_email["human_release_required"] is True
        and lifecycle_email["automated_send_allowed"] is False
        and lifecycle_email["external_send_executed"] is False
    )
    last_mile_workspace = {
        "schema": "ProofLaunchCampaignWorkspaceClosureV1",
        "artifact_count": len(workspace_artifacts),
        "artifact_set_sha256": _digest(workspace_artifacts),
        "landing_page_schema": landing_page["schema"],
        "lifecycle_email_schema": lifecycle_email["schema"],
        "same_evidence_spine": same_evidence_spine,
        "all_activation_disabled": all_activation_disabled,
        "external_actions_executed": 0,
        "truth_boundary": (
            "The workspace contains content-addressed drafts and preregistered effect "
            "plans. It does not prove publication, delivery, performance or 4A preference."
        ),
    }
    capabilities = {
        "industry_and_data_strategy": bool(pack.industry_gtm_profile),
        "channel_portfolio_and_ads": len(pack.channel_portfolio["portfolio"]) == 12,
        "content_calendar": calendar["slot_count"] == 7,
        "text_generation": len(pack.text_creative_challenger_plan["requests"]) == 3,
        "seo_geo": len(pack.seo_geo_faqs) >= 1,
        "video_generation_contract": "3840x2160" in pack.video_brief.delivery_spec,
        "audio_generation_contract": "48 kHz" in pack.audio_brief.mix_spec,
        "analytics": len(pack.analytics.metrics) >= 1,
        "revenue_feedback": any(
            item["revenue_economics_sha256"] for item in scenarios
        ),
        "agent_graph_loop_harness": harness["autonomy_level"]
        == "L2_deterministic_workflow",
    }
    if not all(capabilities.values()):
        raise LifecycleClosureError("one or more lifecycle capabilities are disconnected")
    core: dict[str, object] = {
        "schema": "ProofLaunchGTMLifecycleClosureCaseV1",
        "campaign_id": request.campaign_id,
        "strategy_id": strategy.strategy_id,
        "production_pack_sha256": pack.content_sha256,
        "calendar_sha256": calendar["content_sha256"],
        "graph_loop_harness_sha256": harness["contract_sha256"],
        "business_model": request.audience.business_model.value,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "industry_risk": request.industry_risk.value,
        "capabilities": capabilities,
        "last_mile_workspace": last_mile_workspace,
        "post_selection_omnichannel_probe": post_selection_probe,
        "scenarios": scenarios,
        "scenario_count": len(scenarios),
        "zero_budget_paid_channels_excluded": (
            request.budget is not BudgetTier.ZERO
            or all(
                not item["paid_channel"]
                or item["activation_state"] == "excluded"
                for item in pack.channel_portfolio["portfolio"]
            )
        ),
        "external_actions_executed": 0,
        "model_calls_executed": 0,
        "cloud_api_calls_executed": 0,
        "synthetic_observation_count": len(scenarios),
        "production_outcomes_observed": 0,
        "human_blind_reviews_observed": 0,
        "four_a_effect_proven": False,
        "causal_revenue_proven": False,
        "truth_boundary": (
            "This case proves deterministic integration over synthetic fixtures. It does "
            "not prove live publication, production outcomes, causal revenue, annual "
            "breakout performance, human preference, 4A quality or Top-1 standing."
        ),
    }
    core["content_sha256"] = _digest(core)
    verify_lifecycle_closure_case(core)
    return core


def verify_lifecycle_closure_case(case: Mapping[str, object]) -> None:
    if case.get("schema") != "ProofLaunchGTMLifecycleClosureCaseV1":
        raise LifecycleClosureError("lifecycle closure schema is invalid")
    supplied = case.get("content_sha256")
    payload = dict(case)
    payload.pop("content_sha256", None)
    if supplied != _digest(payload):
        raise LifecycleClosureError("lifecycle closure digest mismatch")
    capabilities = case.get("capabilities")
    scenarios = case.get("scenarios")
    workspace = case.get("last_mile_workspace")
    post_selection = case.get("post_selection_omnichannel_probe")
    if not isinstance(capabilities, Mapping) or not capabilities or not all(
        value is True for value in capabilities.values()
    ):
        raise LifecycleClosureError("lifecycle capability coverage is incomplete")
    if not isinstance(scenarios, list) or case.get("scenario_count") != len(scenarios):
        raise LifecycleClosureError("lifecycle scenario count is invalid")
    if (
        not isinstance(workspace, Mapping)
        or workspace.get("schema") != "ProofLaunchCampaignWorkspaceClosureV1"
        or workspace.get("artifact_count") != 9
        or not isinstance(workspace.get("artifact_set_sha256"), str)
        or len(str(workspace.get("artifact_set_sha256"))) != 64
        or workspace.get("landing_page_schema")
        != "ProofLaunchLandingPageDraftV1"
        or workspace.get("lifecycle_email_schema")
        != "ProofLaunchLifecycleEmailDraftV1"
        or workspace.get("same_evidence_spine") is not True
        or workspace.get("all_activation_disabled") is not True
        or workspace.get("external_actions_executed") != 0
    ):
        raise LifecycleClosureError("last-mile campaign workspace is incomplete or unsafe")
    if (
        not isinstance(post_selection, Mapping)
        or post_selection.get("schema")
        != "ProofLaunchSyntheticPostSelectionProbeV1"
        or post_selection.get("campaign_id") != case.get("campaign_id")
        or post_selection.get("strategy_id") != case.get("strategy_id")
        or post_selection.get("lane_count") != 9
        or post_selection.get("same_creative_system_across_lanes") is not True
        or post_selection.get("same_evidence_spine_across_lanes") is not True
        or post_selection.get("all_external_actions_disabled") is not True
        or post_selection.get("effect_claim_eligible") is not False
        or post_selection.get("synthetic_human_selection_probe") is not True
        or post_selection.get("human_selection_observed") is not False
    ):
        raise LifecycleClosureError("post-selection omnichannel probe is invalid")
    if case.get("budget") == BudgetTier.ZERO.value and case.get(
        "zero_budget_paid_channels_excluded"
    ) is not True:
        raise LifecycleClosureError("zero-budget case admitted a paid channel")
    if any(
        item.get("passed") is not True
        or item.get("human_review_required") is not True
        or item.get("automatic_strategy_mutation_executed") is not False
        or item.get("automatic_budget_activation_executed") is not False
        or item.get("automatic_external_publish_executed") is not False
        for item in scenarios
        if isinstance(item, Mapping)
    ):
        raise LifecycleClosureError("a lifecycle scenario bypasses the harness")
    if (
        case.get("external_actions_executed") != 0
        or case.get("model_calls_executed") != 0
        or case.get("cloud_api_calls_executed") != 0
        or case.get("production_outcomes_observed") != 0
        or case.get("human_blind_reviews_observed") != 0
        or case.get("four_a_effect_proven") is not False
        or case.get("causal_revenue_proven") is not False
    ):
        raise LifecycleClosureError("synthetic lifecycle evidence was overstated")
