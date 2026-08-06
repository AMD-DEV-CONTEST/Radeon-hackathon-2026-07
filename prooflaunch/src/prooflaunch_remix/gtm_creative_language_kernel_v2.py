from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


KERNEL_SCHEMA = "ProofLaunchGTMCreativeLanguageKernelV2"
EVALUATION_SCHEMA = "ProofLaunchGTMCreativeCampaignEvaluationV2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROOF_TYPES = ("first_party_observation", "first_party_test", "first_party_data", "first_party_tool", "product_behavior", "expert_judgment")
CREATIVE_TERRITORIES = (
    "documented_reality", "authority_proof", "challenger_humor", "useful_tool",
    "emotional_story", "cultural_participation", "product_spectacle",
)
NARRATIVE_STRUCTURES = ("suspense_proof", "transformation", "conflict_release", "myth_verification", "live_experiment", "world_building")
PLATFORMS = ("linkedin", "reddit", "x", "tiktok", "instagram", "youtube", "email", "search")
B2B_ROLES = ("engineering", "operations", "finance", "procurement", "executive", "channel_partner")
B2C_DIMENSIONS = ("identity", "usage_context", "maturity", "price_sensitivity", "lifecycle")
BRAND_MEMORY_FIELDS = ("language_code", "visual_code", "sound_code", "character_code", "interaction_code")
LEGITIMATE_GROWTH_PATTERNS = ("extreme_utility", "public_proof", "category_borrowing", "live_problem_solving", "transparent_tradeoff", "community_co_creation")
DECEPTION_FIELDS = ("fake_comments", "fake_scarcity", "fake_identity", "impersonation", "harassment", "dark_posting", "manipulation", "unsupported_competitor_attack")


class GTMCreativeLanguageError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_creative_language_kernel() -> dict[str, Any]:
    standards = {
        "linkedin": {"job": "earn professional reconsideration with a specific operator insight and inspectable proof", "must_have": ["point_of_view", "proof", "role_relevance"], "avoid": ["engagement_bait", "corporate_brochure"]},
        "reddit": {"job": "participate in the community context with transparent affiliation and useful detail", "must_have": ["community_context", "affiliation_disclosure", "useful_answer"], "avoid": ["drive_by_promotion", "vote_manipulation"]},
        "x": {"job": "compress a falsifiable idea into a useful conversational unit", "must_have": ["clear_claim", "evidence_link", "reply_value"], "avoid": ["empty_thread_hook", "hashtag_stuffing"]},
        "tiktok": {"job": "resolve a visual question quickly with native pacing and a visible payoff", "must_have": ["first_frame_question", "visual_proof", "payoff"], "avoid": ["recycled_horizontal_edit", "unsupported_shock_hook"]},
        "instagram": {"job": "create saveable or shareable visual meaning with brand-recognizable craft", "must_have": ["visual_system", "caption_job", "save_or_share_value"], "avoid": ["generic_stock_aesthetic", "caption_duplication"]},
        "youtube": {"job": "fulfil title and thumbnail expectation through sustained evidence", "must_have": ["promise_match", "evidence_sequence", "retention_payoff"], "avoid": ["bait_and_switch", "unearned_length"]},
        "email": {"job": "advance one consent-bound lifecycle decision", "must_have": ["trigger", "reader_value", "single_action"], "avoid": ["consent_assumption", "fake_personalization"]},
        "search": {"job": "satisfy query intent with extractable, source-backed answer depth", "must_have": ["intent_match", "direct_answer", "citations"], "avoid": ["keyword_stuffing", "doorway_content"]},
    }
    payload = {
        "schema": KERNEL_SCHEMA,
        "proof_object_types": list(PROOF_TYPES),
        "creative_territories": list(CREATIVE_TERRITORIES),
        "narrative_structures": list(NARRATIVE_STRUCTURES),
        "platform_writing_standards": standards,
        "b2b_role_adaptations": list(B2B_ROLES),
        "b2c_audience_dimensions": list(B2C_DIMENSIONS),
        "brand_memory_fields": list(BRAND_MEMORY_FIELDS),
        "legitimate_unconventional_growth_patterns": list(LEGITIMATE_GROWTH_PATTERNS),
        "deception_prohibitions": list(DECEPTION_FIELDS),
        "generic_language_detectors": {
            "empty_superlatives": ["revolutionary", "game-changing", "cutting-edge", "world-class", "next-level"],
            "ai_rhythm": ["in today's fast-paced", "not just .{0,60} it's", "imagine a world where"],
            "fake_urgency": ["act now", "last chance", "limited time"],
            "abstract_value": ["unlock potential", "transform your business", "elevate your brand", "supercharge growth"],
            "universal_cta": ["learn more", "get started", "click here"],
        },
        "truth_boundary": "The kernel enforces structure, evidence and integrity. Passing does not establish originality, human preference, market effect, or 4A quality.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_creative_language_kernel(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != KERNEL_SCHEMA or supplied != _digest(unsigned):
        raise GTMCreativeLanguageError("creative-language kernel seal is invalid")
    expected = {
        "proof_object_types": set(PROOF_TYPES), "creative_territories": set(CREATIVE_TERRITORIES),
        "narrative_structures": set(NARRATIVE_STRUCTURES), "b2b_role_adaptations": set(B2B_ROLES),
        "b2c_audience_dimensions": set(B2C_DIMENSIONS), "brand_memory_fields": set(BRAND_MEMORY_FIELDS),
        "legitimate_unconventional_growth_patterns": set(LEGITIMATE_GROWTH_PATTERNS), "deception_prohibitions": set(DECEPTION_FIELDS),
    }
    for field, values in expected.items():
        if set(payload.get(field, [])) != values:
            raise GTMCreativeLanguageError(f"kernel vocabulary drifted: {field}")
    if set(payload.get("platform_writing_standards", {})) != set(PLATFORMS):
        raise GTMCreativeLanguageError("eight platform writing standards are required")


def evaluate_creative_campaign(pack: Mapping[str, Any], kernel: Mapping[str, Any] | None = None) -> dict[str, Any]:
    kernel = kernel or build_creative_language_kernel()
    verify_creative_language_kernel(kernel)
    campaign_id = str(pack.get("campaign_id") or "")
    business_model = str(pack.get("business_model") or "")
    if not campaign_id or business_model not in {"b2b", "b2c"}:
        raise GTMCreativeLanguageError("campaign identity or business model is invalid")
    defects: list[str] = []
    proofs = pack.get("proof_objects")
    if not isinstance(proofs, list) or not proofs:
        defects.append("missing_first_party_proof_object")
    else:
        for proof in proofs:
            if proof.get("proof_type") not in PROOF_TYPES or not SHA256_RE.fullmatch(str(proof.get("content_sha256") or "")):
                defects.append("invalid_proof_object")
    territory = str(pack.get("creative_territory") or "")
    narrative = str(pack.get("narrative_structure") or "")
    if territory not in CREATIVE_TERRITORIES: defects.append("invalid_creative_territory")
    if narrative not in NARRATIVE_STRUCTURES: defects.append("invalid_narrative_structure")
    brand_memory = pack.get("brand_memory")
    if not isinstance(brand_memory, Mapping) or any(len(str(brand_memory.get(field) or "").strip()) < 8 for field in BRAND_MEMORY_FIELDS):
        defects.append("incomplete_long_term_brand_memory")
    growth_pattern = str(pack.get("growth_pattern") or "")
    if growth_pattern not in LEGITIMATE_GROWTH_PATTERNS: defects.append("unsupported_unconventional_growth_pattern")
    deception = pack.get("deception_controls")
    if not isinstance(deception, Mapping) or set(deception) != set(DECEPTION_FIELDS) or any(deception.values()):
        defects.append("deception_or_missing_deception_control")
    adaptations = pack.get("audience_adaptations")
    required_adaptations = B2B_ROLES if business_model == "b2b" else B2C_DIMENSIONS
    if not isinstance(adaptations, Mapping) or set(adaptations) != set(required_adaptations) or any(len(str(adaptations.get(key) or "").strip()) < 16 for key in required_adaptations):
        defects.append("incomplete_audience_adaptation")
    assets = pack.get("platform_assets")
    if not isinstance(assets, list) or not assets:
        defects.append("missing_platform_assets")
        assets = []
    detectors = kernel["generic_language_detectors"]
    for asset in assets:
        platform = str(asset.get("platform") or "")
        text = str(asset.get("text") or "").strip()
        if platform not in PLATFORMS or len(text) < 24:
            defects.append(f"invalid_platform_asset:{platform or 'unknown'}")
            continue
        lower = text.casefold()
        for detector, patterns in detectors.items():
            if any(re.search(pattern, lower) for pattern in patterns):
                defects.append(f"{detector}:{platform}")
        if asset.get("competitor_substitution_test_passed") is not True:
            defects.append(f"competitor_substitutable_copy:{platform}")
        standard = kernel["platform_writing_standards"][platform]
        present = set(asset.get("standard_elements_present") or [])
        missing = set(standard["must_have"]) - present
        if missing: defects.append(f"platform_standard_gap:{platform}:{','.join(sorted(missing))}")
    payload = {
        "schema": EVALUATION_SCHEMA,
        "campaign_id": campaign_id,
        "kernel_sha256": kernel["content_sha256"],
        "defects": sorted(set(defects)),
        "defect_count": len(set(defects)),
        "status": "creative_integrity_ready_for_human_review" if not defects else "creative_integrity_gap",
        "human_originality_craft_and_preference_review_required": True,
        "automatic_publish_or_spend_allowed": False,
        "observed_effect_claim_allowed": False,
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_creative_campaign_evaluation(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != EVALUATION_SCHEMA or supplied != _digest(unsigned):
        raise GTMCreativeLanguageError("creative campaign evaluation seal is invalid")
    if payload.get("defect_count") != len(payload.get("defects", [])):
        raise GTMCreativeLanguageError("creative defect aggregate drifted")
    if payload.get("automatic_publish_or_spend_allowed") is not False or payload.get("observed_effect_claim_allowed") is not False:
        raise GTMCreativeLanguageError("creative evaluation escaped authority or truth boundary")


__all__ = ["GTMCreativeLanguageError", "build_creative_language_kernel", "evaluate_creative_campaign", "verify_creative_campaign_evaluation", "verify_creative_language_kernel"]
