from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .files import atomic_write_text


class OmnichannelActivationError(ValueError):
    """A selected creative territory could not be carried across the GTM system."""


SCHEMA = "ProofLaunchOmnichannelActivationPlanV1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANE_IDS = (
    "primary_channel",
    "secondary_channel",
    "landing_page",
    "lifecycle_email",
    "seo_geo_answer",
    "community_relay",
    "multimodal_production",
    "content_schedule",
    "effect_instrumentation",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _validate_content_addressed(payload: Mapping[str, Any], schema: str) -> None:
    if payload.get("schema") != schema:
        raise OmnichannelActivationError(f"{schema} input is missing")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned["content_sha256"] = None
    if (
        not isinstance(supplied, str)
        or not _SHA256.fullmatch(supplied)
        or supplied != _digest(unsigned)
    ):
        raise OmnichannelActivationError(f"{schema} content digest drifted")


def _draft_lane(lane_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "draft": dict(payload),
        "truth_status": "draft_pending_human_review",
        "human_release_required": True,
        "automatic_publish_enabled": False,
        "automatic_send_enabled": False,
        "automatic_spend_enabled": False,
        "external_action_executed": False,
    }


def compile_omnichannel_activation(
    admission: Mapping[str, Any],
    multimodal_compilation: Mapping[str, Any],
) -> dict[str, Any]:
    """Carry one human-selected creative system into nine governed GTM lanes."""

    _validate_content_addressed(
        admission, "ProofLaunchMultimodalProductionAdmissionV1"
    )
    _validate_content_addressed(
        multimodal_compilation, "ProofLaunchMultimodalSeedCompilationV1"
    )
    if (
        multimodal_compilation.get("multimodal_admission_sha256")
        != admission.get("content_sha256")
    ):
        raise OmnichannelActivationError(
            "multimodal compilation is not bound to the selected territory"
        )
    if not (
        admission.get("prompt_compilation_authorized") is True
        and admission.get("gpu_execution_authorized") is False
        and admission.get("spend_authorized") is False
        and admission.get("external_publish_authorized") is False
        and admission.get("effect_claim_eligible") is False
    ):
        raise OmnichannelActivationError("selection authority boundary is invalid")
    candidate = admission.get("selected_candidate")
    if not isinstance(candidate, Mapping):
        raise OmnichannelActivationError("selected candidate is missing")
    candidate_sha = candidate.get("candidate_content_sha256")
    unsigned_candidate = dict(candidate)
    unsigned_candidate.pop("candidate_content_sha256", None)
    if candidate_sha != _digest(unsigned_candidate):
        raise OmnichannelActivationError("selected candidate digest drifted")
    campaign_id = str(admission.get("campaign_id") or "").strip()
    strategy_id = str(admission.get("strategy_id") or "").strip()
    challenger_plan_sha256 = admission.get("challenger_plan_sha256")
    proof_claim_id = str(admission.get("proof_claim_id") or "").strip()
    if (
        not campaign_id
        or not strategy_id
        or not isinstance(challenger_plan_sha256, str)
        or not _SHA256.fullmatch(challenger_plan_sha256)
        or not proof_claim_id
        or candidate.get("strategy_id") != strategy_id
        or candidate.get("proof_claim_id") != proof_claim_id
    ):
        raise OmnichannelActivationError(
            "campaign, strategy, plan and proof identities are not bound"
        )
    channels = candidate.get("channels")
    proof_rows = candidate.get("factual_claims")
    if not isinstance(channels, list) or len(channels) != 2:
        raise OmnichannelActivationError("selected channels are incomplete")
    if (
        not isinstance(proof_rows, list)
        or len(proof_rows) != 1
        or not isinstance(proof_rows[0], str)
        or not proof_rows[0].strip()
    ):
        raise OmnichannelActivationError("selected proof is invalid")
    proof = proof_rows[0]
    idea = str(candidate.get("organizing_idea") or "").strip()
    tension = str(candidate.get("cultural_tension") or "").strip()
    mechanism = str(candidate.get("participation_mechanism") or "").strip()
    relay = str(candidate.get("share_trigger") or "").strip()
    falsifier = str(candidate.get("falsifier") or "").strip()
    proof_role = str(candidate.get("proof_role") or "").strip()
    if not all((idea, tension, mechanism, relay, falsifier, proof_role)):
        raise OmnichannelActivationError("selected creative system is incomplete")
    primary, secondary = channels
    if not all(isinstance(row, Mapping) for row in (primary, secondary)):
        raise OmnichannelActivationError("selected channel drafts are invalid")
    cta = str(primary.get("cta") or "").strip()
    if not cta or secondary.get("cta") != cta:
        raise OmnichannelActivationError("selected CTA binding drifted")
    stage_ids = [str(row.get("stage_id")) for row in multimodal_compilation["stages"]]
    if stage_ids != ["hero_image", "hero_video", "original_music", "speech"]:
        raise OmnichannelActivationError("multimodal stages are incomplete or reordered")

    lanes = [
        _draft_lane("primary_channel", dict(primary)),
        _draft_lane("secondary_channel", dict(secondary)),
        _draft_lane(
            "landing_page",
            {
                "headline": idea,
                "decision_tension": tension,
                "supporting_proof": proof,
                "participation_mechanism": mechanism,
                "call_to_action": cta,
            },
        ),
        _draft_lane(
            "lifecycle_email",
            {
                "subject": str(primary.get("hook") or ""),
                "preheader": proof_role,
                "body_blocks": [tension, proof, mechanism],
                "call_to_action": cta,
            },
        ),
        _draft_lane(
            "seo_geo_answer",
            {
                "question": "What evidence should a decision team inspect before advancing this offer?",
                "answer_blocks": [proof, proof_role, falsifier],
                "answer_status": "source_bound_draft",
            },
        ),
        _draft_lane(
            "community_relay",
            {
                "utility_object": idea,
                "participation_mechanism": mechanism,
                "voluntary_share_trigger": relay,
                "endorsement_required": False,
            },
        ),
        _draft_lane(
            "multimodal_production",
            {
                "compilation_sha256": multimodal_compilation["content_sha256"],
                "stage_ids": stage_ids,
                "all_execution_blocked": True,
            },
        ),
        _draft_lane(
            "content_schedule",
            {
                "slot_count": 7,
                "slots": [
                    {
                        "day": day,
                        "job": job,
                        "status": "pending_human_review",
                        "minimum_review_window_hours": 24,
                    }
                    for day, job in enumerate(
                        (
                            "publish_proof_object",
                            "surface_decision_tension",
                            "invite_participation",
                            "answer_search_objection",
                            "relay_useful_object",
                            "review_qualified_signals",
                            "human_decide_next_experiment",
                        ),
                        start=1,
                    )
                ],
            },
        ),
        _draft_lane(
            "effect_instrumentation",
            {
                "primary_metric": "qualified_evidence_interaction_rate",
                "secondary_metrics": [
                    "qualified_action_rate",
                    "voluntary_relay_rate",
                    "evidence_engagement_rate",
                    "complaint_rate",
                ],
                "creative_falsifier": falsifier,
                "candidate_decision": "human_review_after_preregistered_observation",
                "causal_revenue_claim_allowed": False,
            },
        ),
    ]
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "campaign_id": campaign_id,
        "strategy_id": strategy_id,
        "challenger_plan_sha256": challenger_plan_sha256,
        "multimodal_admission_sha256": admission["content_sha256"],
        "multimodal_compilation_sha256": multimodal_compilation["content_sha256"],
        "selected_territory_id": admission["selected_territory_id"],
        "selected_candidate_content_sha256": candidate_sha,
        "proof_claim_id": proof_claim_id,
        "approved_proof": proof,
        "lane_count": len(lanes),
        "lane_ids": list(_LANE_IDS),
        "lanes": lanes,
        "same_creative_system_across_lanes": True,
        "same_evidence_spine_across_lanes": True,
        "human_release_required": True,
        "automatic_strategy_mutation_enabled": False,
        "automatic_publish_enabled": False,
        "automatic_send_enabled": False,
        "automatic_spend_enabled": False,
        "external_actions_executed": 0,
        "effect_claim_eligible": False,
        "truth_boundary": (
            "This plan carries one human-selected, model-generated creative territory "
            "into nine source-bound GTM drafts. It does not execute media models, publish, "
            "send, spend, observe lift, prove revenue, establish 4A preference or Top-1 standing."
        ),
        "content_sha256": None,
    }
    receipt["content_sha256"] = _digest(receipt)
    verify_omnichannel_activation(receipt)
    return receipt


def verify_omnichannel_activation(payload: Mapping[str, Any]) -> None:
    _validate_content_addressed(payload, SCHEMA)
    if (
        not isinstance(payload.get("campaign_id"), str)
        or not str(payload.get("campaign_id")).strip()
        or not isinstance(payload.get("strategy_id"), str)
        or not str(payload.get("strategy_id")).strip()
        or not isinstance(payload.get("challenger_plan_sha256"), str)
        or not _SHA256.fullmatch(str(payload.get("challenger_plan_sha256")))
        or not isinstance(payload.get("proof_claim_id"), str)
        or not str(payload.get("proof_claim_id")).strip()
    ):
        raise OmnichannelActivationError("omnichannel identity binding is invalid")
    lanes = payload.get("lanes")
    if (
        payload.get("lane_count") != 9
        or payload.get("lane_ids") != list(_LANE_IDS)
        or not isinstance(lanes, list)
        or [row.get("lane_id") for row in lanes if isinstance(row, Mapping)]
        != list(_LANE_IDS)
    ):
        raise OmnichannelActivationError("omnichannel lane coverage is incomplete")
    for lane in lanes:
        if not isinstance(lane, Mapping) or not isinstance(lane.get("draft"), Mapping):
            raise OmnichannelActivationError("omnichannel lane draft is invalid")
        if not (
            lane.get("truth_status") == "draft_pending_human_review"
            and lane.get("human_release_required") is True
            and lane.get("automatic_publish_enabled") is False
            and lane.get("automatic_send_enabled") is False
            and lane.get("automatic_spend_enabled") is False
            and lane.get("external_action_executed") is False
        ):
            raise OmnichannelActivationError("an omnichannel lane escaped the harness")
    if not (
        payload.get("same_creative_system_across_lanes") is True
        and payload.get("same_evidence_spine_across_lanes") is True
        and payload.get("human_release_required") is True
        and payload.get("automatic_strategy_mutation_enabled") is False
        and payload.get("automatic_publish_enabled") is False
        and payload.get("automatic_send_enabled") is False
        and payload.get("automatic_spend_enabled") is False
        and payload.get("external_actions_executed") == 0
        and payload.get("effect_claim_eligible") is False
    ):
        raise OmnichannelActivationError("omnichannel authority boundary is invalid")


def compile_omnichannel_activation_files(
    admission_path: str | Path,
    multimodal_compilation_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    sources = [
        Path(path).expanduser().resolve(strict=True)
        for path in (admission_path, multimodal_compilation_path)
    ]
    if any(path.is_symlink() or not path.is_file() for path in sources):
        raise OmnichannelActivationError("compiler inputs must be real files")
    receipt = compile_omnichannel_activation(
        *[json.loads(path.read_text(encoding="utf-8")) for path in sources]
    )
    target = Path(output_path).expanduser().resolve()
    if target.exists():
        raise OmnichannelActivationError("refusing to overwrite an activation receipt")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(
        target,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    target.chmod(0o600)
    return receipt


__all__ = [
    "OmnichannelActivationError",
    "SCHEMA",
    "compile_omnichannel_activation",
    "compile_omnichannel_activation_files",
    "verify_omnichannel_activation",
]
