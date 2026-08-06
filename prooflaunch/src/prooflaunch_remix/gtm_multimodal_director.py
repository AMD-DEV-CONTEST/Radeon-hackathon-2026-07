from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMMultimodalDirectionReceiptV1"
IMAGE_SELECTION_SCHEMA = "ProofLaunchImageBestOfNReceiptV1"
_SHOT_FUNCTIONS = frozenset({"tension", "proof", "turn", "product_demonstration", "action"})


class MultimodalDirectorError(ValueError):
    """Multimodal direction is incomplete, ungrounded, or internally inconsistent."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def select_image_best_of_n(
    candidates: Sequence[Mapping[str, object]],
    *,
    claim_id: str,
    evidence_sha256: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise MultimodalDirectorError("image candidate_id is required")
        hard_findings: list[str] = []
        if candidate.get("identity_lock_passed") is not True:
            hard_findings.append("identity_lock_failed")
        if candidate.get("claim_text_ocr_passed") is not True:
            hard_findings.append("claim_text_ocr_failed")
        if candidate.get("rights_receipt_present") is not True:
            hard_findings.append("rights_receipt_missing")
        if candidate.get("claim_id") != claim_id or candidate.get("evidence_sha256") != evidence_sha256:
            hard_findings.append("evidence_binding_failed")
        score = candidate.get("creative_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
            hard_findings.append("creative_score_invalid")
            score = 0.0
        rows.append(
            {
                "candidate_id": candidate_id,
                "hard_gate_passed": not hard_findings,
                "hard_gate_findings": hard_findings,
                "creative_score": round(float(score), 6),
                "human_creative_review": None,
            }
        )
    eligible = [row for row in rows if row["hard_gate_passed"]]
    eligible.sort(key=lambda row: (-float(row["creative_score"]), str(row["candidate_id"])))
    selected = eligible[0]["candidate_id"] if eligible else None
    core: dict[str, Any] = {
        "schema": IMAGE_SELECTION_SCHEMA,
        "claim_id": claim_id,
        "evidence_sha256": evidence_sha256,
        "candidate_count": len(rows),
        "hard_gate_eligible_count": len(eligible),
        "mechanically_selected_candidate_id": selected,
        "candidates": rows,
        "human_creative_selection": None,
        "rendered_asset_publishable": False,
        "truth_boundary": "Mechanical selection occurs only after identity, text, rights and evidence gates; it does not establish taste or publishability.",
    }
    core["content_sha256"] = _digest(core)
    return core


def compile_multimodal_direction_receipt(
    *,
    strategy_id: str,
    campaign_id: str,
    brand_name: str,
    claim_id: str,
    evidence_sha256: str,
    customer_promise: str,
    call_to_action: str,
    creative_strategy_kernel: Mapping[str, object],
    video_brief: Mapping[str, object],
    audio_brief: Mapping[str, object],
) -> dict[str, Any]:
    territories = creative_strategy_kernel.get("creative_territories")
    if not isinstance(territories, list) or len(territories) < 3:
        raise MultimodalDirectorError("creative territories are required")
    visual_grammars = [
        {
            "territory_id": row["territory_id"],
            "composition": row["visual_grammar"]["composition"],
            "motion": row["visual_grammar"]["motion"],
            "forbidden": list(row["visual_grammar"]["forbidden"]),
            "color": "owner brand palette only; if absent, neutral proof-card palette pending human art direction",
            "material": "product-authentic surfaces and legible evidence cards; no decorative synthetic UI",
            "type": "owner brand type system or neutral accessible fallback pending license confirmation",
            "lens": "choose lens and depth only after product scale and platform crop are known",
        }
        for row in territories
    ]
    shots = video_brief.get("shot_list")
    if not isinstance(shots, list) or len(shots) < 4:
        raise MultimodalDirectorError("video brief requires at least four shots")
    shot_rows: list[dict[str, object]] = []
    for shot in shots:
        if not isinstance(shot, Mapping):
            raise MultimodalDirectorError("video shot must be an object")
        function = shot.get("function")
        if function not in _SHOT_FUNCTIONS:
            raise MultimodalDirectorError("every video shot needs one allowed communication function")
        shot_rows.append(
            {
                "order": shot.get("order"),
                "function": function,
                "visual_direction": shot.get("visual_direction"),
                "on_screen_copy": shot.get("on_screen_copy"),
                "proof_claim_id": shot.get("proof_claim_id"),
                "evidence_sha256": shot.get("evidence_sha256"),
            }
        )
    proof_shots = [row for row in shot_rows if row["function"] == "proof"]
    proof_binding_passed = bool(proof_shots) and all(
        row["proof_claim_id"] == claim_id and row["evidence_sha256"] == evidence_sha256
        for row in proof_shots
    )
    first = shot_rows[0]
    first_direction = str(first["visual_direction"] or "").casefold()
    first_copy = str(first["on_screen_copy"] or "")
    first_frame = {
        "promise_present": bool(first_copy.strip()),
        "visual_conflict_present": any(token in first_direction for token in ("contrast", "tension", "split", "before")),
        "product_relationship_present": any(token in first_direction for token in ("product", "owner-supplied", "interface", "packaging")),
        "three_second_duration_assumption": "shot_1_must_hold_0.0_to_3.0_seconds_in_platform_edit",
        "status": "production_brief_contract_only_render_unobserved",
    }
    first_frame["brief_gate_passed"] = all(
        first_frame[field]
        for field in ("promise_present", "visual_conflict_present", "product_relationship_present")
    )
    video_layers = {
        "narrative_script": [
            "surface the one growth tension",
            "turn the promise into an inspectable question",
            "show the evidence card and its limitation",
            "invite the unresolved objection",
            "offer one manual next action",
        ],
        "shot_script": shot_rows,
        "platform_edit_script": {
            "vertical_9_16": "0–3s promise/product tension; proof before midpoint; burned-in accessible captions; one CTA",
            "horizontal_16_9": "retain evidence reading time and source marker; no crop may remove claim qualification",
            "caption_safe_area_required": True,
            "render_review_required": True,
        },
    }
    audio_direction = {
        "communication_purpose": "make the claim legible, preserve uncertainty and leave space for the audience to inspect",
        "voice": audio_brief.get("voice_direction"),
        "music": audio_brief.get("music_direction"),
        "sound_effects": audio_brief.get("sfx_direction"),
        "mix": audio_brief.get("mix_spec"),
        "rights": audio_brief.get("rights_instructions"),
        "human_audio_director_pass": None,
    }
    cross_modal = {
        "claim_id_shared": proof_binding_passed,
        "cta_shared": call_to_action in [str(row.get("on_screen_copy") or "") for row in shot_rows],
        "brand_identity_lock_present": brand_name.casefold() in " ".join(str(item) for item in video_brief.get("identity_lock", [])).casefold(),
        "customer_promise_source": "owner_declared",
        "rendered_visual_checked": False,
        "rendered_audio_checked": False,
        "landing_page_render_checked": False,
        "human_cross_modal_review": None,
    }
    identity_lock = {
        "brand_name": brand_name,
        "owner_assets_only": True,
        "locked_elements": ["product_structure", "logo", "packaging", "interface", "critical_text"],
        "ocr_exact_match_required_for_claim_text": True,
        "perceptual_product_reference_required": True,
        "human_identity_review_required": True,
    }
    empty_best_of_n = select_image_best_of_n((), claim_id=claim_id, evidence_sha256=evidence_sha256)
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "strategy_id": strategy_id,
        "campaign_id": campaign_id,
        "visual_grammars": visual_grammars,
        "identity_lock": identity_lock,
        "image_best_of_n": empty_best_of_n,
        "video_layers": video_layers,
        "first_frame_three_second_gate": first_frame,
        "shot_function_coverage": sorted({str(row["function"]) for row in shot_rows}),
        "audio_direction": audio_direction,
        "cross_modal_consistency": cross_modal,
        "rendered_asset_count": 0,
        "rendered_asset_quality_observed": False,
        "human_multimodal_director_pass": None,
        "external_publish_executed": False,
        "truth_boundary": (
            "This receipt proves production-brief contracts and evidence continuity only. No image, video or audio render, "
            "identity match, readability, aesthetic preference or publishability is claimed until the actual media is reviewed."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_multimodal_direction_receipt(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise MultimodalDirectorError("multimodal direction receipt seal is invalid")
    if payload.get("rendered_asset_count") != 0 or payload.get("rendered_asset_quality_observed") is not False:
        raise MultimodalDirectorError("brief compilation cannot claim rendered-media evidence")
    if payload.get("human_multimodal_director_pass") is not None:
        raise MultimodalDirectorError("brief compilation cannot claim human direction approval")
    layers = payload.get("video_layers")
    if not isinstance(layers, Mapping) or not {"narrative_script", "shot_script", "platform_edit_script"}.issubset(layers):
        raise MultimodalDirectorError("three-layer video script is incomplete")
