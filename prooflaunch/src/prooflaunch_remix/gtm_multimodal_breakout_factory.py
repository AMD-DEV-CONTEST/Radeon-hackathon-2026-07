from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .gtm_generative_execution_kernel import (
    GTMGenerativeExecutionKernelError,
    compile_generative_execution_kernel,
    verify_generative_execution_kernel,
)
from .gtm_named_capability_distillation import (
    GTMNamedCapabilityDistillationError,
    verify_named_capability_distillation,
)


SCHEMA = "ProofLaunchGTMMultimodalBreakoutFactoryV1"


class GTMMultimodalBreakoutFactoryError(ValueError):
    pass


TEXT_CATEGORIES = ("text_content_generation", "seo_operations", "geo_ai_visibility")
IMAGE_CATEGORIES = ("image_generation_editing",)
VIDEO_CATEGORIES = ("video_generation_production", "audio_voice_music")
OPERATING_CATEGORIES = (
    "cross_device_memory", "data_strategy_intelligence", "content_scheduling_operations",
    "product_marketing_analytics", "employee_agent_platforms", "advertising_activation",
    "gtm_lifecycle_orchestration",
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _category_index(distillation: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {row["category_id"]: row for row in distillation["categories"]}


def _stress_pack(index: Mapping[str, Mapping[str, Any]], category_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "category_id": category_id,
            "reference_products": list(index[category_id]["reference_products"]),
            "mechanisms_to_absorb": list(index[category_id]["mechanism_repertoire"]),
            "same_brief_task": "apply the named mechanisms to the current frozen owner brief under identical delivery constraints",
            "source_same_brief_task_sha256": _digest(index[category_id]["same_brief_task"]),
            "effect_pk_question": index[category_id]["effect_pk_question"],
            "quality_axes": list(index[category_id]["quality_axes"]),
            "pinned_oss_candidates": list(index[category_id]["pinned_oss_candidates"]),
            "copy_reference_expression": False,
        }
        for category_id in category_ids
    ]


def compile_multimodal_breakout_factory(
    brief: Mapping[str, Any],
    *,
    named_capability_distillation: Mapping[str, Any],
    learning_memory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        verify_named_capability_distillation(named_capability_distillation)
    except GTMNamedCapabilityDistillationError as error:
        raise GTMMultimodalBreakoutFactoryError(f"named capability distillation is invalid: {error}") from error
    try:
        kernel = compile_generative_execution_kernel(
            brief, candidate_count=24, learning_memory=learning_memory
        )
    except GTMGenerativeExecutionKernelError as error:
        raise GTMMultimodalBreakoutFactoryError(f"creative genome compilation failed: {error}") from error
    normalized = kernel["brief"]
    index = _category_index(named_capability_distillation)
    zero_budget = normalized["budget"] == "zero"
    operating_ids = tuple(category for category in OPERATING_CATEGORIES if not (zero_budget and category == "advertising_activation"))
    stress = {
        "text": _stress_pack(index, TEXT_CATEGORIES),
        "image": _stress_pack(index, IMAGE_CATEGORIES),
        "video": _stress_pack(index, VIDEO_CATEGORIES),
        "operations": _stress_pack(index, operating_ids),
    }
    quality_axes = sorted({
        axis
        for pack in stress.values()
        for category in pack
        for axis in category["quality_axes"]
    })
    candidates = []
    for rank, blueprint in enumerate(kernel["candidate_blueprints"][:3], 1):
        mandate = blueprint["creative_mandate"]
        campaign_spine = {
            "candidate_id": blueprint["candidate_id"],
            "genome_id": blueprint["genome_id"],
            "single_organizing_conflict": normalized["tension"],
            "single_audience_decision": normalized["decision_job"],
            "single_approved_proof": normalized["approved_proof"],
            "opening_job": mandate["opening_job"],
            "narrative_beats": mandate["narrative_beats"],
            "participation_job": mandate["participation_job"],
            "payoff_job": mandate["payoff_job"],
            "tone": mandate["tone"],
            "visual_direction": mandate["visual_direction"],
        }
        common = {
            "brief": normalized,
            "campaign_spine": campaign_spine,
            "forbidden": [
                "copy any named product output, interface or recognizable expression",
                "invent evidence, customer outcomes, rankings or organic effects",
                "flatten platform-native work into one reformatted master copy",
                "use engagement bait, fake participation, spam or undisclosed automation",
            ],
        }
        candidates.append({
            "territory_rank": rank,
            "candidate_id": blueprint["candidate_id"],
            "genome_id": blueprint["genome_id"],
            "campaign_spine": campaign_spine,
            "text_generation_request": {
                "adapter": "openai_compatible_chat_or_local_chat_model",
                "stress_pack": stress["text"],
                "input": common,
                "output_contract": {
                    "strategy_rationale": "one concrete audience decision and tension",
                    "platform_native_primary_copy": "publish-ready draft with first line, body, proof, participation and CTA",
                    "alternate_openings": 5,
                    "comment_or_reply_system": "first comment plus three useful response branches",
                    "seo_geo_derivatives": "one source-grounded search explainer and one answer-engine citation unit",
                    "claim_inventory": "every factual clause mapped to approved proof or marked hypothesis",
                },
            },
            "image_generation_request": {
                "adapter": "comfyui_flux_or_qwen_image_workflow",
                "stress_pack": stress["image"],
                "input": common,
                "output_contract": {
                    "key_visual": "one ownable visual metaphor that demonstrates the campaign conflict",
                    "deliverables": ["4:5 feed", "9:16 story", "16:9 editorial"],
                    "copy_overlay_plan": "render typography separately from the generative image when text fidelity is uncertain",
                    "identity_lock": "preserve owner-approved product, brand, people and evidence objects only",
                    "negative_constraints": "no stock-ad composition, generic gradient SaaS card, fake UI or invented logo",
                },
            },
            "video_generation_request": {
                "adapter": "comfyui_wan_or_ltx_video_workflow",
                "stress_pack": stress["video"],
                "input": common,
                "output_contract": {
                    "duration_seconds": "15-30",
                    "first_1500ms": "show the conflict or surprising proof action before explanation",
                    "shot_plan": "six materially different shots with camera, subject action, transition and evidence role",
                    "audio_plan": "voice, score and sound design must each serve a named narrative beat",
                    "captions": "platform-safe captions authored from the final approved transcript",
                    "delivery": ["2160x3840 vertical", "3840x2160 landscape"],
                    "continuity": "same organizing idea and proof as text/image; never a literal slideshow of the copy",
                },
            },
            "zero_budget_distribution_request": {
                "enabled": zero_budget,
                "paid_media_spend": 0 if zero_budget else None,
                "stress_pack": stress["operations"],
                "sequence": [
                    "publish the strongest native proof object only after named human release",
                    "seed to the smallest relevant audience cell where the decision tension is already active",
                    "answer substantive objections with new evidence utility rather than promotional repetition",
                    "turn qualified replies into the next content question and preserve provenance",
                    "on days two through seven, expand only the mechanism that passes the preregistered downstream metric",
                ],
                "organic_measurement": [
                    "qualified dwell or completion", "substantive reply rate", "save or useful relay rate",
                    "profile-to-product progression", "qualified conversion event", "negative feedback and policy guardrails",
                ],
                "automatic_publish": False,
                "automatic_outreach": False,
            },
            "production_status": "MODEL_EXECUTION_PENDING",
            "produced_asset_count": 0,
            "external_action_count": 0,
        })
    payload = {
        "schema": SCHEMA,
        "brief": normalized,
        "creative_kernel": kernel,
        "named_capability_distillation_sha256": named_capability_distillation["content_sha256"],
        "active_named_product_stress_count": sum(len(row["reference_products"]) for pack in stress.values() for row in pack),
        "active_capability_category_count": sum(len(pack) for pack in stress.values()),
        "active_quality_axes": quality_axes,
        "zero_budget_mode": zero_budget,
        "candidate_campaigns": candidates,
        "model_call_budget": {"text": 3, "image": 3, "video": 3, "total": 9},
        "coherence_gate": {
            "same_conflict_across_modalities": True,
            "same_approved_proof_across_modalities": True,
            "different_native_execution_per_modality": True,
            "three_distinct_genomes_required": True,
            "source_hidden_human_pk_required": True,
            "observed_organic_effect_required_for_breakout_claim": True,
        },
        "winner_selected": False,
        "produced_asset_count": 0,
        "external_action_count": 0,
        "truth_boundary": "This factory emits model-ready text, image, video and organic-distribution work orders under one campaign spine. It does not execute models, render media, publish, observe effects or prove superiority.",
    }
    payload["content_sha256"] = _digest(payload)
    verify_multimodal_breakout_factory(payload)
    return payload


def verify_multimodal_breakout_factory(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMMultimodalBreakoutFactoryError("multimodal breakout factory seal is invalid")
    try:
        verify_generative_execution_kernel(payload["creative_kernel"])
    except (KeyError, GTMGenerativeExecutionKernelError) as error:
        raise GTMMultimodalBreakoutFactoryError(f"creative kernel is invalid: {error}") from error
    candidates = payload.get("candidate_campaigns", [])
    if len(candidates) != 3 or len({row.get("genome_id") for row in candidates}) != 3:
        raise GTMMultimodalBreakoutFactoryError("factory must bind three distinct campaign genomes")
    if payload.get("model_call_budget", {}).get("total") != 9:
        raise GTMMultimodalBreakoutFactoryError("multimodal model-call budget drifted")
    if payload.get("winner_selected") is not False or payload.get("produced_asset_count") != 0 or payload.get("external_action_count") != 0:
        raise GTMMultimodalBreakoutFactoryError("factory overstated production or effects")
    if payload.get("zero_budget_mode") and any(
        row.get("zero_budget_distribution_request", {}).get("paid_media_spend") != 0
        for row in candidates
    ):
        raise GTMMultimodalBreakoutFactoryError("zero-budget factory introduced media spend")


__all__ = [
    "GTMMultimodalBreakoutFactoryError", "SCHEMA", "compile_multimodal_breakout_factory",
    "verify_multimodal_breakout_factory",
]
