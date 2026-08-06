#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_multimodal_production_contract_v2 import evaluate_multimodal_production, verify_multimodal_production_evaluation


ROOT = Path(__file__).resolve().parents[1]
H = "a" * 64


def fixture() -> dict:
    return {
        "bundle_id": "synthetic-multimodal-regression", "proof_objects": [{"proof_object_id": "proof-1", "content_sha256": H}], "strategy_decision_sha256": H,
        "dependency_ladder": [{"tier": tier, "provider_or_method": tier, "expected_quality": f"declared quality for {tier}", "known_limitations": [f"declared limitation for {tier}"]} for tier in ("flagship_cloud", "backup_cloud", "local", "deterministic_template", "human_edit")],
        "selected_dependency_tier": "local", "downgrade_disclosure": {"quality_delta_disclosed": True, "expected_differences": ["lower temporal detail than flagship cloud route"]},
        "review_gates": {role: "approved" for role in ("director", "editor", "copy_director", "industry_expert", "brand", "legal", "conversion")},
        "assets": [{
            "asset_id": "video-1", "modality": "video", "platform": "tiktok", "proof_object_ids": ["proof-1"],
            "video_spec": {"first_frame": "A rejected claim card", "visual_question": "Can the claim survive evidence review?", "evidence_sequence": ["claim", "source", "verdict"], "human_role": "skeptical operator", "sound_design": "quiet tactile interface", "reveal": "the missing evidence", "action_path": "run the same test"},
            "visual_qc": {axis: "pass" for axis in ("person", "product", "text", "hands", "materials", "physics", "lighting", "motion", "temporal_continuity")},
            "audio_qc": {axis: "pass" for axis in ("tone", "pronunciation", "accent_fit", "rhythm", "music_rights", "loudness", "audio_visual_sync")},
            "homogeneity_comparison": {"brand_archive_receipt_sha256s": [H], "competitor_receipt_sha256s": [H], "axes": {axis: {"distinct_enough": True, "review_note": "Distinct regression fixture"} for axis in ("composition", "color", "camera", "metaphor", "typography")}},
            "adaptation": {"master_proof_shared": True, "strategy_spine_shared": True, "platform_recomposed": True, "source_asset_crop_only": False},
            "provenance": {"source_receipt_sha256s": [H], "model_or_method": "deterministic regression renderer", "version": "v2", "prompt_sha256": H, "human_edits": ["timing review"], "rights_status": "synthetic regression fixture", "final_sha256": H},
        }],
    }


def main() -> int:
    payload = evaluate_multimodal_production(fixture()); verify_multimodal_production_evaluation(payload)
    output = ROOT / "evidence/v10/gtm-multimodal-production-contract-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "asset_count": payload["asset_count"], "status": payload["status"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
