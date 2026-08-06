from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMMultimodalProductionEvaluationV2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MODALITIES = {"text", "image", "video", "audio", "landing_page"}
VIDEO_FIELDS = ("first_frame", "visual_question", "evidence_sequence", "human_role", "sound_design", "reveal", "action_path")
VISUAL_AXES = ("person", "product", "text", "hands", "materials", "physics", "lighting", "motion", "temporal_continuity")
AUDIO_AXES = ("tone", "pronunciation", "accent_fit", "rhythm", "music_rights", "loudness", "audio_visual_sync")
HOMOGENEITY_AXES = ("composition", "color", "camera", "metaphor", "typography")
REVIEW_ROLES = ("director", "editor", "copy_director", "industry_expert", "brand", "legal", "conversion")
DEPENDENCY_TIERS = ("flagship_cloud", "backup_cloud", "local", "deterministic_template", "human_edit")


class GTMMultimodalProductionError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _hashes(values: Any) -> bool:
    return isinstance(values, list) and bool(values) and all(SHA256_RE.fullmatch(str(value)) for value in values)


def evaluate_multimodal_production(bundle: Mapping[str, Any]) -> dict[str, Any]:
    bundle_id = str(bundle.get("bundle_id") or "")
    if not bundle_id:
        raise GTMMultimodalProductionError("bundle_id is required")
    defects: list[str] = []
    proof_objects = bundle.get("proof_objects")
    if not isinstance(proof_objects, list) or not proof_objects:
        defects.append("missing_bundle_proof_objects")
        proof_objects = []
    proof_ids = set()
    for proof in proof_objects:
        proof_id = str(proof.get("proof_object_id") or "") if isinstance(proof, Mapping) else ""
        if not proof_id or not SHA256_RE.fullmatch(str(proof.get("content_sha256") or "")):
            defects.append("invalid_bundle_proof_object")
        proof_ids.add(proof_id)
    if not SHA256_RE.fullmatch(str(bundle.get("strategy_decision_sha256") or "")):
        defects.append("missing_strategy_decision_hash")

    ladder = bundle.get("dependency_ladder")
    if not isinstance(ladder, list) or [row.get("tier") for row in ladder if isinstance(row, Mapping)] != list(DEPENDENCY_TIERS):
        defects.append("incomplete_or_unordered_dependency_ladder")
    else:
        for row in ladder:
            if not row.get("provider_or_method") or not row.get("expected_quality") or not row.get("known_limitations"):
                defects.append(f"incomplete_dependency_tier:{row.get('tier')}")
    selected_tier = str(bundle.get("selected_dependency_tier") or "")
    if selected_tier not in DEPENDENCY_TIERS:
        defects.append("invalid_selected_dependency_tier")
    downgrade = bundle.get("downgrade_disclosure")
    if selected_tier and selected_tier != "flagship_cloud":
        if not isinstance(downgrade, Mapping) or downgrade.get("quality_delta_disclosed") is not True or not downgrade.get("expected_differences"):
            defects.append("silent_quality_downgrade")

    review_gates = bundle.get("review_gates")
    if not isinstance(review_gates, Mapping) or set(review_gates) != set(REVIEW_ROLES):
        defects.append("incomplete_seven_role_review_gates")
        review_gates = {}
    elif any(value not in {"approved", "pending", "rejected"} for value in review_gates.values()):
        defects.append("invalid_review_gate_status")

    assets = bundle.get("assets")
    if not isinstance(assets, list) or not assets:
        defects.append("missing_multimodal_assets")
        assets = []
    seen_assets = set()
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "")
        modality = str(asset.get("modality") or "")
        platform = str(asset.get("platform") or "")
        if not asset_id or asset_id in seen_assets or modality not in MODALITIES or not platform:
            defects.append(f"invalid_asset_identity:{asset_id or 'unknown'}")
        seen_assets.add(asset_id)
        bound_proofs = set(map(str, asset.get("proof_object_ids") or []))
        if not bound_proofs or not bound_proofs.issubset(proof_ids):
            defects.append(f"asset_without_valid_proof:{asset_id}")
        if modality == "video":
            spec = asset.get("video_spec")
            if not isinstance(spec, Mapping) or any(not spec.get(field) for field in VIDEO_FIELDS) or not isinstance(spec.get("evidence_sequence"), list) or len(spec["evidence_sequence"]) < 2:
                defects.append(f"incomplete_video_plan:{asset_id}")
        visual_qc = asset.get("visual_qc")
        if modality in {"image", "video", "landing_page"}:
            if not isinstance(visual_qc, Mapping) or set(visual_qc) != set(VISUAL_AXES) or any(value not in {"pass", "not_applicable"} for value in visual_qc.values()):
                defects.append(f"incomplete_visual_continuity:{asset_id}")
        audio_qc = asset.get("audio_qc")
        if modality in {"video", "audio"}:
            if not isinstance(audio_qc, Mapping) or set(audio_qc) != set(AUDIO_AXES) or any(value not in {"pass", "not_applicable"} for value in audio_qc.values()):
                defects.append(f"incomplete_audio_qc:{asset_id}")
        comparison = asset.get("homogeneity_comparison")
        if not isinstance(comparison, Mapping) or not _hashes(comparison.get("brand_archive_receipt_sha256s")) or not _hashes(comparison.get("competitor_receipt_sha256s")):
            defects.append(f"missing_homogeneity_comparison:{asset_id}")
        else:
            axes = comparison.get("axes")
            if not isinstance(axes, Mapping) or set(axes) != set(HOMOGENEITY_AXES) or any(not isinstance(value, Mapping) or value.get("distinct_enough") is not True for value in axes.values()):
                defects.append(f"homogeneity_failure:{asset_id}")
        adaptation = asset.get("adaptation")
        if not isinstance(adaptation, Mapping) or adaptation.get("master_proof_shared") is not True or adaptation.get("strategy_spine_shared") is not True or adaptation.get("platform_recomposed") is not True or adaptation.get("source_asset_crop_only") is not False:
            defects.append(f"platform_copy_or_crop_adaptation:{asset_id}")
        provenance = asset.get("provenance")
        required_provenance = ("source_receipt_sha256s", "model_or_method", "version", "prompt_sha256", "human_edits", "rights_status", "final_sha256")
        if not isinstance(provenance, Mapping) or any(field not in provenance for field in required_provenance) or not _hashes(provenance.get("source_receipt_sha256s")) or not SHA256_RE.fullmatch(str(provenance.get("prompt_sha256") or "")) or not SHA256_RE.fullmatch(str(provenance.get("final_sha256") or "")):
            defects.append(f"incomplete_asset_provenance:{asset_id}")
    all_reviews_approved = bool(review_gates) and all(value == "approved" for value in review_gates.values())
    payload = {
        "schema": SCHEMA,
        "bundle_id": bundle_id,
        "asset_count": len(assets),
        "defects": sorted(set(defects)),
        "defect_count": len(set(defects)),
        "all_seven_reviews_approved": all_reviews_approved,
        "status": "multimodal_contract_ready_for_release_authorization" if not defects and all_reviews_approved else "multimodal_contract_gap_or_review_pending",
        "external_release_authorized": False,
        "observed_quality_or_effect_claim_allowed": False,
        "truth_boundary": "Passing proves required production evidence and reviews are present. It does not prove human preference, 4A craft, platform performance, or market effect.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_multimodal_production_evaluation(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMMultimodalProductionError("multimodal evaluation seal is invalid")
    if payload.get("defect_count") != len(payload.get("defects", [])):
        raise GTMMultimodalProductionError("multimodal defect aggregate drifted")
    if payload.get("external_release_authorized") is not False or payload.get("observed_quality_or_effect_claim_allowed") is not False:
        raise GTMMultimodalProductionError("multimodal evaluation escaped authority or truth boundary")


__all__ = ["GTMMultimodalProductionError", "evaluate_multimodal_production", "verify_multimodal_production_evaluation"]
