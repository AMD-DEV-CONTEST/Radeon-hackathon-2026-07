from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .gtm_craft_handoff import ROLE_SKILL_SELECTIONS
from .gtm_team_capability_os import ROLE_REGISTRY


class GTMOmnichannelCraftError(ValueError):
    """A last-mile lane lacks specialist ownership, review independence, or safety."""


PLAYBOOK_SCHEMA = "ProofLaunchGTMOmnichannelCraftPlaybookV1"
JOB_BINDING_SCHEMA = "ProofLaunchGTMOmnichannelCraftJobBindingV1"


LANE_TEAM_BLUEPRINTS: dict[str, dict[str, tuple[str, ...] | str]] = {
    "cross_device_memory": {
        "director": "gtm_general_manager",
        "producers": ("agent_quality_learning_engineer", "growth_data_experimentation_lead"),
        "reviewers": ("brand_safety_claims_lead", "gtm_general_manager", "sales_enablement_revops_lead"),
    },
    "data_strategy_intelligence": {
        "director": "gtm_general_manager",
        "producers": ("market_intelligence_lead", "growth_data_experimentation_lead"),
        "reviewers": ("brand_safety_claims_lead", "gtm_general_manager", "agent_quality_learning_engineer"),
    },
    "content_scheduling_operations": {
        "director": "creative_strategy_director",
        "producers": ("platform_distribution_strategist", "lifecycle_crm_strategist"),
        "reviewers": ("brand_safety_claims_lead", "growth_data_experimentation_lead", "localization_cultural_editor"),
    },
    "image_generation_editing": {
        "director": "creative_strategy_director",
        "producers": ("art_design_director", "creative_strategy_director"),
        "reviewers": ("brand_safety_claims_lead", "platform_distribution_strategist", "localization_cultural_editor"),
    },
    "video_generation_production": {
        "director": "creative_strategy_director",
        "producers": ("short_video_director", "art_design_director", "audio_voice_producer"),
        "reviewers": ("brand_safety_claims_lead", "platform_distribution_strategist", "localization_cultural_editor"),
    },
    "audio_voice_music": {
        "director": "creative_strategy_director",
        "producers": ("audio_voice_producer", "creative_strategy_director"),
        "reviewers": ("brand_safety_claims_lead", "localization_cultural_editor", "platform_distribution_strategist"),
    },
    "text_content_generation": {
        "director": "creative_strategy_director",
        "producers": ("senior_social_copywriter", "longform_editorial_director"),
        "reviewers": ("brand_safety_claims_lead", "platform_distribution_strategist", "localization_cultural_editor"),
    },
    "product_marketing_analytics": {
        "director": "product_marketing_lead",
        "producers": ("growth_data_experimentation_lead", "sales_enablement_revops_lead"),
        "reviewers": ("brand_safety_claims_lead", "gtm_general_manager", "agent_quality_learning_engineer"),
    },
    "geo_ai_visibility": {
        "director": "product_marketing_lead",
        "producers": ("seo_geo_editor", "longform_editorial_director"),
        "reviewers": ("brand_safety_claims_lead", "platform_distribution_strategist", "localization_cultural_editor"),
    },
    "seo_operations": {
        "director": "product_marketing_lead",
        "producers": ("seo_geo_editor", "longform_editorial_director"),
        "reviewers": ("brand_safety_claims_lead", "platform_distribution_strategist", "localization_cultural_editor"),
    },
    "employee_agent_platforms": {
        "director": "gtm_general_manager",
        "producers": ("agent_quality_learning_engineer", "sales_enablement_revops_lead", "growth_data_experimentation_lead"),
        "reviewers": ("brand_safety_claims_lead", "gtm_general_manager", "audience_research_lead"),
    },
    "advertising_activation": {
        "director": "creative_strategy_director",
        "producers": ("demand_generation_lead", "senior_social_copywriter", "art_design_director"),
        "reviewers": ("brand_safety_claims_lead", "growth_data_experimentation_lead", "platform_distribution_strategist"),
    },
    "gtm_lifecycle_orchestration": {
        "director": "gtm_general_manager",
        "producers": ("product_marketing_lead", "senior_social_copywriter", "art_design_director", "short_video_director", "audio_voice_producer", "lifecycle_crm_strategist"),
        "reviewers": ("brand_safety_claims_lead", "growth_data_experimentation_lead", "localization_cultural_editor"),
    },
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _skills(role_id: str) -> list[str]:
    selected = list(ROLE_SKILL_SELECTIONS.get(role_id, ()))
    registered = set(ROLE_REGISTRY.get(role_id, {}).get("atomic_skill_ids", []))
    if not 4 <= len(selected) <= 5 or not set(selected).issubset(registered):
        raise GTMOmnichannelCraftError(f"invalid specialist skill projection: {role_id}")
    return selected


def _order(
    *,
    order_id: str,
    stage: str,
    role_id: str,
    input_sha256: str,
    output_name: str,
    acceptance: Sequence[str],
    depends_on: Sequence[str] = (),
) -> dict[str, Any]:
    order = {
        "work_order_id": order_id,
        "stage": stage,
        "role_id": role_id,
        "selected_atomic_skill_ids": _skills(role_id),
        "input_binding_sha256": input_sha256,
        "output_name": output_name,
        "acceptance_criteria": list(acceptance),
        "depends_on": list(depends_on),
        "model_output_is_execution_evidence": False,
        "model_output_is_human_preference_evidence": False,
    }
    order["work_order_sha256"] = _digest(order)
    return order


def compile_lane_craft_playbook(
    category_id: str,
    *,
    same_brief_task: str,
    effect_pk_question: str,
    quality_axes: Sequence[str],
    output_contract: Sequence[str],
    hard_gates: Sequence[str],
    failure_signals: Sequence[str],
) -> dict[str, Any]:
    blueprint = LANE_TEAM_BLUEPRINTS.get(category_id)
    if blueprint is None:
        raise GTMOmnichannelCraftError(f"unknown last-mile lane: {category_id}")
    director = str(blueprint["director"])
    producers = tuple(str(item) for item in blueprint["producers"])
    reviewers = tuple(str(item) for item in blueprint["reviewers"])
    if set(producers) & set(reviewers):
        raise GTMOmnichannelCraftError("lane producer/reviewer independence failed")
    binding = {
        "category_id": category_id,
        "same_brief_task": same_brief_task,
        "effect_pk_question": effect_pk_question,
        "quality_axes": list(quality_axes),
        "output_contract": list(output_contract),
        "hard_gates": list(hard_gates),
        "failure_signals": list(failure_signals),
    }
    input_sha = _digest(binding)
    orders = [
        _order(
            order_id="diagnose-market",
            stage="diagnose",
            role_id="market_intelligence_lead",
            input_sha256=input_sha,
            output_name="dated mechanism and comparable-case boundary",
            acceptance=("observation separated from inference", "no source expression copied"),
        ),
        _order(
            order_id="diagnose-audience",
            stage="diagnose",
            role_id="audience_research_lead",
            input_sha256=input_sha,
            output_name="one primary decision or use moment",
            acceptance=("one primary role", "tension and objection remain falsifiable"),
        ),
        _order(
            order_id="direct-system",
            stage="direct",
            role_id=director,
            input_sha256=input_sha,
            output_name="lane-level strategy and craft system",
            acceptance=("one coherent proof spine", "each output has a distinct job", "quality axes become production decisions"),
            depends_on=("diagnose-market", "diagnose-audience"),
        ),
    ]
    producer_ids: list[str] = []
    for index, output_name in enumerate(output_contract, start=1):
        order_id = f"produce-{index:02d}"
        producer_ids.append(order_id)
        orders.append(
            _order(
                order_id=order_id,
                stage="produce",
                role_id=producers[(index - 1) % len(producers)],
                input_sha256=input_sha,
                output_name=str(output_name),
                acceptance=("directly reviewable artifact or receipt", "source and identity binding preserved", "not a placeholder or plan-only substitution"),
                depends_on=("direct-system",),
            )
        )
    for index, reviewer in enumerate(reviewers, start=1):
        assigned_gates = [
            str(gate)
            for gate_index, gate in enumerate(hard_gates)
            if gate_index % len(reviewers) == index - 1
        ]
        orders.append(
            _order(
                order_id=f"review-{index:02d}",
                stage="review",
                role_id=reviewer,
                input_sha256=input_sha,
                output_name="independent pass/revise/block decision and located repair",
                acceptance=(
                    *assigned_gates,
                    "reviewer did not produce the artifact",
                    "failure is located against a named quality axis or hard gate",
                ),
                depends_on=tuple(producer_ids),
            )
        )
    payload: dict[str, Any] = {
        "schema": PLAYBOOK_SCHEMA,
        "category_id": category_id,
        "input_contract": binding,
        "input_binding_sha256": input_sha,
        "director_role_id": director,
        "producer_role_ids": list(producers),
        "reviewer_role_ids": list(reviewers),
        "stage_order": ["diagnose", "direct", "produce", "review", "repair_if_required", "review_again", "named_human_release"],
        "work_orders": orders,
        "work_order_count": len(orders),
        "selected_atomic_skill_assignment_count": sum(
            len(row["selected_atomic_skill_ids"]) for row in orders
        ),
        "review_loop": {
            "independent_reviewer_count": 3,
            "decision_vocabulary": ["pass", "revise", "block"],
            "maximum_revision_rounds": 1,
            "all_three_must_re_review_after_repair": True,
            "model_review_can_release_or_promote": False,
        },
        "harness": {
            "hard_gates": list(hard_gates),
            "failure_signals": list(failure_signals),
            "same_brief_required": True,
            "source_identity_and_rights_required": True,
            "automatic_publish_send_spend_or_strategy_mutation": False,
            "automatic_external_action_count": 0,
            "named_human_release_required": True,
        },
        "truth_boundary": (
            "This playbook converts a last-mile lane into specialist work orders and "
            "independent review topology. It does not prove the work was executed, preferred "
            "by humans, superior to a named product, or effective in market."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_lane_craft_playbook(payload)
    return payload


def verify_lane_craft_playbook(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != PLAYBOOK_SCHEMA:
        raise GTMOmnichannelCraftError("omnichannel craft playbook schema is invalid")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMOmnichannelCraftError("omnichannel craft playbook digest is invalid")
    if payload.get("input_binding_sha256") != _digest(payload.get("input_contract")):
        raise GTMOmnichannelCraftError("omnichannel craft input binding drifted")
    outputs = payload.get("input_contract", {}).get("output_contract", [])
    orders = payload.get("work_orders")
    expected_count = len(outputs) + 6
    if not isinstance(orders, list) or len(orders) != expected_count or payload.get("work_order_count") != expected_count:
        raise GTMOmnichannelCraftError("omnichannel craft work-order coverage drifted")
    producer_ids = set(payload.get("producer_role_ids", []))
    reviewer_ids = set(payload.get("reviewer_role_ids", []))
    if producer_ids & reviewer_ids or len(reviewer_ids) != 3:
        raise GTMOmnichannelCraftError("omnichannel producer/reviewer independence drifted")
    for order in orders:
        unsigned_order = dict(order)
        order_sha = unsigned_order.pop("work_order_sha256", None)
        if order_sha != _digest(unsigned_order):
            raise GTMOmnichannelCraftError("omnichannel craft work-order digest is invalid")
        if order.get("input_binding_sha256") != payload.get("input_binding_sha256"):
            raise GTMOmnichannelCraftError("omnichannel work-order input binding drifted")
        if order.get("model_output_is_execution_evidence") is not False or order.get("model_output_is_human_preference_evidence") is not False:
            raise GTMOmnichannelCraftError("omnichannel model output gained false authority")
        _skills(str(order.get("role_id")))
    review_loop = payload.get("review_loop", {})
    if review_loop.get("maximum_revision_rounds") != 1 or review_loop.get("all_three_must_re_review_after_repair") is not True or review_loop.get("model_review_can_release_or_promote") is not False:
        raise GTMOmnichannelCraftError("omnichannel repair/re-review loop drifted")
    harness = payload.get("harness", {})
    if harness.get("automatic_publish_send_spend_or_strategy_mutation") is not False or harness.get("automatic_external_action_count") != 0 or harness.get("named_human_release_required") is not True:
        raise GTMOmnichannelCraftError("omnichannel release boundary drifted")


def compile_craft_job_binding(
    playbook: Mapping[str, Any],
    *,
    job_id: str,
    reference_product: str,
    frozen_brief_sha256: str,
    candidate_dossier_sha256: str,
) -> dict[str, Any]:
    verify_lane_craft_playbook(playbook)
    payload: dict[str, Any] = {
        "schema": JOB_BINDING_SCHEMA,
        "job_id": job_id,
        "category_id": playbook["category_id"],
        "playbook_sha256": playbook["content_sha256"],
        "reference_product": reference_product,
        "frozen_brief_sha256": frozen_brief_sha256,
        "candidate_dossier_sha256": candidate_dossier_sha256,
        "same_brief_required": True,
        "named_product_baseline_authorized": False,
        "human_review_completed": False,
        "winner_selected": False,
        "automatic_external_action_count": 0,
    }
    payload["content_sha256"] = _digest(payload)
    verify_craft_job_binding(payload, playbook=playbook)
    return payload


def verify_craft_job_binding(
    payload: Mapping[str, Any], *, playbook: Mapping[str, Any] | None = None
) -> None:
    if payload.get("schema") != JOB_BINDING_SCHEMA:
        raise GTMOmnichannelCraftError("omnichannel craft job schema is invalid")
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMOmnichannelCraftError("omnichannel craft job digest is invalid")
    if playbook is not None:
        verify_lane_craft_playbook(playbook)
        if (
            payload.get("playbook_sha256") != playbook.get("content_sha256")
            or payload.get("category_id") != playbook.get("category_id")
        ):
            raise GTMOmnichannelCraftError("omnichannel craft job/playbook binding drifted")
    for field in ("frozen_brief_sha256", "candidate_dossier_sha256", "playbook_sha256"):
        value = payload.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise GTMOmnichannelCraftError(f"omnichannel craft job {field} is invalid")
    if payload.get("same_brief_required") is not True:
        raise GTMOmnichannelCraftError("omnichannel craft job lost same-Brief binding")
    for field in (
        "named_product_baseline_authorized",
        "human_review_completed",
        "winner_selected",
    ):
        if payload.get(field) is not False:
            raise GTMOmnichannelCraftError(f"omnichannel craft job escaped {field} boundary")
    if payload.get("automatic_external_action_count") != 0:
        raise GTMOmnichannelCraftError("omnichannel craft job enabled an external action")
