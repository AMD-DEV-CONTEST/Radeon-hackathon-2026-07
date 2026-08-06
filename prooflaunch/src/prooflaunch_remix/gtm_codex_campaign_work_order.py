from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Mapping

from .gtm_industry_profile import verify_industry_gtm_profile
from .gtm_strategy import BudgetTier, CampaignStrategyInput, Channel, GTMStrategy


class CodexCampaignWorkOrderError(ValueError):
    """A generative campaign work order escaped its brief, graph, or harness."""


PROTOCOL_SCHEMA = "ProofLaunchCodexCampaignGenerationProtocolV1"
WORK_ORDER_SCHEMA = "ProofLaunchCodexCampaignGenerationWorkOrderV1"
MATRIX_SCHEMA = "ProofLaunchCodexCampaignAdaptationMatrixV1"

SURFACE_IDS = (
    "linkedin",
    "tiktok",
    "reddit",
    "youtube",
    "instagram",
    "x",
    "google_search",
    "bing_search",
    "chatgpt_answers",
    "claude_answers",
    "gemini_answers",
    "perplexity_answers",
    "copilot_answers",
)

CHANNEL_SURFACE_MAP: dict[Channel, tuple[str, ...]] = {
    Channel.COMMUNITY_LISTENING: ("reddit", "x"),
    Channel.CREATOR_COMMUNITY: ("tiktok", "instagram", "youtube"),
    Channel.CUSTOMER_EVIDENCE: ("linkedin", "youtube", "google_search"),
    Channel.CUSTOMER_EMAIL: ("linkedin", "google_search", "chatgpt_answers"),
    Channel.FOUNDER_CONVERSATIONS: ("linkedin", "reddit", "x"),
    Channel.LINKEDIN_ORGANIC: ("linkedin", "x"),
    Channel.OWNED_SOCIAL: ("instagram", "tiktok", "x"),
    Channel.PARTNER_COMMUNITIES: ("linkedin", "reddit", "youtube"),
    Channel.SEARCH_EDUCATION: (
        "google_search",
        "bing_search",
        "chatgpt_answers",
        "perplexity_answers",
    ),
    Channel.SHORT_VIDEO_ORGANIC: ("tiktok", "instagram", "youtube"),
    Channel.PAID_SEARCH: ("google_search", "bing_search"),
    Channel.PAID_SOCIAL: ("linkedin", "instagram", "tiktok"),
}

_SHA = re.compile(r"^[0-9a-f]{64}$")


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_codex_campaign_generation_protocol() -> dict[str, Any]:
    """Compile the shared deterministic graph and model freedom envelope."""

    protocol: dict[str, Any] = {
        "schema": PROTOCOL_SCHEMA,
        "protocol_version": "2026-08-03.1",
        "autonomy_level": "L2_deterministic_workflow_with_bounded_model_generation",
        "composition_patterns": [
            "routing",
            "prompt_chaining",
            "evaluator_optimizer_one_repair_round",
        ],
        "graph": [
            {
                "stage": "classify_and_bind",
                "executor": "deterministic_code",
                "output": "industry profile, evidence spine, lifecycle, budget and permission envelope",
                "commit_gate": "schema, digest, rights, validity and business-model fit",
            },
            {
                "stage": "route_and_frame",
                "executor": "deterministic_code",
                "output": "two focus channels, thirteen surface jobs and output contract",
                "commit_gate": "zero-budget exclusions, channel focus and exact surface coverage",
            },
            {
                "stage": "direct_and_generate",
                "executor": "flagship_model_single_coherent_context",
                "output": "one integrated strategy and last-mile campaign system",
                "commit_gate": "strict JSON schema; no tool, publish, send or spend authority",
            },
            {
                "stage": "critic_and_repair",
                "executor": "focused_binary_model_critics_then_same_generator",
                "output": "accepted draft or one located repair",
                "commit_gate": "maximum one repair round; critics cannot release or promote",
            },
            {
                "stage": "verify_and_queue_human",
                "executor": "deterministic_code_then_named_human_review",
                "output": "sealed capability candidate or fail-closed rejection",
                "commit_gate": "Level-1 assertions pass and named human release remains pending",
            },
        ],
        "required_output_contract": {
            "strategic_core": {
                "count": 1,
                "required_fields": [
                    "campaign_system_name",
                    "narrow_audience",
                    "job_to_be_done",
                    "category_enemy",
                    "human_tension",
                    "organizing_idea",
                    "proof_spine",
                    "promise_hypothesis",
                    "rejection_rule",
                    "growth_loop",
                ],
            },
            "platform_native_assets": {
                "count": 13,
                "surface_ids": list(SURFACE_IDS),
                "required_fields": [
                    "surface_id",
                    "campaign_platform",
                    "hook",
                    "progression",
                    "body",
                    "cta",
                    "participation_mechanism",
                    "proof_integration",
                    "falsifier",
                ],
            },
            "lifecycle_phases": {
                "count": 4,
                "phase_ids": ["diagnose", "prove", "participate", "convert_and_learn"],
                "all_surfaces_assigned_exactly_once": True,
            },
            "email_sequence": {"count": 4, "lifecycle_state_required": True},
            "production_directions": {
                "count": 3,
                "kinds": ["image_system", "video_system", "audio_system"],
                "acceptance_test_required": True,
            },
            "search_geo_nodes": {
                "count": 7,
                "surface_ids": list(SURFACE_IDS[6:]),
                "source_and_rejection_condition_required": True,
            },
            "seven_day_flight": {
                "count": 7,
                "human_review_status_required": True,
                "primary_secondary_focus_required": True,
            },
            "experiment_registry": {
                "count": 4,
                "experiment_ids": [
                    "hook_hold",
                    "qualified_participation",
                    "proof_depth",
                    "conversion_intent",
                ],
                "numerator_denominator_baseline_and_kill_rule_required": True,
            },
        },
        "model_context_order": [
            "immutable_brief",
            "approved_evidence",
            "industry_operating_contract",
            "lifecycle_and_budget_constraints",
            "channel_focus",
            "voice_and_prohibited_tactics",
            "required_output_contract",
            "evaluation_and_stop_rules",
        ],
        "named_failure_modes": [
            {
                "failure_id": "brief_drift",
                "caught_by": "Level-1 exact input and digest assertions",
            },
            {
                "failure_id": "claim_or_product_detail_hallucination",
                "caught_by": "Level-1 approved-claim equality plus focused factual critic",
            },
            {
                "failure_id": "platform_flattening",
                "caught_by": "Level-1 native blueprint markers plus focused platform critic",
            },
            {
                "failure_id": "spray_and_pray_distribution",
                "caught_by": "Level-1 two-channel focus and seven-day job assertions",
            },
            {
                "failure_id": "generic_campaign_platform",
                "caught_by": "binary campaign-system critic calibrated against named humans",
            },
            {
                "failure_id": "synthetic_or_unobserved_effect_leakage",
                "caught_by": "Level-1 effect-language and evidence-class assertions",
            },
            {
                "failure_id": "rights_privacy_or_regulatory_escape",
                "caught_by": "Level-1 claim rights, risk and specialist approval assertions",
            },
            {
                "failure_id": "missing_falsifier_or_stop_rule",
                "caught_by": "Level-1 required-field and experiment assertions",
            },
            {
                "failure_id": "vanity_metric_optimization",
                "caught_by": "Level-1 numerator, denominator, qualification and economics binding",
            },
            {
                "failure_id": "model_judge_authority_leak",
                "caught_by": "code-enforced no-release/no-promotion permission gate",
            },
        ],
        "evaluation_pyramid": {
            "level_1_code": {
                "runs": "every_generation_and_every_change",
                "binary_only": True,
                "blocks_on_any_failure": True,
            },
            "level_2_model_critics": {
                "criteria": [
                    "campaign_system_specific_not_generic",
                    "platform_expression_native_not_reformatted",
                    "audience_language_and_objection_fit",
                    "proof_and_limitation_co_present",
                ],
                "binary_only": True,
                "human_calibration_required": True,
                "minimum_calibration_labels_per_critic": 100,
                "minimum_tpr": 0.8,
                "minimum_tnr": 0.8,
                "can_release_or_promote": False,
            },
            "level_3_human": {
                "required_for": [
                    "craft_preference",
                    "brand_voice",
                    "cultural_fit",
                    "release",
                    "named_product_pk",
                ],
                "source_hidden_binary_preference": True,
                "can_be_substituted_by_model": False,
            },
        },
        "termination_conditions": {
            "maximum_generation_attempts": 2,
            "maximum_critic_repair_rounds": 1,
            "stop_on_schema_or_digest_failure": True,
            "stop_on_claim_rights_or_safety_failure": True,
            "stop_on_unresolved_failure_after_repair": True,
            "success_state": "sealed_capability_candidate_pending_named_human_review",
            "failure_state": "rejected_fail_closed_with_located_reasons",
        },
        "permissions": {
            "model_may_generate_drafts": True,
            "model_may_select_or_change_approved_claim": False,
            "model_may_publish_send_spend_or_contact": False,
            "model_may_change_strategy_after_observation": False,
            "model_critic_may_release_or_promote": False,
            "named_human_release_required": True,
            "automatic_external_action_count": 0,
        },
        "trace_contract": {
            "log_input_and_protocol_digests": True,
            "log_model_provider_id_and_parameters": True,
            "log_each_attempt_and_located_failure": True,
            "log_repair_diff": True,
            "log_human_decision_separately": True,
            "hidden_chain_of_thought_required": False,
            "retention_policy_reference": "production-trace-retention-v1",
        },
        "truth_boundary": (
            "This protocol proves an L2 Graph/Loop/Harness contract for campaign generation. "
            "It does not prove a model call occurred, an output passed human review, a named product was beaten, or market effect."
        ),
    }
    protocol["content_sha256"] = _digest(protocol)
    verify_codex_campaign_generation_protocol(protocol)
    return protocol


def verify_codex_campaign_generation_protocol(protocol: Mapping[str, Any]) -> None:
    unsigned = dict(protocol)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexCampaignWorkOrderError("campaign generation protocol digest is invalid")
    if (
        protocol.get("schema") != PROTOCOL_SCHEMA
        or protocol.get("autonomy_level")
        != "L2_deterministic_workflow_with_bounded_model_generation"
        or len(protocol.get("graph", [])) != 5
        or len(protocol.get("named_failure_modes", [])) != 10
        or protocol.get("termination_conditions", {}).get("maximum_generation_attempts")
        != 2
        or protocol.get("termination_conditions", {}).get(
            "maximum_critic_repair_rounds"
        )
        != 1
        or protocol.get("permissions", {}).get("model_may_publish_send_spend_or_contact")
        is not False
        or protocol.get("permissions", {}).get("model_critic_may_release_or_promote")
        is not False
        or protocol.get("permissions", {}).get("automatic_external_action_count")
        != 0
    ):
        raise CodexCampaignWorkOrderError("campaign generation protocol boundary drifted")
    output = protocol.get("required_output_contract", {})
    if (
        output.get("platform_native_assets", {}).get("count") != 13
        or output.get("email_sequence", {}).get("count") != 4
        or output.get("production_directions", {}).get("count") != 3
        or output.get("search_geo_nodes", {}).get("count") != 7
        or output.get("seven_day_flight", {}).get("count") != 7
        or output.get("experiment_registry", {}).get("count") != 4
    ):
        raise CodexCampaignWorkOrderError("campaign generation output contract drifted")


def compile_codex_campaign_work_order(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    industry_profile: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile one arbitrary brief into a bounded flagship-model work order."""

    verify_codex_campaign_generation_protocol(protocol)
    verify_industry_gtm_profile(industry_profile)
    if (
        industry_profile.get("campaign_id") != request.campaign_id
        or industry_profile.get("business_model") != request.audience.business_model.value
        or industry_profile.get("lifecycle") != request.lifecycle.value
        or industry_profile.get("budget") != request.budget.value
        or industry_profile.get("industry_risk") != request.industry_risk.value
        or industry_profile.get("source_strategy_sha256") != _digest(strategy)
        or industry_profile.get("strategy_id") not in {None, strategy.strategy_id}
    ):
        raise CodexCampaignWorkOrderError("industry profile escaped the campaign brief")
    if strategy.proof_claim_id not in {claim.claim_id for claim in request.claims}:
        raise CodexCampaignWorkOrderError("strategy proof escaped the approved claim set")
    if request.budget is BudgetTier.ZERO and (
        strategy.primary_channel.paid or strategy.secondary_channel.paid
    ):
        raise CodexCampaignWorkOrderError("zero-budget work order selected a paid channel")

    primary_surfaces = list(CHANNEL_SURFACE_MAP[strategy.primary_channel])
    secondary_surfaces = list(CHANNEL_SURFACE_MAP[strategy.secondary_channel])
    overlapping_surfaces = sorted(set(primary_surfaces) & set(secondary_surfaces))
    request_sha = _digest(request)
    strategy_sha = _digest(strategy)
    approved_claims = [
        {
            "claim_id": claim.claim_id,
            "exact_text": claim.text,
            "evidence_uri": claim.evidence_uri,
            "evidence_sha256": claim.evidence_sha256,
            "rights": claim.rights.value,
            "rights_reference": claim.rights_reference,
            "approved_by": claim.approved_by,
            "specialist_approved_by": claim.specialist_approved_by,
            "valid_from": claim.valid_from,
            "valid_until": claim.valid_until,
        }
        for claim in request.claims
    ]
    work_order: dict[str, Any] = {
        "schema": WORK_ORDER_SCHEMA,
        "work_order_id": (
            f"codex-campaign-{industry_profile['industry_archetype']}-"
            f"{request.audience.business_model.value}-{request.lifecycle.value}-"
            f"{request.budget.value}-{request_sha[:10]}"
        ),
        "protocol_sha256": protocol["content_sha256"],
        "request_sha256": request_sha,
        "strategy_sha256": strategy_sha,
        "industry_profile_sha256": industry_profile["content_sha256"],
        "immutable_brief": {
            "campaign_id": request.campaign_id,
            "brand_name": request.brand.brand_name,
            "industry": request.industry,
            "industry_archetype": industry_profile["industry_archetype"],
            "business_model": request.audience.business_model.value,
            "lifecycle": request.lifecycle.value,
            "budget": request.budget.value,
            "industry_risk": request.industry_risk.value,
            "product_category": request.product_category,
            "product_surface": request.product_surface.value,
            "audience_name": request.audience.name,
            "audience_role": request.audience_role,
            "core_problem": request.audience.core_problem,
            "desired_outcome": request.audience.desired_outcome,
            "buying_context": request.audience.buying_context,
            "objective": request.objective,
            "offer": request.offer,
            "landing_url": request.landing_url,
            "voice_principles": list(request.brand.voice_principles),
            "prohibited_tactics": list(request.brand.prohibited_tactics),
        },
        "approved_evidence": {
            "selected_proof_claim_id": strategy.proof_claim_id,
            "selected_proof_exact_text": strategy.proof,
            "claims": approved_claims,
            "proof_gate": industry_profile["proof_gate"],
            "model_may_add_product_facts": False,
            "model_may_strengthen_claim_language": False,
        },
        "industry_operating_contract": {
            key: industry_profile[key]
            for key in (
                "classification_status",
                "human_classification_confirmation_required",
                "business_model_fit",
                "buying_motion",
                "decision_unit",
                "conversion_unit",
                "evidence_ladder",
                "zero_budget_growth_engine",
                "distribution_surfaces",
                "unit_economics_metrics",
                "feedback_signals",
                "creative_constraints",
                "specialist_roles",
            )
        },
        "strategy_contract": {
            "strategy_id": strategy.strategy_id,
            "hero_hypothesis": strategy.hero_hypothesis,
            "objection": strategy.objection,
            "call_to_action": strategy.call_to_action,
            "primary_channel": strategy.primary_channel.value,
            "secondary_channel": strategy.secondary_channel.value,
            "primary_platform_surfaces": primary_surfaces,
            "secondary_platform_surfaces": secondary_surfaces,
            "overlapping_platform_surfaces": overlapping_surfaces,
            "overlap_requires_distinct_content_jobs": bool(overlapping_surfaces),
            "all_thirteen_surfaces_required_for_capability_coverage": True,
            "only_focus_surfaces_may_enter_the_initial_seven_day_flight": True,
            "seo_geo_question_intents": list(strategy.seo_geo_question_intents),
            "metrics": _normalize(strategy.metrics),
            "stop_rules": list(strategy.stop_rules),
            "rights_and_safety_notes": list(strategy.rights_and_safety_notes),
        },
        "model_task": {
            "role": "single_coherent_flagship_creative_and_gtm_director",
            "instruction": (
                "Generate one integrated campaign system, not thirteen independent posts. "
                "Start from a human tension and an industry-native behavior, preserve the exact proof, "
                "assign each surface a distinct lifecycle job, and return only the required JSON object."
            ),
            "creative_quality_requirements": [
                "one organizing idea survives copy, image, video, audio, email, search and GEO",
                "language fits the named decision unit and buying motion",
                "primary and secondary channels receive the strongest production effort",
                "every platform asset has a native structure and cannot be swapped unchanged",
                "participation produces a useful action rather than a vanity reaction",
                "proof, limitation and falsifier remain adjacent",
                "experiments optimize qualified behavior and economics rather than impressions",
            ],
            "required_output_contract": protocol["required_output_contract"],
        },
        "harness": {
            "named_failure_modes": protocol["named_failure_modes"],
            "evaluation_pyramid": protocol["evaluation_pyramid"],
            "termination_conditions": protocol["termination_conditions"],
            "permissions": protocol["permissions"],
            "trace_contract": protocol["trace_contract"],
        },
        "execution_state": {
            "generation_status": "queued_no_model_call_observed",
            "model_call_count": 0,
            "generation_attempt_count": 0,
            "critic_repair_round_count": 0,
            "candidate_output_present": False,
            "level_1_passed": False,
            "level_2_passed": False,
            "named_human_review_completed": False,
            "release_eligible": False,
            "external_publish_executed": False,
            "production_effect_observed": False,
            "causal_effect_claim_allowed": False,
            "automatic_strategy_mutation_executed": False,
        },
        "truth_boundary": (
            "This work order proves that an arbitrary evidence-bound brief was compiled into a model-ready campaign-generation contract. "
            "It does not prove inference, output quality, human preference, publication, market effect, revenue or product superiority."
        ),
    }
    work_order["content_sha256"] = _digest(work_order)
    verify_codex_campaign_work_order(work_order, protocol=protocol)
    return work_order


def verify_codex_campaign_work_order(
    work_order: Mapping[str, Any], *, protocol: Mapping[str, Any]
) -> None:
    verify_codex_campaign_generation_protocol(protocol)
    unsigned = dict(work_order)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexCampaignWorkOrderError("campaign work-order digest is invalid")
    if (
        work_order.get("schema") != WORK_ORDER_SCHEMA
        or work_order.get("protocol_sha256") != protocol.get("content_sha256")
        or _SHA.fullmatch(str(work_order.get("request_sha256", ""))) is None
        or _SHA.fullmatch(str(work_order.get("strategy_sha256", ""))) is None
        or _SHA.fullmatch(str(work_order.get("industry_profile_sha256", ""))) is None
    ):
        raise CodexCampaignWorkOrderError("campaign work-order binding is invalid")
    brief = work_order.get("immutable_brief", {})
    evidence = work_order.get("approved_evidence", {})
    strategy = work_order.get("strategy_contract", {})
    if (
        brief.get("business_model") not in {"b2b", "b2c"}
        or brief.get("lifecycle") not in {"pre_pmf", "launch", "growth", "mature"}
        or brief.get("budget") not in {"zero", "small", "scaled"}
        or evidence.get("model_may_add_product_facts") is not False
        or evidence.get("model_may_strengthen_claim_language") is not False
        or len(evidence.get("claims", [])) < 1
        or strategy.get("all_thirteen_surfaces_required_for_capability_coverage")
        is not True
        or strategy.get("only_focus_surfaces_may_enter_the_initial_seven_day_flight")
        is not True
        or not strategy.get("primary_platform_surfaces")
        or not strategy.get("secondary_platform_surfaces")
        or strategy.get("primary_channel") == strategy.get("secondary_channel")
        or strategy.get("overlap_requires_distinct_content_jobs")
        is not bool(strategy.get("overlapping_platform_surfaces"))
    ):
        raise CodexCampaignWorkOrderError("campaign work-order context is incomplete")
    if brief.get("budget") == "zero" and (
        strategy.get("primary_channel") in {"paid_search", "paid_social"}
        or strategy.get("secondary_channel") in {"paid_search", "paid_social"}
    ):
        raise CodexCampaignWorkOrderError("zero-budget work order gained a paid channel")
    state = work_order.get("execution_state", {})
    if (
        state.get("generation_status") != "queued_no_model_call_observed"
        or state.get("model_call_count") != 0
        or state.get("candidate_output_present") is not False
        or state.get("named_human_review_completed") is not False
        or state.get("release_eligible") is not False
        or state.get("external_publish_executed") is not False
        or state.get("production_effect_observed") is not False
        or state.get("causal_effect_claim_allowed") is not False
        or state.get("automatic_strategy_mutation_executed") is not False
    ):
        raise CodexCampaignWorkOrderError("campaign work-order execution authority drifted")


def verify_codex_campaign_adaptation_matrix(matrix: Mapping[str, Any]) -> None:
    unsigned = dict(matrix)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise CodexCampaignWorkOrderError("campaign adaptation matrix digest is invalid")
    protocol = matrix.get("generation_protocol")
    if not isinstance(protocol, Mapping):
        raise CodexCampaignWorkOrderError("campaign adaptation protocol is missing")
    verify_codex_campaign_generation_protocol(protocol)
    work_orders = matrix.get("work_orders")
    if (
        matrix.get("schema") != MATRIX_SCHEMA
        or matrix.get("case_count") != 456
        or matrix.get("work_order_count") != 456
        or not isinstance(work_orders, list)
        or len(work_orders) != 456
        or len({row.get("work_order_id") for row in work_orders if isinstance(row, Mapping)})
        != 456
        or matrix.get("model_call_count") != 0
        or matrix.get("candidate_output_count") != 0
        or matrix.get("human_review_completed_count") != 0
        or matrix.get("release_eligible_count") != 0
        or matrix.get("external_publish_executed_count") != 0
        or matrix.get("production_effect_observed_count") != 0
        or matrix.get("causal_effect_claim_allowed_count") != 0
        or matrix.get("empty_secondary_platform_surface_work_order_count") != 0
    ):
        raise CodexCampaignWorkOrderError("campaign adaptation matrix boundary drifted")
    for work_order in work_orders:
        if not isinstance(work_order, Mapping):
            raise CodexCampaignWorkOrderError("campaign adaptation work order is invalid")
        verify_codex_campaign_work_order(work_order, protocol=protocol)


__all__ = [
    "CodexCampaignWorkOrderError",
    "MATRIX_SCHEMA",
    "PROTOCOL_SCHEMA",
    "SURFACE_IDS",
    "WORK_ORDER_SCHEMA",
    "compile_codex_campaign_generation_protocol",
    "compile_codex_campaign_work_order",
    "verify_codex_campaign_adaptation_matrix",
    "verify_codex_campaign_generation_protocol",
    "verify_codex_campaign_work_order",
]
