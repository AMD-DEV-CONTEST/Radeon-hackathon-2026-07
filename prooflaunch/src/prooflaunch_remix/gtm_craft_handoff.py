from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_human_capability_kernel import (
    PROFESSIONAL_AXIS_IDS,
    SURFACE_SPECIALIST_LENSES,
    _surface_ids,
    normalize_surface_id,
    surface_playbook,
    unconventional_edge_play,
)
from .gtm_strategy import CampaignStrategyInput, GTMStrategy
from .gtm_team_capability_os import GTMTeamCapabilityError, verify_gtm_team_capability_contract


class GTMCraftHandoffError(ValueError):
    """A specialist handoff graph is incomplete, unbound, or unsafe."""


PLAN_SCHEMA = "ProofLaunchGTMCraftHandoffPlanV1"
REVIEW_SCHEMA = "ProofLaunchGTMCraftAdvisoryReviewV1"
_DECISIONS = ("pass", "revise", "block")
_REVIEW_FIELDS = frozenset(
    {
        "schema",
        "work_order_id",
        "territory_id",
        "strategy_id",
        "candidate_content_sha256",
        "decision",
        "blocking_findings",
        "repair_instructions",
    }
)


ROLE_SKILL_SELECTIONS: dict[str, tuple[str, ...]] = {
    "gtm_general_manager": (
        "portfolio_strategy",
        "stage_budget_diagnosis",
        "market_sequencing",
        "resource_allocation",
        "cross_function_arbitration",
    ),
    "market_intelligence_lead": (
        "query_lattice_design",
        "source_triangulation",
        "temporal_change_detection",
        "competitor_mechanism_abstraction",
    ),
    "audience_research_lead": (
        "behavioral_segmentation",
        "decision_unit_mapping",
        "anxiety_and_desire_language",
        "persona_falsification",
    ),
    "product_marketing_lead": (
        "positioning",
        "message_hierarchy",
        "proof_architecture",
        "objection_mapping",
    ),
    "creative_strategy_director": (
        "big_idea_development",
        "cultural_tension_framing",
        "proof_sequence",
        "concept_divergence",
        "senior_critique",
    ),
    "senior_social_copywriter": (
        "hook_writing",
        "voice_matching",
        "spoken_rhythm",
        "claim_safe_persuasion",
        "line_editing",
    ),
    "longform_editorial_director": (
        "thesis_development",
        "argument_architecture",
        "narrative_pacing",
        "structural_editing",
        "citation_integrity",
    ),
    "short_video_director": (
        "beat_sheet",
        "first_frame_direction",
        "retention_pacing",
        "edit_notes",
        "platform_cut_strategy",
    ),
    "seo_geo_editor": (
        "intent_mapping",
        "information_gain",
        "entity_clarity",
        "answer_extractability",
        "source_citation",
    ),
    "lifecycle_crm_strategist": (
        "lifecycle_state_model",
        "message_sequence",
        "personalization_boundary",
        "frequency_capping",
        "consent_management",
    ),
    "platform_distribution_strategist": (
        "platform_grammar",
        "format_selection",
        "community_norms",
        "cross_platform_rewrite",
        "algorithm_change_monitoring",
    ),
    "brand_safety_claims_lead": (
        "claim_review",
        "evidence_validity",
        "copyright_boundary",
        "platform_policy",
        "release_authority",
    ),
    "localization_cultural_editor": (
        "transcreation",
        "cultural_context",
        "dialect_register",
        "inclusive_language",
        "native_editor_review",
    ),
    "growth_data_experimentation_lead": (
        "metric_tree",
        "experiment_design",
        "power_analysis",
        "uncertainty_calibration",
    ),
    "agent_quality_learning_engineer": (
        "task_taxonomy",
        "trajectory_eval",
        "failure_slicing",
        "adversarial_eval",
        "human_promotion_gate",
    ),
    "sales_enablement_revops_lead": (
        "stage_definition",
        "enablement_asset",
        "crm_hygiene",
        "handoff_sla",
        "revenue_reconciliation",
    ),
    "demand_generation_lead": (
        "offer_design",
        "campaign_architecture",
        "lead_quality",
        "incrementality",
        "budget_stop_rules",
    ),
    "product_led_growth_lead": (
        "first_value_design",
        "onboarding_experiment",
        "referral_loop",
        "retention_cohort",
        "product_experimentation",
    ),
    "art_design_director": (
        "art_direction",
        "visual_metaphor",
        "layout_hierarchy",
        "product_fidelity",
        "visual_quality_review",
    ),
    "audio_voice_producer": (
        "voice_casting",
        "performance_pacing",
        "sound_design",
        "mixing",
        "rights_clearance",
    ),
    "organic_growth_community_lead": (
        "community_mapping",
        "listen_before_speak",
        "utility_asset",
        "feedback_loop",
        "anti_spam_control",
    ),
    "creator_partnerships_lead": (
        "creator_fit",
        "brief_co_creation",
        "creative_freedom_boundary",
        "rights_and_usage",
        "partnership_incrementality",
    ),
}


_CHANNEL_PRODUCER_PREFERENCES: dict[str, tuple[str, ...]] = {
    "short_video_organic": ("short_video_director", "senior_social_copywriter"),
    "search_education": ("seo_geo_editor", "longform_editorial_director", "senior_social_copywriter"),
    "customer_email": ("lifecycle_crm_strategist", "senior_social_copywriter"),
    "customer_evidence": ("longform_editorial_director", "senior_social_copywriter"),
    "linkedin_organic": ("senior_social_copywriter", "longform_editorial_director"),
    "founder_conversations": ("senior_social_copywriter", "longform_editorial_director"),
    "partner_communities": ("senior_social_copywriter", "longform_editorial_director"),
    "community_listening": ("senior_social_copywriter",),
    "creator_community": ("senior_social_copywriter", "short_video_director"),
    "owned_social": ("senior_social_copywriter",),
    "paid_search": ("senior_social_copywriter", "seo_geo_editor"),
    "paid_social": ("senior_social_copywriter", "short_video_director"),
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _work_order(
    *,
    order_id: str,
    stage: str,
    role_id: str,
    role_registry: Mapping[str, Mapping[str, Any]],
    input_binding_sha256: str,
    output_contract: Sequence[str],
    acceptance: Sequence[str],
    surface_id: str,
    business_model: str,
    channel: str | None = None,
    depends_on: Sequence[str] = (),
) -> dict[str, Any]:
    role = role_registry.get(role_id)
    if not isinstance(role, Mapping):
        raise GTMCraftHandoffError(f"required role is not active: {role_id}")
    registered = set(role.get("atomic_skill_ids", []))
    selected = list(ROLE_SKILL_SELECTIONS[role_id])
    if not set(selected).issubset(registered):
        raise GTMCraftHandoffError(f"selected skills drifted from role registry: {role_id}")
    try:
        surface = surface_playbook(surface_id)
        edge_play = unconventional_edge_play(surface_id, business_model)
    except Exception as error:
        raise GTMCraftHandoffError(f"unsupported public surface: {surface_id}") from error
    if surface_id not in _surface_ids(role_id):
        raise GTMCraftHandoffError(
            f"role is not professionally bound to surface: {role_id}:{surface_id}"
        )
    payload = {
        "work_order_id": order_id,
        "stage": stage,
        "role_id": role_id,
        "selected_atomic_skill_ids": selected,
        "selected_professional_skill_card_ids": [
            f"{role_id}:{skill_id}" for skill_id in selected
        ],
        "required_professional_axis_ids": list(PROFESSIONAL_AXIS_IDS),
        "surface_id": surface_id,
        "surface_specialist_lens_ids": [
            f"{surface_id}:{lens_id}" for lens_id, _ in SURFACE_SPECIALIST_LENSES
        ],
        "surface_native_format_contract": surface["native_format_contract"],
        "surface_fail_closed_anti_pattern": surface["fail_closed_anti_pattern"],
        "hidden_algorithm_or_ranking_inference_allowed": False,
        "platform_selection_required_before_release": (
            surface["category"] == "holding_state"
        ),
        "unconventional_edge_play": edge_play,
        "input_binding_sha256": input_binding_sha256,
        "depends_on": list(depends_on),
        "channel": channel,
        "required_output_fields": list(output_contract),
        "acceptance_criteria": list(acceptance),
        "advisory_model_output_is_release_evidence": False,
    }
    payload["work_order_sha256"] = _digest(payload)
    return payload


def _producer_for_channel(channel: str, active_role_ids: set[str]) -> str:
    for role_id in _CHANNEL_PRODUCER_PREFERENCES.get(
        channel, ("senior_social_copywriter",)
    ):
        if role_id in active_role_ids:
            return role_id
    raise GTMCraftHandoffError(f"no active craft producer can own channel: {channel}")


def compile_gtm_craft_handoff_plan(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    territory: Mapping[str, Any],
    channels: Sequence[Mapping[str, Any]],
    creative_alpha_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Compile a typed craft graph; it is an execution contract, not role-play evidence."""

    team = creative_alpha_plan.get("gtm_team_capability_contract")
    if not isinstance(team, Mapping):
        raise GTMCraftHandoffError("creative-alpha plan lacks a GTM team contract")
    try:
        verify_gtm_team_capability_contract(team)
    except GTMTeamCapabilityError as error:
        raise GTMCraftHandoffError(f"invalid GTM team contract: {error}") from error
    active_rows = team["active_virtual_team"]["roles"]
    role_registry = {
        str(row["role_id"]): row for row in active_rows if isinstance(row, Mapping)
    }
    active_role_ids = set(role_registry)
    if len(channels) != 2:
        raise GTMCraftHandoffError("craft handoff requires exactly two channel executions")

    binding = {
        "strategy_id": strategy.strategy_id,
        "proof_claim_id": strategy.proof_claim_id,
        "proof_evidence_sha256": strategy.proof_evidence_sha256,
        "creative_alpha_sha256": creative_alpha_plan.get("content_sha256"),
        "team_contract_sha256": team.get("content_sha256"),
        "market_language_contract_sha256": creative_alpha_plan.get(
            "market_language_contract", {}
        ).get("content_sha256"),
        "territory_id": territory.get("territory_id"),
        "territory_variant_id": territory.get("variant_id"),
        "style_id": territory.get("assigned_style", {}).get("style_id"),
        "business_model": request.audience.business_model.value,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "primary_audience_role": request.audience_role,
        "distribution_platform": request.distribution_platform,
        "channels": [str(row.get("channel")) for row in channels],
    }
    input_binding_sha256 = _digest(binding)
    surface_id = normalize_surface_id(request.distribution_platform)
    orders: list[dict[str, Any]] = []

    diagnosis_specs = (
        (
            "research-mechanism",
            "market_intelligence_lead",
            ("dated_observation", "abstract_mechanism", "uncertainty", "copy_boundary"),
            ("separate observed signal from inference", "abstract mechanism without copying source expression"),
        ),
        (
            "audience-decision",
            "audience_research_lead",
            ("primary_role", "decision_or_use_moment", "tension_language", "falsifier"),
            ("one owner-confirmed primary role", "no committee-average or mass-market-average voice"),
        ),
        (
            "message-proof",
            "product_marketing_lead",
            ("position", "message_hierarchy", "approved_proof_role", "open_objection"),
            ("every promise binds approved evidence", "open objection remains visible"),
        ),
    )
    for order_id, role_id, output_fields, acceptance in diagnosis_specs:
        orders.append(
            _work_order(
                order_id=order_id,
                stage="diagnose",
                role_id=role_id,
                role_registry=role_registry,
                input_binding_sha256=input_binding_sha256,
                surface_id=surface_id,
                business_model=request.audience.business_model.value,
                output_contract=output_fields,
                acceptance=acceptance,
            )
        )

    orders.append(
        _work_order(
            order_id="creative-system",
            stage="direct",
            role_id="creative_strategy_director",
            role_registry=role_registry,
            input_binding_sha256=input_binding_sha256,
            surface_id=surface_id,
            business_model=request.audience.business_model.value,
            output_contract=("cultural_tension", "organizing_idea", "participation_mechanism", "share_trigger", "proof_role", "falsifier"),
            acceptance=("one ownable system, not a list of tactics", "territory keeps the approved proof spine", "style changes structure and voice without source imitation"),
            depends_on=("research-mechanism", "audience-decision", "message-proof"),
        )
    )

    producer_order_ids: list[str] = []
    for index, channel in enumerate(channels, start=1):
        channel_id = str(channel.get("channel"))
        producer = _producer_for_channel(channel_id, active_role_ids)
        order_id = f"craft-{index}-{channel_id}"
        producer_order_ids.append(order_id)
        orders.append(
            _work_order(
                order_id=order_id,
                stage="produce",
                role_id=producer,
                role_registry=role_registry,
                input_binding_sha256=input_binding_sha256,
                surface_id=surface_id,
                business_model=request.audience.business_model.value,
                channel=channel_id,
                output_contract=("native_format", "hook", "body", "exact_cta", "disclosure"),
                acceptance=("native opening and rhythm", "useful value appears before the ask", "no cross-platform copy-paste", "approved proof appears exactly once", "copy is speakable, specific and role-native"),
                depends_on=("creative-system",),
            )
        )

    review_specs = (
        (
            "review-platform",
            "platform_distribution_strategist",
            ("native_format_fit", "community_norm_fit", "cross_platform_difference", "timing_claim_boundary"),
            ("cannot swap unchanged across channels", "no universal timing or algorithm claim"),
        ),
        (
            "review-claims-rights",
            "brand_safety_claims_lead",
            ("claim_evidence_match", "rights_boundary", "policy_risk", "blocking_defects"),
            ("zero unsupported claims", "zero identity imitation or restricted-expression reuse"),
        ),
        (
            "review-language",
            "localization_cultural_editor",
            ("audience_register", "cultural_fit", "meaning_preservation", "language_defects"),
            ("language matches the primary role and locale", "humor and idiom preserve meaning and safety"),
        ),
    )
    for order_id, role_id, output_fields, acceptance in review_specs:
        orders.append(
            _work_order(
                order_id=order_id,
                stage="review",
                role_id=role_id,
                role_registry=role_registry,
                input_binding_sha256=input_binding_sha256,
                surface_id=surface_id,
                business_model=request.audience.business_model.value,
                output_contract=("decision", *output_fields, "repair_instruction"),
                acceptance=(*acceptance, "decision is exactly pass, revise or block", "reviewer is not either channel producer"),
                depends_on=tuple(producer_order_ids),
            )
        )

    payload: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "strategy_id": strategy.strategy_id,
        "territory_id": territory.get("territory_id"),
        "context_binding": binding,
        "input_binding_sha256": input_binding_sha256,
        "work_orders": orders,
        "work_order_count": len(orders),
        "stage_order": ["diagnose", "direct", "produce", "review", "repair_if_required", "named_human_release"],
        "producer_work_order_ids": producer_order_ids,
        "review_work_order_ids": ["review-platform", "review-claims-rights", "review-language"],
        "model_execution_contract": {
            "generation_calls_per_territory": 1,
            "independent_review_calls_per_territory": 3,
            "maximum_repair_calls_per_territory": 1,
            "post_repair_independent_review_calls_per_territory": 3,
            "maximum_total_model_calls_per_territory": 8,
            "review_decisions": list(_DECISIONS),
            "repair_only_on_revise": True,
            "block_is_fail_closed": True,
            "all_reviews_are_advisory_until_named_human_release": True,
        },
        "harness": {
            "closed_candidate_schema": True,
            "exact_claim_and_cta_binding": True,
            "platform_native_difference_gate": True,
            "originality_and_identity_imitation_gate": True,
            "maximum_revision_rounds": 1,
            "automatic_winner_selection": False,
            "automatic_publish_send_or_spend": False,
            "automatic_external_action_count": 0,
            "named_human_release_required": True,
            "platform_selection_required_before_named_human_release": (
                surface_id == "owner_platform_unspecified"
            ),
        },
        "truth_boundary": (
            "This graph assigns inspectable specialist work and review responsibilities. "
            "Compilation alone proves neither that a model executed each craft skill nor that "
            "the output achieved human preference, organic reach, conversion or revenue lift."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_gtm_craft_handoff_plan(payload, team_contract=team)
    return payload


def verify_gtm_craft_handoff_plan(
    payload: Mapping[str, Any], *, team_contract: Mapping[str, Any]
) -> None:
    if payload.get("schema") != PLAN_SCHEMA:
        raise GTMCraftHandoffError("craft handoff schema is invalid")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMCraftHandoffError("craft handoff digest is invalid")
    if payload.get("input_binding_sha256") != _digest(payload.get("context_binding")):
        raise GTMCraftHandoffError("craft handoff input binding is invalid")
    if payload.get("context_binding", {}).get("team_contract_sha256") != team_contract.get("content_sha256"):
        raise GTMCraftHandoffError("craft handoff team binding drifted")
    active_rows = team_contract.get("active_virtual_team", {}).get("roles", [])
    active = {str(row.get("role_id")): row for row in active_rows if isinstance(row, Mapping)}
    orders = payload.get("work_orders")
    if not isinstance(orders, list) or payload.get("work_order_count") != len(orders) or len(orders) != 9:
        raise GTMCraftHandoffError("craft handoff must contain exactly nine work orders")
    ids = [row.get("work_order_id") for row in orders if isinstance(row, Mapping)]
    if len(ids) != len(set(ids)):
        raise GTMCraftHandoffError("craft work-order identities are not unique")
    producers = {
        row.get("role_id") for row in orders if isinstance(row, Mapping) and row.get("stage") == "produce"
    }
    reviewers = {
        row.get("role_id") for row in orders if isinstance(row, Mapping) and row.get("stage") == "review"
    }
    if producers & reviewers:
        raise GTMCraftHandoffError("a producer cannot independently review its own work")
    for row in orders:
        if not isinstance(row, Mapping):
            raise GTMCraftHandoffError("craft work order is invalid")
        role_id = str(row.get("role_id"))
        role = active.get(role_id)
        if role is None:
            raise GTMCraftHandoffError(f"craft work order uses an inactive role: {role_id}")
        selected = row.get("selected_atomic_skill_ids")
        if not isinstance(selected, list) or not 4 <= len(selected) <= 5:
            raise GTMCraftHandoffError("craft work order skill selection is not bounded")
        if not set(selected).issubset(set(role.get("atomic_skill_ids", []))):
            raise GTMCraftHandoffError("craft work order selected an unregistered skill")
        expected_cards = [f"{role_id}:{skill_id}" for skill_id in selected]
        if row.get("selected_professional_skill_card_ids") != expected_cards:
            raise GTMCraftHandoffError("craft work order professional skill binding drifted")
        if row.get("required_professional_axis_ids") != list(PROFESSIONAL_AXIS_IDS):
            raise GTMCraftHandoffError("craft work order professional axes drifted")
        surface_id = row.get("surface_id")
        try:
            surface = surface_playbook(str(surface_id))
        except Exception as error:
            raise GTMCraftHandoffError("craft work order surface binding drifted") from error
        if surface_id not in _surface_ids(role_id):
            raise GTMCraftHandoffError("craft work order surface binding drifted")
        expected_lenses = [
            f"{surface_id}:{lens_id}" for lens_id, _ in SURFACE_SPECIALIST_LENSES
        ]
        if row.get("surface_specialist_lens_ids") != expected_lenses:
            raise GTMCraftHandoffError("craft work order surface specialist coverage drifted")
        if (
            row.get("surface_native_format_contract")
            != surface["native_format_contract"]
            or row.get("surface_fail_closed_anti_pattern")
            != surface["fail_closed_anti_pattern"]
            or row.get("hidden_algorithm_or_ranking_inference_allowed") is not False
            or row.get("platform_selection_required_before_release")
            is not (surface["category"] == "holding_state")
        ):
            raise GTMCraftHandoffError("craft work order surface contract drifted")
        expected_edge_play = unconventional_edge_play(
            str(surface_id), str(payload.get("context_binding", {}).get("business_model"))
        )
        if row.get("unconventional_edge_play") != expected_edge_play:
            raise GTMCraftHandoffError("craft work order edge-play binding drifted")
        sealed = dict(row)
        row_sha = sealed.pop("work_order_sha256", None)
        if row_sha != _digest(sealed):
            raise GTMCraftHandoffError("craft work-order digest is invalid")
        if row.get("input_binding_sha256") != payload.get("input_binding_sha256"):
            raise GTMCraftHandoffError("craft work-order input binding drifted")
        if row.get("advisory_model_output_is_release_evidence") is not False:
            raise GTMCraftHandoffError("advisory model output became release evidence")
    execution = payload.get("model_execution_contract")
    if (
        not isinstance(execution, Mapping)
        or execution.get("maximum_repair_calls_per_territory") != 1
        or execution.get("post_repair_independent_review_calls_per_territory") != 3
        or execution.get("maximum_total_model_calls_per_territory") != 8
    ):
        raise GTMCraftHandoffError("craft model-call or repair budget drifted")
    harness = payload.get("harness")
    if not isinstance(harness, Mapping) or harness.get("maximum_revision_rounds") != 1:
        raise GTMCraftHandoffError("craft repair loop is not bounded")
    for field in ("automatic_winner_selection", "automatic_publish_send_or_spend"):
        if harness.get(field) is not False:
            raise GTMCraftHandoffError(f"unsafe craft harness field: {field}")
    if harness.get("automatic_external_action_count") != 0 or harness.get("named_human_release_required") is not True:
        raise GTMCraftHandoffError("craft release boundary drifted")
    expected_platform_hold = (
        payload.get("context_binding", {}).get("distribution_platform")
        == "owner_platform_unspecified"
    )
    if (
        harness.get("platform_selection_required_before_named_human_release")
        is not expected_platform_hold
    ):
        raise GTMCraftHandoffError("craft platform-selection release boundary drifted")


def build_craft_review_requests(
    handoff_plan: Mapping[str, Any], candidate: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Build three source-bound advisory reviews; they never substitute for humans."""

    candidate_sha = candidate.get("candidate_content_sha256")
    if not isinstance(candidate_sha, str) or len(candidate_sha) != 64:
        raise GTMCraftHandoffError("candidate is not mechanically sealed")
    requests: list[dict[str, Any]] = []
    for order in handoff_plan.get("work_orders", []):
        if not isinstance(order, Mapping) or order.get("stage") != "review":
            continue
        output_contract = {
            "schema": REVIEW_SCHEMA,
            "work_order_id": order["work_order_id"],
            "territory_id": handoff_plan["territory_id"],
            "strategy_id": handoff_plan["strategy_id"],
            "candidate_content_sha256": candidate_sha,
            "decision": "pass | revise | block",
            "blocking_findings": [],
            "repair_instructions": [],
        }
        user = {
            "task": "Independently review the candidate only against this work order. Return one JSON object and no markdown.",
            "work_order": order,
            "candidate": candidate,
            "output_contract": output_contract,
            "decision_rules": {
                "pass": "every assigned acceptance criterion passes",
                "revise": "a bounded textual repair can close every finding without changing approved proof or CTA",
                "block": "rights, evidence, policy, identity imitation, or an irreparable strategic contradiction fails",
                "empty_findings_required_on_pass": True,
                "specific_findings_required_on_revise_or_block": True,
            },
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an independent GTM craft reviewer, not the producer. "
                    "Apply only the assigned skills and acceptance criteria. Do not reward "
                    "fluency, invent evidence, choose a winner, or authorize release."
                ),
            },
            {"role": "user", "content": _canonical(user)},
        ]
        request = {
            "request_id": f"{handoff_plan['territory_id']}:{order['work_order_id']}",
            "work_order_id": order["work_order_id"],
            "messages": messages,
            "maximum_output_tokens": 700,
            "temperature": 0.0,
            "request_sha256": _digest(messages),
        }
        requests.append(request)
    if len(requests) != 3:
        raise GTMCraftHandoffError("craft handoff lacks three independent review requests")
    return requests


def validate_craft_review(
    raw_content: str,
    *,
    handoff_plan: Mapping[str, Any],
    candidate: Mapping[str, Any],
    work_order_id: str,
) -> dict[str, Any]:
    try:
        review = json.loads(raw_content)
    except (TypeError, json.JSONDecodeError) as error:
        raise GTMCraftHandoffError("craft review must be one strict JSON object") from error
    if not isinstance(review, dict) or set(review) != _REVIEW_FIELDS:
        raise GTMCraftHandoffError("craft review fields do not match the closed contract")
    if review.get("schema") != REVIEW_SCHEMA:
        raise GTMCraftHandoffError("craft review schema is invalid")
    expected = {
        "work_order_id": work_order_id,
        "territory_id": handoff_plan.get("territory_id"),
        "strategy_id": handoff_plan.get("strategy_id"),
        "candidate_content_sha256": candidate.get("candidate_content_sha256"),
    }
    if any(review.get(field) != value for field, value in expected.items()):
        raise GTMCraftHandoffError("craft review binding drifted")
    decision = review.get("decision")
    if decision not in _DECISIONS:
        raise GTMCraftHandoffError("craft review decision is invalid")
    findings = review.get("blocking_findings")
    repairs = review.get("repair_instructions")
    if not isinstance(findings, list) or not isinstance(repairs, list):
        raise GTMCraftHandoffError("craft review findings are invalid")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 600 for item in (*findings, *repairs)):
        raise GTMCraftHandoffError("craft review contains an invalid finding")
    if decision == "pass" and (findings or repairs):
        raise GTMCraftHandoffError("passing craft review contains fabricated defects")
    if decision in {"revise", "block"} and not findings:
        raise GTMCraftHandoffError("failing craft review lacks a specific finding")
    if decision == "revise" and not repairs:
        raise GTMCraftHandoffError("revisable craft review lacks repair instructions")
    if decision == "block" and repairs:
        raise GTMCraftHandoffError("blocked craft review cannot request automated repair")
    sealed = dict(review)
    sealed["review_content_sha256"] = _digest(sealed)
    sealed["advisory_only"] = True
    sealed["human_release_granted"] = False
    return sealed
