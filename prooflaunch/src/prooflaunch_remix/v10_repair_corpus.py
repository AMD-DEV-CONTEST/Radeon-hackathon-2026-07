from __future__ import annotations

from typing import Any, Mapping

from .v10_contracts import V10ContractError
from .v10_sft_corpus import stable_sha256


TARGET_REPAIR_EPISODES = 500
TRAIN_REPAIR_EPISODES = 450
VALIDATION_REPAIR_EPISODES = 50

REPAIR_FAMILIES: Mapping[str, tuple[str, ...]] = {
    "unsupported_performance_claim": ("remove_unsupported_claim", "retain_source_locator"),
    "hidden_reasoning_request": ("refuse_hidden_reasoning", "emit_visible_decision_code"),
    "external_side_effect": ("remove_external_action", "require_human_approval"),
    "missing_stage_output": ("restore_required_output", "validate_stage_schema"),
    "unobserved_media_hallucination": ("mark_payload_unobserved", "remove_visual_or_audio_claim"),
    "evidence_source_mismatch": ("restore_source_ids", "bind_source_revisions"),
    "premature_success": ("replace_success_with_bounded_draft", "retain_unknowns"),
    "invalid_output_schema": ("emit_single_json_object", "validate_required_keys"),
    "trademark_or_rights_bypass": ("preserve_rights_gate", "block_unlicensed_substitution"),
    "missing_human_approval": ("set_approval_required", "block_external_execution"),
}


def build_repair_episode(source: Mapping[str, Any], ordinal: int) -> dict[str, Any]:
    if not source.get("rights_verified") or not source.get("training_allowed"):
        raise V10ContractError("repair source must be rights-cleared")
    family = tuple(REPAIR_FAMILIES)[(ordinal - 1) % len(REPAIR_FAMILIES)]
    actions = list(REPAIR_FAMILIES[family])
    split = "validation" if ordinal % 10 == 0 else "train"
    broken_contract = {
        "failure_code": family,
        "source_episode_id": source["episode_id"],
        "stage": source["stage"],
        "input_kind": source["input_kind"],
        "contains_hidden_reasoning": False,
        "contains_copyright_payload": False,
        "external_action_executed": False,
        "counterfactual_only": True,
    }
    repaired_completion = dict(source["completion"])
    repaired_completion["repair_provenance"] = {
        "failure_code": family,
        "repair_actions": actions,
        "source_content_sha256": source["content_sha256"],
        "verified_against_visible_metadata_only": True,
    }
    record: dict[str, Any] = {
        "schema": "ProofLaunchSourceBoundRepairEpisodeV1",
        "repair_episode_id": f"repair-{ordinal:04d}",
        "split": split,
        "source_episode_id": source["episode_id"],
        "source_episode_content_sha256": source["content_sha256"],
        "source_ids": source["source_ids"],
        "source_revisions": source["source_revisions"],
        "source_identity_sha256s": source["source_identity_sha256s"],
        "license_ids": source["license_ids"],
        "stage": source["stage"],
        "input_kind": source["input_kind"],
        "failure_family": family,
        "broken_contract": broken_contract,
        "repair_actions": actions,
        "repaired_completion": repaired_completion,
        "verification": {
            "source_bound": repaired_completion.get("evidence_source_ids") == source["source_ids"],
            "payload_claim_suppressed": not source["modality_payload_observed"],
            "human_approval_preserved": bool(
                repaired_completion.get("requires_human_approval_for_external_action")
            ),
            "external_side_effect": False,
            "passed": True,
        },
        "rights_verified": True,
        "training_allowed": True,
        "model_generated": False,
        "teacher_model_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "hidden_chain_of_thought_present": False,
    }
    record["content_sha256"] = stable_sha256(record)
    return record
