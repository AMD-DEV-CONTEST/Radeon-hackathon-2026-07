from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .quality_contract import wilson_lower_bound


SCHEMA = "ProofLaunchGTMProductionQualityOperatingContractV1"
EVALUATION_SCHEMA = "ProofLaunchGTMProductionQualityEvaluationV1"

QUALITY_STATES = (
    "mechanically_ready",
    "human_publishable",
    "production_proven",
)

BLOCKING_DEFECT_CLASSES = (
    "unsupported_or_false_claim",
    "rights_or_provenance_violation",
    "platform_or_audience_mismatch",
    "wrong_or_broken_call_to_action",
    "brand_product_or_identity_drift",
    "unreadable_or_inaccessible_delivery",
)

REQUIRED_COPY_BIBLE_PLATFORMS = (
    "linkedin",
    "reddit",
    "x",
    "tiktok",
    "instagram",
    "youtube",
    "email",
    "seo_geo",
)

COPY_BIBLE_FIELDS = (
    "platform_job",
    "native_formats",
    "voice_rules",
    "hook_rules",
    "proof_rules",
    "cta_rules",
    "forbidden_patterns",
    "accessibility_rules",
)


class GTMProductionQualityContractError(ValueError):
    """Production-quality evidence is malformed or attempts an invalid promotion."""


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


def _bool(value: object) -> bool:
    return value is True


def _count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    if numerator > denominator:
        return None
    return numerator / denominator


def build_production_quality_contract() -> dict[str, Any]:
    """Return the immutable operating contract behind T001-T008."""

    core: dict[str, Any] = {
        "schema": SCHEMA,
        "version": 1,
        "north_star": {
            "name": "brief_to_observed_gtm_value",
            "type": "three-axis_vector_not_a_volume_score",
            "axes": [
                {
                    "metric": "time_to_first_human_publishable_asset_hours",
                    "direction": "minimize",
                    "observation_required": "qualified_human_release_decision",
                },
                {
                    "metric": "directly_publishable_rate",
                    "direction": "maximize",
                    "minimum": 0.90,
                    "observation_required": "qualified_human_review",
                },
                {
                    "metric": "qualified_conversion_rate",
                    "direction": "maximize",
                    "observation_required": "authorized_production_observation",
                },
            ],
            "anti_gaming_rule": (
                "Asset count, token count, platform count, impressions and mechanical test count "
                "cannot substitute for any North-Star axis. Missing observations remain null."
            ),
        },
        "quality_states": [
            {
                "state": "mechanically_ready",
                "meaning": "G0 passed; the exact artifact is reviewable but not approved for release.",
            },
            {
                "state": "human_publishable",
                "meaning": "G0-G1 passed; qualified humans found the exact artifact directly publishable.",
            },
            {
                "state": "production_proven",
                "meaning": (
                    "G0-G3 passed; the exact released artifact has authorized, pre-registered, "
                    "incremental production evidence."
                ),
            },
        ],
        "quality_gates": {
            "G0_contract": {
                "required_true": [
                    "artifact_contract_passed",
                    "rights_gate_passed",
                    "claim_evidence_gate_passed",
                    "platform_contract_passed",
                    "identity_gate_passed",
                    "accessibility_gate_passed",
                ],
                "blocking_defect_count": 0,
            },
            "G1_professional_editor": {
                "minimum_qualified_reviews": 5,
                "minimum_directly_publishable_rate": 0.90,
                "maximum_major_rework_rate": 0.10,
                "human_blocking_defect_count": 0,
            },
            "G2_same_brief_blind_pk": {
                "named_external_baseline_required": True,
                "source_hidden_review_required": True,
                "minimum_comparisons": 5,
                "minimum_candidate_preference_rate": 0.75,
                "minimum_wilson_lower_95_exclusive": 0.50,
            },
            "G3_production_effect": {
                "minimum_publication_receipts": 1,
                "minimum_authorized_observations": 1,
                "pre_registered_primary_metric_required": True,
                "registered_sample_floor_required": True,
                "successful_primary_decision_required": True,
                "incremental_design_gate_required": True,
                "attribution_integrity_required": True,
                "safety_regression_allowed": False,
            },
        },
        "directly_publishable_definition": (
            "A qualified editor can release the exact asset after only spelling, punctuation, "
            "link or formatting corrections; no strategy, hook, argument, shot, proof or CTA rewrite."
        ),
        "major_rework_definition": (
            "Any rewrite of strategy, audience, promise, hook, argument, evidence architecture, "
            "visual grammar, shot sequence, audio direction or CTA."
        ),
        "blocking_defect_classes": list(BLOCKING_DEFECT_CLASSES),
        "effect_metric_tree": {
            "diagnostic_only": ["impressions", "raw_reach", "views", "follower_count"],
            "awareness": ["qualified_attention_rate", "target_audience_completion_rate"],
            "consideration": ["evidence_engagement_rate", "qualified_return_visit_rate"],
            "demand": ["qualified_action_rate", "sales_accepted_lead_rate"],
            "acquisition": ["qualified_lead_rate", "verified_signup_rate"],
            "activation": ["activation_rate", "time_to_value"],
            "revenue": ["incremental_net_revenue", "incremental_contribution_margin"],
            "retention": ["retained_account_rate", "retained_user_rate"],
        },
        "promotion_rules": {
            "gates_are_monotonic": True,
            "missing_is_failure_not_zero": True,
            "model_judge_can_release": False,
            "automatic_external_publish": False,
            "automatic_budget_spend": False,
            "automatic_learning_promotion": False,
            "production_proven_requires_all_prior_gates": True,
        },
        "supporting_contracts": {
            "product_evidence_extractor": {
                "required_fields": [
                    "claim_id",
                    "claim_text",
                    "source_uri",
                    "source_sha256",
                    "rights_status",
                    "valid_at",
                    "release_scope",
                    "approved_by",
                ],
                "allowed_rights_status": ["owner_approved", "licensed", "public_measurement"],
            },
            "natural_breakout_admission": {
                "maximum_age_days": 180,
                "preferred_age_days": 90,
                "minimum_account_baseline_items": 10,
                "paid_distribution_status_must_be_known": True,
                "public_source_and_capture_hash_required": True,
            },
            "single_growth_tension": {
                "exactly_one_required": True,
                "required_fields": [
                    "audience",
                    "problem",
                    "business_constraint",
                    "evidence_ids",
                    "falsifier",
                    "primary_outcome_metric",
                ],
            },
            "platform_copy_bible": {
                "required_platforms": list(REQUIRED_COPY_BIBLE_PLATFORMS),
                "required_fields_per_platform": list(COPY_BIBLE_FIELDS),
                "copy_paste_across_platforms_allowed": False,
            },
        },
        "truth_boundary": (
            "This contract defines admissible evidence and promotion semantics. It does not itself "
            "prove that an artifact is publishable, superior, effective, causal, 4A-level or Top-1."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_production_quality_contract(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMProductionQualityContractError("production-quality contract seal is invalid")
    if tuple(row.get("state") for row in payload.get("quality_states", ())) != QUALITY_STATES:
        raise GTMProductionQualityContractError("production-quality states drifted")


def evaluate_quality_ladder(evidence: Mapping[str, object]) -> dict[str, Any]:
    """Evaluate G0-G3 without imputing missing human or production observations."""

    g0_fields = (
        "artifact_contract_passed",
        "rights_gate_passed",
        "claim_evidence_gate_passed",
        "platform_contract_passed",
        "identity_gate_passed",
        "accessibility_gate_passed",
    )
    g0_failures = [field for field in g0_fields if not _bool(evidence.get(field))]
    blocking_defects = _count(evidence.get("blocking_defect_count"))
    if blocking_defects != 0:
        g0_failures.append("blocking_defect_count_must_equal_zero")
    g0 = not g0_failures

    human_reviews = _count(evidence.get("qualified_review_count"))
    publishable = _count(evidence.get("directly_publishable_count"))
    major_rework = _count(evidence.get("major_rework_count"))
    human_blockers = _count(evidence.get("human_blocking_defect_count"))
    publishable_rate = _rate(publishable, human_reviews)
    major_rework_rate = _rate(major_rework, human_reviews)
    g1_checks = {
        "prior_gate": g0,
        "minimum_qualified_reviews": human_reviews is not None and human_reviews >= 5,
        "directly_publishable_rate": publishable_rate is not None and publishable_rate >= 0.90,
        "major_rework_rate": major_rework_rate is not None and major_rework_rate <= 0.10,
        "human_blocking_defects": human_blockers == 0,
    }
    g1 = all(g1_checks.values())

    comparisons = _count(evidence.get("blind_comparison_count"))
    preferences = _count(evidence.get("candidate_preferred_count"))
    preference_rate = _rate(preferences, comparisons)
    wilson = (
        wilson_lower_bound(preferences, comparisons)
        if preferences is not None
        and comparisons is not None
        and comparisons > 0
        and preferences <= comparisons
        else None
    )
    g2_checks = {
        "prior_gate": g1,
        "named_external_baseline": _bool(evidence.get("named_external_baseline_present")),
        "source_hidden_review": _bool(evidence.get("source_hidden_review")),
        "minimum_comparisons": comparisons is not None and comparisons >= 5,
        "candidate_preference_rate": preference_rate is not None and preference_rate >= 0.75,
        "wilson_lower_95": wilson is not None and wilson > 0.50,
    }
    g2 = all(g2_checks.values())

    publication_receipts = _count(evidence.get("publication_receipt_count"))
    observations = _count(evidence.get("authorized_observation_count"))
    observed_sample = _count(evidence.get("observed_sample_size"))
    registered_sample = _count(evidence.get("registered_minimum_sample"))
    g3_checks = {
        "prior_gate": g2,
        "publication_receipt": publication_receipts is not None and publication_receipts >= 1,
        "authorized_observation": observations is not None and observations >= 1,
        "pre_registered_primary_metric": _bool(evidence.get("primary_metric_pre_registered")),
        "registered_sample_floor": (
            observed_sample is not None
            and registered_sample is not None
            and registered_sample > 0
            and observed_sample >= registered_sample
        ),
        "successful_primary_decision": evidence.get("primary_metric_decision") == "success",
        "incremental_design_gate": _bool(evidence.get("incremental_design_gate_passed")),
        "attribution_integrity": _bool(evidence.get("attribution_integrity_passed")),
        "no_safety_regression": evidence.get("safety_regression_observed") is False,
    }
    g3 = all(g3_checks.values())

    current_state = "not_admitted"
    if g0:
        current_state = "mechanically_ready"
    if g1:
        current_state = "human_publishable"
    if g3:
        current_state = "production_proven"

    core: dict[str, Any] = {
        "schema": EVALUATION_SCHEMA,
        "current_state": current_state,
        "attained_states": {
            "mechanically_ready": g0,
            "human_publishable": g1,
            "production_proven": g3,
        },
        "gates": {
            "G0_contract": {"passed": g0, "checks": {field: field not in g0_failures for field in g0_fields}, "failures": g0_failures},
            "G1_professional_editor": {"passed": g1, "checks": g1_checks},
            "G2_same_brief_blind_pk": {"passed": g2, "checks": g2_checks},
            "G3_production_effect": {"passed": g3, "checks": g3_checks},
        },
        "observed_metrics": {
            "qualified_review_count": human_reviews,
            "directly_publishable_rate": publishable_rate,
            "major_rework_rate": major_rework_rate,
            "candidate_preference_rate": preference_rate,
            "candidate_preference_wilson_lower_95": wilson,
            "publication_receipt_count": publication_receipts,
            "authorized_observation_count": observations,
            "qualified_conversion_rate": _number(evidence.get("qualified_conversion_rate")),
            "time_to_first_human_publishable_asset_hours": _number(
                evidence.get("time_to_first_human_publishable_asset_hours")
            ),
        },
        "unobserved_metrics": [],
        "promotion_allowed": g3,
        "automatic_release_allowed": False,
        "automatic_learning_allowed": False,
        "truth_boundary": (
            "The current state is the highest monotonic gate supported by supplied evidence. "
            "Null metrics were not imputed and model output alone cannot promote a state."
        ),
    }
    core["unobserved_metrics"] = [
        key for key, value in core["observed_metrics"].items() if value is None
    ]
    core["content_sha256"] = _digest(core)
    return core


def evaluate_product_evidence_claims(claims: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    required = build_production_quality_contract()["supporting_contracts"]["product_evidence_extractor"]
    blockers: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip() or claim_id in seen:
            blockers.append({"claim": str(claim_id), "reason": "claim_id_missing_or_duplicate"})
        else:
            seen.add(claim_id)
        for field in required["required_fields"]:
            value = claim.get(field)
            if not isinstance(value, str) or not value.strip():
                blockers.append({"claim": str(claim_id or index), "reason": f"missing_{field}"})
        if claim.get("rights_status") not in required["allowed_rights_status"]:
            blockers.append({"claim": str(claim_id or index), "reason": "rights_status_not_releasable"})
        release_scope = claim.get("release_scope")
        if isinstance(release_scope, str) and release_scope.casefold() in {
            "draft_only",
            "internal_draft",
            "draft_only_pending_named_claim_approver",
        }:
            blockers.append({"claim": str(claim_id or index), "reason": "release_scope_is_draft_only"})
        source_uri = claim.get("source_uri")
        parsed_source = urlparse(source_uri) if isinstance(source_uri, str) else None
        if parsed_source is None or not parsed_source.scheme:
            blockers.append({"claim": str(claim_id or index), "reason": "source_uri_not_absolute"})
        valid_at = claim.get("valid_at")
        try:
            valid_time = (
                datetime.fromisoformat(str(valid_at).replace("Z", "+00:00"))
                if valid_at is not None
                else None
            )
        except ValueError:
            valid_time = None
        if valid_time is None or valid_time.tzinfo is None:
            blockers.append({"claim": str(claim_id or index), "reason": "valid_at_invalid"})
        source_sha = claim.get("source_sha256")
        if not isinstance(source_sha, str) or len(source_sha) != 64 or any(ch not in "0123456789abcdef" for ch in source_sha):
            blockers.append({"claim": str(claim_id or index), "reason": "source_sha256_invalid"})
    return {
        "passed": bool(claims) and not blockers,
        "claim_count": len(claims),
        "blocking_findings": blockers,
    }


def evaluate_organic_breakout_candidate(
    candidate: Mapping[str, object], *, observed_at: datetime
) -> dict[str, Any]:
    """Admit recent relative breakout evidence without equating public counters to causality."""

    failures: list[str] = []
    source_url = candidate.get("source_url")
    parsed = urlparse(source_url) if isinstance(source_url, str) else None
    if parsed is None or parsed.scheme != "https" or not parsed.hostname:
        failures.append("public_https_source_required")
    published_at = candidate.get("published_at")
    published: datetime | None = None
    if isinstance(published_at, str):
        try:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            published = None
    if (
        published is None
        or published.tzinfo is None
        or observed_at.tzinfo is None
        or published > observed_at
    ):
        failures.append("valid_timezone_aware_publication_time_required")
        age_days = None
    else:
        age_days = (observed_at - published).total_seconds() / 86400
        if age_days > 180:
            failures.append("candidate_older_than_180_days")
    baseline_count = _count(candidate.get("account_baseline_item_count"))
    if baseline_count is None or baseline_count < 10:
        failures.append("account_baseline_requires_at_least_10_items")
    attention = _number(candidate.get("item_attention"))
    median_attention = _number(candidate.get("baseline_median_attention"))
    interaction = _number(candidate.get("item_interactions"))
    median_interaction = _number(candidate.get("baseline_median_interactions"))
    relative_attention = (
        attention / median_attention
        if attention is not None and median_attention is not None and median_attention > 0
        else None
    )
    relative_interaction = (
        interaction / median_interaction
        if interaction is not None and median_interaction is not None and median_interaction > 0
        else None
    )
    if not (
        (relative_attention is not None and relative_attention >= 2.0)
        or (relative_interaction is not None and relative_interaction >= 1.5)
    ):
        failures.append("relative_breakout_threshold_not_met")
    paid_status = candidate.get("paid_distribution_status")
    if paid_status not in {"organic_only_verified", "none_observed_with_disclosure"}:
        failures.append("organic_distribution_not_supported")
    if candidate.get("rights_status") not in {"public_measurement", "owner_approved"}:
        failures.append("public_measurement_rights_missing")
    for field in ("source_sha256", "capture_sha256"):
        value = candidate.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)
        ):
            failures.append(f"{field}_invalid")
    return {
        "passed": not failures,
        "age_days": age_days,
        "preferred_90_day_window": age_days is not None and age_days <= 90,
        "relative_attention": relative_attention,
        "relative_interactions": relative_interaction,
        "failures": failures,
        "causal_growth_claim_allowed": False,
        "training_admitted": False,
        "human_strategy_abstraction_required": True,
    }


def evaluate_single_growth_tension(strategy: Mapping[str, object]) -> dict[str, Any]:
    tensions = strategy.get("growth_tensions")
    required = build_production_quality_contract()["supporting_contracts"]["single_growth_tension"]["required_fields"]
    if not isinstance(tensions, Sequence) or isinstance(tensions, (str, bytes)):
        tensions = []
    failures: list[str] = []
    if len(tensions) != 1:
        failures.append("exactly_one_growth_tension_required")
    elif not isinstance(tensions[0], Mapping):
        failures.append("growth_tension_must_be_an_object")
    else:
        tension = tensions[0]
        for field in required:
            value = tension.get(field)
            if field == "evidence_ids":
                if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
                    failures.append("growth_tension_missing_evidence_ids")
            elif not isinstance(value, str) or not value.strip():
                failures.append(f"growth_tension_missing_{field}")
    return {"passed": not failures, "tension_count": len(tensions), "failures": failures}


def evaluate_platform_copy_bible(copy_bible: Mapping[str, object]) -> dict[str, Any]:
    platforms = copy_bible.get("platforms")
    if not isinstance(platforms, Mapping):
        platforms = {}
    failures: list[str] = []
    fingerprints: set[str] = set()
    for platform in REQUIRED_COPY_BIBLE_PLATFORMS:
        spec = platforms.get(platform)
        if not isinstance(spec, Mapping):
            failures.append(f"missing_platform_{platform}")
            continue
        missing = [field for field in COPY_BIBLE_FIELDS if not spec.get(field)]
        failures.extend(f"{platform}_missing_{field}" for field in missing)
        if not missing:
            fingerprint = _digest({field: spec[field] for field in COPY_BIBLE_FIELDS})
            if fingerprint in fingerprints:
                failures.append(f"{platform}_duplicates_another_platform_contract")
            fingerprints.add(fingerprint)
    return {
        "passed": not failures,
        "required_platform_count": len(REQUIRED_COPY_BIBLE_PLATFORMS),
        "present_platform_count": sum(platform in platforms for platform in REQUIRED_COPY_BIBLE_PLATFORMS),
        "failures": failures,
    }
