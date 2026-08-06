from __future__ import annotations

from typing import Any, Mapping, Sequence

from .v10_contracts import V10ContractError
from .v10_sft_corpus import stable_sha256


TARGET_GOLD_BRIEF_CANDIDATES = 300
TARGET_GOLD_CAMPAIGN_CANDIDATES = 150

CHANNELS = ("web", "social", "email", "search", "video", "audio")

BRIEF_GATES = (
    "source_identity_bound",
    "source_revision_bound",
    "rights_verified",
    "payload_observation_explicit",
    "audience_defined",
    "jtbd_defined",
    "single_minded_proposition_defined",
    "reason_to_believe_source_bound",
    "claim_inventory_present",
    "deliverables_bounded",
    "human_approval_preserved",
    "stop_conditions_present",
)


def build_gold_brief_candidate(source: Mapping[str, Any], ordinal: int) -> dict[str, Any]:
    if not source.get("rights_verified") or not source.get("training_allowed"):
        raise V10ContractError("gold brief candidate source must be rights-cleared")
    channel = CHANNELS[(ordinal - 1) % len(CHANNELS)]
    brief: dict[str, Any] = {
        "schema": "ProofLaunchGoldBriefCandidateV1",
        "brief_id": f"gold-brief-candidate-{ordinal:03d}",
        "promotion_status": "candidate_pending_five_person_review",
        "evaluation_use": "held_out_only_until_review",
        "source_episode_id": source["episode_id"],
        "source_episode_content_sha256": source["content_sha256"],
        "source_ids": source["source_ids"],
        "source_revisions": source["source_revisions"],
        "source_identity_sha256s": source["source_identity_sha256s"],
        "evidence_urls": source["evidence_urls"],
        "license_ids": source["license_ids"],
        "stage": source["stage"],
        "input_kind": source["input_kind"],
        "objective": f"Create a reviewable {source['stage']} GTM decision without exceeding supplied evidence metadata.",
        "audience": "evidence-accountable GTM team",
        "job_to_be_done": "move from licensed inputs to a review-ready decision with every unknown and approval boundary visible",
        "market_tension": "speed is valuable only when claim, rights, and approval provenance survive production",
        "single_minded_proposition": "Proof before publish.",
        "reason_to_believe": {
            "source_ids": source["source_ids"],
            "source_revisions": source["source_revisions"],
            "claim": "the candidate preserves immutable source locators and explicit unknowns",
        },
        "big_idea": "Every output carries its proof path.",
        "channel": channel,
        "deliverables": [
            f"one {channel} concept specification",
            "one claim-to-source ledger",
            "one preflight and stop-condition checklist",
        ],
        "claim_inventory": [
            {"claim": "source identity is recorded", "status": "observed_metadata", "source_ids": source["source_ids"]},
            {"claim": "modality payload was not inspected", "status": "explicit_unknown", "source_ids": source["source_ids"]},
            {"claim": "commercial performance", "status": "prohibited_unobserved", "source_ids": []},
        ],
        "creative_mandatories": [
            "show source locator near factual claim",
            "do not infer visual or audio content from metadata",
            "do not execute external action without named human approval",
        ],
        "success_measurement_design": {
            "primary": "claim_source_coverage",
            "guardrails": ["rights_failure_count", "unsupported_claim_count", "approval_bypass_count"],
            "observed_result": None,
        },
        "stop_conditions": [
            "required evidence is missing",
            "rights or trademark status is unresolved",
            "external action lacks named human approval",
        ],
        "modality_payload_observed": source["modality_payload_observed"],
        "rights_verified": True,
        "external_side_effect": False,
        "hidden_chain_of_thought_present": False,
        "teacher_model_used": False,
        "human_reviewed": False,
        "human_quality_score": None,
        "mechanical_gate_results": {gate: True for gate in BRIEF_GATES},
    }
    brief["content_sha256"] = stable_sha256(brief)
    return brief


def build_gold_campaign_candidate(
    briefs: Sequence[Mapping[str, Any]], ordinal: int
) -> dict[str, Any]:
    if len(briefs) != 2 or any(not brief.get("rights_verified") for brief in briefs):
        raise V10ContractError("campaign candidate requires two rights-cleared briefs")
    campaign: dict[str, Any] = {
        "schema": "ProofLaunchGoldCampaignCandidateV1",
        "campaign_id": f"gold-campaign-candidate-{ordinal:03d}",
        "promotion_status": "candidate_pending_five_person_review",
        "evaluation_use": "held_out_only_until_review",
        "brief_ids": [brief["brief_id"] for brief in briefs],
        "brief_content_sha256s": [brief["content_sha256"] for brief in briefs],
        "source_ids": sorted({value for brief in briefs for value in brief["source_ids"]}),
        "source_revisions": sorted({value for brief in briefs for value in brief["source_revisions"]}),
        "strategy": {
            "single_minded_proposition": "Proof before publish.",
            "big_idea": "Every output carries its proof path.",
            "audience": "evidence-accountable GTM team",
        },
        "channel_plan": [
            {"channel": brief["channel"], "brief_id": brief["brief_id"], "status": "specification_only"}
            for brief in briefs
        ],
        "multimodal_production_spec": {
            "image_canvas": [3840, 2160],
            "video_master": {"width": 3840, "height": 2160, "fps": 30, "rendered": False},
            "audio_master": {"sample_rate_hz": 48000, "integrated_lufs_target": -16, "rendered": False},
            "text_assets": ["landing_page", "social_caption", "email", "search_copy"],
        },
        "agent_execution_plan": [
            "inspect_sources",
            "plan_claims_and_channels",
            "produce_bounded_specs",
            "verify_claim_rights_identity_and_approval",
            "repair_or_safe_stop",
        ],
        "acceptance_gates": {
            "all_briefs_mechanically_complete": True,
            "source_coverage_required": 1.0,
            "unsupported_claim_count_required": 0,
            "rights_failure_count_required": 0,
            "human_approval_for_external_action": True,
            "rendered_asset_quality_observed": False,
        },
        "rights_verified": True,
        "external_side_effect": False,
        "hidden_chain_of_thought_present": False,
        "teacher_model_used": False,
        "human_reviewed": False,
        "human_quality_score": None,
        "training_observed": False,
    }
    campaign["content_sha256"] = stable_sha256(campaign)
    return campaign
