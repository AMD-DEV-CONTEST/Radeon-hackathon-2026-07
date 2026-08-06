from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .gtm_organic_signal_sampling_standard import (
    B2B_VERTICALS,
    B2C_VERTICALS,
    PLATFORMS,
    SUBVERTICAL_REQUIREMENTS,
)
from .gtm_subvertical_ontology_v1 import build_ontology, scope_for_subvertical, verify_ontology


STANDARD_SCHEMA = "ProofLaunchGTMCaseEvidenceFunnelStandardV2"
COVERAGE_SCHEMA = "ProofLaunchGTMCaseEvidenceFunnelCoverageV2"
MIGRATION_SCHEMA = "ProofLaunchGTMCaseSeedMigrationQueueV2"


class GTMCaseEvidenceFunnelError(ValueError):
    """A case, audit, blueprint, or completion claim escaped the V2 truth contract."""


COMPANY_SCALE_QUOTAS = {"small": 70, "mid_market": 65, "enterprise_or_mass_brand": 65}
LIFECYCLE_QUOTAS = {"pre_pmf": 30, "launch": 50, "growth": 70, "mature": 50}
BUDGET_QUOTAS = {
    "zero_paid": 20,
    "low_budget": 50,
    "capital_efficient": 50,
    "mixed_budget": 50,
    "mature_scale": 30,
}
RECENCY_QUOTAS = {"three_to_six_months": 80, "six_to_twelve_months": 50, "twelve_to_twenty_four_months": 30, "historical_mechanism": 40}
OUTCOME_QUOTAS = {"recent_breakout": 60, "durable_repeat": 40, "failed_or_stalled": 40, "mature_control": 30, "turnaround": 30}
MARKET_QUOTAS = {
    "north_america": 50,
    "uk_ireland": 30,
    "europe_english": 35,
    "anz": 25,
    "singapore": 20,
    "hong_kong": 15,
    "southern_africa_english": 15,
    "multi_market": 10,
}

QUOTA_DIMENSIONS = {
    "company_scale": COMPANY_SCALE_QUOTAS,
    "lifecycle_state": LIFECYCLE_QUOTAS,
    "budget_tier": BUDGET_QUOTAS,
    "recency_bucket": RECENCY_QUOTAS,
    "outcome_type": OUTCOME_QUOTAS,
    "quota_market": MARKET_QUOTAS,
}

FUNNEL_TARGETS = {
    "structured_candidates": 200,
    "mechanism_deep_audits": 40,
    "outcome_cross_verifications": 10,
    "execution_case_blueprints": 5,
}

ALLOWED_ACCESS_METHODS = {
    "ordinary_public_page",
    "public_feed",
    "official_public_api",
    "operator_authorized_export",
    "user_provided_authorized_data",
}
ALLOWED_SOURCE_CLASSES = {
    "official_company",
    "official_platform",
    "official_filing",
    "award_body",
    "independent_media",
    "academic_or_research",
    "public_community",
    "first_party_analytics_export",
}
COST_COMPONENTS = (
    "paid_media",
    "personnel",
    "tools",
    "creators",
    "channel_fees",
    "production",
)
ALLOWED_COST_DISCLOSURE_STATUSES = {"known_zero", "disclosed", "bounded_estimate", "unknown"}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required_text(row: Mapping[str, Any], field: str, *, minimum: int = 2) -> str:
    value = row.get(field)
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise GTMCaseEvidenceFunnelError(f"{field} is missing or too thin")
    return value.strip()


def _required_list(row: Mapping[str, Any], field: str, *, minimum: int = 1) -> list[Any]:
    value = row.get(field)
    if not isinstance(value, list) or len(value) < minimum:
        raise GTMCaseEvidenceFunnelError(f"{field} requires at least {minimum} item(s)")
    return value


def _subvertical_registry() -> list[dict[str, Any]]:
    registry: list[dict[str, Any]] = []
    vertical_models = {**{name: "b2b" for name in B2B_VERTICALS}, **{name: "b2c" for name in B2C_VERTICALS}}
    for vertical, subverticals in SUBVERTICAL_REQUIREMENTS.items():
        sibling_ids = [f"{vertical_models[vertical]}.{vertical}.{value}" for value in subverticals]
        for subvertical in subverticals:
            subvertical_id = f"{vertical_models[vertical]}.{vertical}.{subvertical}"
            registry.append(
                {
                    "subvertical_id": subvertical_id,
                    "business_model": vertical_models[vertical],
                    "vertical": vertical,
                    "subvertical": subvertical,
                    **scope_for_subvertical(subvertical_id, sibling_ids),
                }
            )
    return registry


def build_case_evidence_funnel_standard() -> dict[str, Any]:
    registry = _subvertical_registry()
    ontology = build_ontology(registry)
    verify_ontology(ontology)
    payload: dict[str, Any] = {
        "schema": STANDARD_SCHEMA,
        "ontology_version": "81-subvertical-v1",
        "subvertical_count": len(registry),
        "subverticals": registry,
        "ontology_sha256": ontology["content_sha256"],
        "platform_contracts": list(PLATFORMS),
        "per_subvertical_funnel_targets": dict(FUNNEL_TARGETS),
        "global_funnel_targets": {
            key: value * len(registry) for key, value in FUNNEL_TARGETS.items()
        },
        "marginal_quotas_per_subvertical": {
            dimension: dict(quota) for dimension, quota in QUOTA_DIMENSIONS.items()
        },
        "quota_semantics": (
            "Each case receives exactly one bucket per marginal dimension. Quotas are independent marginals inside the same "
            "200 cases; they are not a 3×4×5×4×5×8 Cartesian requirement."
        ),
        "episode_identity": {
            "unit": "company + product + campaign_or_motion + primary_market + observed_start + observed_end",
            "cross_platform_mirrors_count_once": True,
            "different_year_market_or_mechanism_may_be_separate_when_time_and_motion_are_distinct": True,
        },
        "promotion_ladder": [
            "structured_candidate",
            "mechanism_deep_audited",
            "outcome_cross_verified",
            "execution_case_blueprint",
        ],
        "truth_contract": {
            "coverage_gap_is_required_when_any_target_or_marginal_quota_is_missing": True,
            "weak_related_duplicate_or_undisclosed_budget_backfill_forbidden": True,
            "historical_cases_are_mechanism_priors_not_current_platform_signal": True,
            "vendor_case_study_alone_cannot_prove_causality": True,
            "public_signal_role": "hypothesis_generation_only",
            "copy_voice_asset_reuse_allowed": False,
            "automatic_publish_spend_or_memory_promotion_allowed": False,
            "access_control_captcha_paywall_or_platform_restriction_bypass_allowed": False,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_evidence_funnel_standard(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != STANDARD_SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseEvidenceFunnelError("case evidence funnel standard seal is invalid")
    registry = payload.get("subverticals")
    if not isinstance(registry, list) or len(registry) != 81:
        raise GTMCaseEvidenceFunnelError("exactly 81 subverticals are required")
    ids = [row.get("subvertical_id") for row in registry if isinstance(row, Mapping)]
    if len(set(ids)) != 81:
        raise GTMCaseEvidenceFunnelError("subvertical IDs are missing or duplicated")
    if len(payload.get("platform_contracts", [])) != 12:
        raise GTMCaseEvidenceFunnelError("exactly 12 platform contracts are required")
    for dimension, quotas in payload.get("marginal_quotas_per_subvertical", {}).items():
        if dimension not in QUOTA_DIMENSIONS or sum(quotas.values()) != 200:
            raise GTMCaseEvidenceFunnelError(f"{dimension} marginal quota does not total 200")
    if payload.get("global_funnel_targets") != {
        key: value * 81 for key, value in FUNNEL_TARGETS.items()
    }:
        raise GTMCaseEvidenceFunnelError("global funnel target drifted")


def _verify_source_receipt(receipt: Mapping[str, Any], *, case_id: str) -> None:
    url = _required_text(receipt, "source_url", minimum=9)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise GTMCaseEvidenceFunnelError(f"{case_id} source_url must be a public HTTPS URL")
    if receipt.get("source_class") not in ALLOWED_SOURCE_CLASSES:
        raise GTMCaseEvidenceFunnelError(f"{case_id} has an unsupported source_class")
    if receipt.get("access_method") not in ALLOWED_ACCESS_METHODS:
        raise GTMCaseEvidenceFunnelError(f"{case_id} has an unsupported access_method")
    _required_text(receipt, "captured_at", minimum=10)
    digest = receipt.get("content_sha256")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise GTMCaseEvidenceFunnelError(f"{case_id} source receipt lacks a SHA-256")


def _verify_candidate(candidate: Mapping[str, Any], registry: set[str]) -> None:
    case_id = _required_text(candidate, "case_id", minimum=4)
    if candidate.get("status") != "structured_candidate":
        raise GTMCaseEvidenceFunnelError(f"{case_id} is not a structured candidate")
    if candidate.get("subvertical_id") not in registry:
        raise GTMCaseEvidenceFunnelError(f"{case_id} references an unknown subvertical")
    _required_text(candidate, "company", minimum=2)
    for field in (
        "product",
        "campaign_or_motion",
        "primary_audience",
        "observed_start",
        "observed_end",
        "episode_key",
        "mechanism_hypothesis",
        "result_summary",
        "resource_scope",
    ):
        _required_text(candidate, field, minimum=4)
    for dimension, quotas in QUOTA_DIMENSIONS.items():
        if candidate.get(dimension) not in quotas:
            raise GTMCaseEvidenceFunnelError(f"{case_id} has invalid {dimension}")
    platforms = _required_list(candidate, "platforms")
    allowed_platforms = {row["platform"] for row in PLATFORMS}
    if not set(platforms).issubset(allowed_platforms):
        raise GTMCaseEvidenceFunnelError(f"{case_id} references an unsupported platform")
    receipts = _required_list(candidate, "source_receipts")
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            raise GTMCaseEvidenceFunnelError(f"{case_id} contains an invalid source receipt")
        _verify_source_receipt(receipt, case_id=case_id)
    resource_costs = candidate.get("resource_costs")
    if not isinstance(resource_costs, Mapping) or set(resource_costs) != set(COST_COMPONENTS):
        raise GTMCaseEvidenceFunnelError(f"{case_id} must record all six resource cost components")
    receipt_hashes = {str(receipt["content_sha256"]) for receipt in receipts}
    for component in COST_COMPONENTS:
        cost = resource_costs.get(component)
        if not isinstance(cost, Mapping):
            raise GTMCaseEvidenceFunnelError(f"{case_id}.{component} cost record is invalid")
        disclosure_status = cost.get("disclosure_status")
        if disclosure_status not in ALLOWED_COST_DISCLOSURE_STATUSES:
            raise GTMCaseEvidenceFunnelError(f"{case_id}.{component} has invalid disclosure status")
        amount = cost.get("amount_usd")
        if disclosure_status == "unknown":
            if amount is not None:
                raise GTMCaseEvidenceFunnelError(f"{case_id}.{component} unknown cost carries a numeric amount")
        else:
            if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount < 0:
                raise GTMCaseEvidenceFunnelError(f"{case_id}.{component} disclosed cost lacks a nonnegative amount")
            if disclosure_status == "known_zero" and amount != 0:
                raise GTMCaseEvidenceFunnelError(f"{case_id}.{component} known_zero cost is not zero")
        evidence_hashes = cost.get("evidence_receipt_sha256s")
        if not isinstance(evidence_hashes, list) or not set(map(str, evidence_hashes)).issubset(receipt_hashes):
            raise GTMCaseEvidenceFunnelError(f"{case_id}.{component} cost evidence is not bound to source receipts")
        _required_text(cost, "notes", minimum=8)
    if candidate.get("budget_tier") == "zero_paid" and resource_costs["paid_media"].get("disclosure_status") != "known_zero":
        raise GTMCaseEvidenceFunnelError(f"{case_id} zero_paid classification lacks known-zero paid media evidence")
    if any(
        resource_costs[component].get("disclosure_status") == "known_zero"
        for component in COST_COMPONENTS if component != "paid_media"
    ):
        raise GTMCaseEvidenceFunnelError(f"{case_id} treats non-media labor or production as automatically free")
    if candidate.get("copy_or_voice_reuse_allowed") is not False:
        raise GTMCaseEvidenceFunnelError(f"{case_id} allows source copy or voice reuse")
    quota_credit = candidate.get("quota_credit")
    if quota_credit not in {0, 1}:
        raise GTMCaseEvidenceFunnelError(f"{case_id} has invalid quota credit")
    budget_status = candidate.get("budget_quota_status")
    budget_hashes = candidate.get("budget_classification_evidence_receipt_sha256s")
    if not isinstance(budget_hashes, list) or not set(map(str, budget_hashes)).issubset(receipt_hashes):
        raise GTMCaseEvidenceFunnelError(f"{case_id} budget classification evidence is invalid")
    if quota_credit == 1:
        if budget_status != "source_bound" or not budget_hashes:
            raise GTMCaseEvidenceFunnelError(f"{case_id} received quota credit without source-bound budget evidence")
    elif budget_status != "evidence_gap" or budget_hashes:
        raise GTMCaseEvidenceFunnelError(f"{case_id} zero-credit budget state is inconsistent")


def _verify_mechanism_audit(audit: Mapping[str, Any], case_ids: set[str]) -> None:
    audit_id = _required_text(audit, "audit_id", minimum=4)
    if audit.get("status") != "mechanism_deep_audited" or audit.get("case_id") not in case_ids:
        raise GTMCaseEvidenceFunnelError(f"{audit_id} is not attached to a valid candidate")
    for field in (
        "problem",
        "insight",
        "strategy",
        "creative_system",
        "distribution",
        "conversion_path",
        "resource_inputs",
        "brand_advantage",
        "competitive_alternative_explanation",
        "nontransferable_conditions",
    ):
        _required_text(audit, field, minimum=12)
    _required_list(audit, "evidence_receipt_sha256s", minimum=1)
    if audit.get("human_review_status") != "approved_for_mechanism_research":
        raise GTMCaseEvidenceFunnelError(f"{audit_id} lacks mechanism human review")


def _verify_outcome_audit(
    audit: Mapping[str, Any], case_ids: set[str], mechanism_by_id: Mapping[str, Mapping[str, Any]]
) -> None:
    audit_id = _required_text(audit, "outcome_audit_id", minimum=4)
    mechanism_id = audit.get("mechanism_audit_id")
    if audit.get("status") != "outcome_cross_verified" or mechanism_id not in mechanism_by_id:
        raise GTMCaseEvidenceFunnelError(f"{audit_id} lacks a valid mechanism audit")
    if audit.get("case_id") not in case_ids or audit.get("case_id") != mechanism_by_id[mechanism_id].get("case_id"):
        raise GTMCaseEvidenceFunnelError(f"{audit_id} case lineage is invalid")
    for field in ("business_outcome", "baseline", "measurement_window", "attribution_method", "confidence_grade"):
        _required_text(audit, field, minimum=4)
    surfaces = _required_list(audit, "independent_evidence_surfaces", minimum=2)
    domains = {urlparse(str(surface.get("source_url", ""))).netloc for surface in surfaces if isinstance(surface, Mapping)}
    classes = {surface.get("source_class") for surface in surfaces if isinstance(surface, Mapping)}
    if len(domains) < 2 or len(classes) < 2:
        raise GTMCaseEvidenceFunnelError(f"{audit_id} does not have two independent evidence surfaces")
    if audit.get("causal_claim_allowed") is True and audit.get("attribution_method") not in {
        "randomized_holdout", "geo_holdout", "time_holdout", "matched_control"
    }:
        raise GTMCaseEvidenceFunnelError(f"{audit_id} overstates causality")


def _verify_blueprint(
    blueprint: Mapping[str, Any], case_ids: set[str], outcome_by_id: Mapping[str, Mapping[str, Any]]
) -> None:
    blueprint_id = _required_text(blueprint, "blueprint_id", minimum=4)
    outcome_id = blueprint.get("outcome_audit_id")
    if blueprint.get("status") != "execution_case_blueprint" or outcome_id not in outcome_by_id:
        raise GTMCaseEvidenceFunnelError(f"{blueprint_id} lacks a valid outcome audit")
    if blueprint.get("case_id") not in case_ids or blueprint.get("case_id") != outcome_by_id[outcome_id].get("case_id"):
        raise GTMCaseEvidenceFunnelError(f"{blueprint_id} case lineage is invalid")
    for field in (
        "applicability",
        "proof_object",
        "primary_channel",
        "reinforcing_channel",
        "measurement_chain",
        "kill_rule",
        "forbidden_copy_boundary",
    ):
        _required_text(blueprint, field, minimum=4)
    _required_list(blueprint, "execution_steps", minimum=4)
    _required_list(blueprint, "platform_adaptations", minimum=2)
    if blueprint.get("automatic_publish_or_spend_allowed") is not False:
        raise GTMCaseEvidenceFunnelError(f"{blueprint_id} enables external action")


def compile_case_evidence_funnel_coverage(
    standard: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    mechanism_audits: Sequence[Mapping[str, Any]],
    outcome_audits: Sequence[Mapping[str, Any]],
    blueprints: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    verify_case_evidence_funnel_standard(standard)
    registry_rows = standard["subverticals"]
    registry = {row["subvertical_id"] for row in registry_rows}
    candidate_ids: set[str] = set()
    all_candidate_ids: set[str] = set()
    episode_keys: set[str] = set()
    cases_by_subvertical: dict[str, list[Mapping[str, Any]]] = {key: [] for key in registry}
    for candidate in candidates:
        _verify_candidate(candidate, registry)
        case_id = str(candidate["case_id"])
        episode_key = str(candidate["episode_key"])
        if case_id in all_candidate_ids or episode_key in episode_keys:
            raise GTMCaseEvidenceFunnelError(f"duplicate case or cross-platform episode: {case_id}")
        all_candidate_ids.add(case_id)
        episode_keys.add(episode_key)
        if candidate.get("quota_credit") == 1:
            candidate_ids.add(case_id)
            cases_by_subvertical[str(candidate["subvertical_id"])].append(candidate)

    mechanism_by_id: dict[str, Mapping[str, Any]] = {}
    for audit in mechanism_audits:
        _verify_mechanism_audit(audit, candidate_ids)
        audit_id = str(audit["audit_id"])
        if audit_id in mechanism_by_id:
            raise GTMCaseEvidenceFunnelError(f"duplicate mechanism audit: {audit_id}")
        mechanism_by_id[audit_id] = audit
    outcome_by_id: dict[str, Mapping[str, Any]] = {}
    for audit in outcome_audits:
        _verify_outcome_audit(audit, candidate_ids, mechanism_by_id)
        audit_id = str(audit["outcome_audit_id"])
        if audit_id in outcome_by_id:
            raise GTMCaseEvidenceFunnelError(f"duplicate outcome audit: {audit_id}")
        outcome_by_id[audit_id] = audit
    blueprint_by_id: dict[str, Mapping[str, Any]] = {}
    for blueprint in blueprints:
        _verify_blueprint(blueprint, candidate_ids, outcome_by_id)
        blueprint_id = str(blueprint["blueprint_id"])
        if blueprint_id in blueprint_by_id:
            raise GTMCaseEvidenceFunnelError(f"duplicate execution blueprint: {blueprint_id}")
        blueprint_by_id[blueprint_id] = blueprint

    mechanism_cases = {str(row["case_id"]) for row in mechanism_audits}
    outcome_cases = {str(row["case_id"]) for row in outcome_audits}
    blueprint_cases = {str(row["case_id"]) for row in blueprints}
    rows: list[dict[str, Any]] = []
    for registry_row in registry_rows:
        subvertical_id = registry_row["subvertical_id"]
        cases = cases_by_subvertical[subvertical_id]
        case_ids = {str(case["case_id"]) for case in cases}
        observed_quotas = {
            dimension: dict(sorted(Counter(str(case[dimension]) for case in cases).items()))
            for dimension in QUOTA_DIMENSIONS
        }
        quota_gaps = {
            dimension: {
                bucket: max(0, target - observed_quotas[dimension].get(bucket, 0))
                for bucket, target in quotas.items()
                if observed_quotas[dimension].get(bucket, 0) < target
            }
            for dimension, quotas in QUOTA_DIMENSIONS.items()
        }
        quota_gaps = {dimension: gaps for dimension, gaps in quota_gaps.items() if gaps}
        counts = {
            "structured_candidates": len(case_ids),
            "mechanism_deep_audits": len(case_ids & mechanism_cases),
            "outcome_cross_verifications": len(case_ids & outcome_cases),
            "execution_case_blueprints": len(case_ids & blueprint_cases),
        }
        funnel_gaps = {
            key: max(0, target - counts[key])
            for key, target in FUNNEL_TARGETS.items()
            if counts[key] < target
        }
        complete = not quota_gaps and not funnel_gaps
        rows.append(
            {
                **registry_row,
                "status": "complete" if complete else "coverage_gap",
                "funnel_counts": counts,
                "funnel_gaps": funnel_gaps,
                "observed_marginal_quotas": observed_quotas,
                "marginal_quota_gaps": quota_gaps,
            }
        )

    global_counts = {
        "structured_candidates": len(candidate_ids),
        "mechanism_deep_audits": len(mechanism_cases),
        "outcome_cross_verifications": len(outcome_cases),
        "execution_case_blueprints": len(blueprint_cases),
    }
    complete_ids = [row["subvertical_id"] for row in rows if row["status"] == "complete"]
    payload: dict[str, Any] = {
        "schema": COVERAGE_SCHEMA,
        "standard_sha256": standard["content_sha256"],
        "global_status": "complete" if len(complete_ids) == 81 else "coverage_gap",
        "complete_subvertical_count": len(complete_ids),
        "coverage_gap_subvertical_count": 81 - len(complete_ids),
        "global_funnel_counts": global_counts,
        "global_funnel_gaps": {
            key: max(0, standard["global_funnel_targets"][key] - global_counts[key])
            for key in FUNNEL_TARGETS
        },
        "complete_subvertical_ids": complete_ids,
        "subvertical_coverage": rows,
        "input_set_sha256": _digest(
            {
                "candidates": list(candidates),
                "mechanism_audits": list(mechanism_audits),
                "outcome_audits": list(outcome_audits),
                "blueprints": list(blueprints),
            }
        ),
        "completion_claim_allowed": len(complete_ids) == 81,
        "truth_boundary": (
            "Coverage counts only V2-valid unique episodes. A target matrix, migration queue, public signal, model judgment, "
            "or unreviewed seed has zero quota credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_evidence_funnel_coverage(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != COVERAGE_SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseEvidenceFunnelError("case evidence coverage seal is invalid")
    rows = payload.get("subvertical_coverage")
    if not isinstance(rows, list) or len(rows) != 81:
        raise GTMCaseEvidenceFunnelError("coverage must report all 81 subverticals")
    complete = [row for row in rows if row.get("status") == "complete"]
    if payload.get("complete_subvertical_count") != len(complete):
        raise GTMCaseEvidenceFunnelError("complete subvertical aggregate drifted")
    should_complete = len(complete) == 81
    if payload.get("completion_claim_allowed") is not should_complete:
        raise GTMCaseEvidenceFunnelError("completion claim is inconsistent with coverage")
    if payload.get("global_status") != ("complete" if should_complete else "coverage_gap"):
        raise GTMCaseEvidenceFunnelError("global coverage status is inconsistent")


def compile_seed_migration_queue(quality_seed: Mapping[str, Any], standard: Mapping[str, Any]) -> dict[str, Any]:
    verify_case_evidence_funnel_standard(standard)
    rows = []
    for team in quality_seed.get("teams", []):
        rows.append(
            {
                "migration_id": f"seed:{team.get('team_id')}",
                "source_team_id": team.get("team_id"),
                "source_team_name": team.get("team_name"),
                "source_promotion_status": team.get("promotion_status"),
                "proposed_business_model": team.get("business_model"),
                "status": "requires_v2_normalization",
                "quota_credit": 0,
                "blocking_fields": [
                    "stable_subvertical_id",
                    "episode_identity_and_time_window",
                    "company_scale",
                    "lifecycle_state",
                    "v2_budget_tier",
                    "recency_bucket",
                    "outcome_type",
                    "quota_market",
                    "platform_set",
                    "source_capture_receipts_with_hashes",
                ],
            }
        )
    payload: dict[str, Any] = {
        "schema": MIGRATION_SCHEMA,
        "standard_sha256": standard["content_sha256"],
        "source_seed_sha256": quality_seed.get("content_sha256"),
        "migration_item_count": len(rows),
        "quota_credit": 0,
        "items": rows,
        "truth_boundary": "Legacy seeds remain research leads and cannot count toward 200/40/10/5 until each V2 blocker is resolved.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


__all__ = [
    "ALLOWED_COST_DISCLOSURE_STATUSES",
    "BUDGET_QUOTAS",
    "COMPANY_SCALE_QUOTAS",
    "COST_COMPONENTS",
    "FUNNEL_TARGETS",
    "GTMCaseEvidenceFunnelError",
    "LIFECYCLE_QUOTAS",
    "MARKET_QUOTAS",
    "OUTCOME_QUOTAS",
    "QUOTA_DIMENSIONS",
    "RECENCY_QUOTAS",
    "build_case_evidence_funnel_standard",
    "compile_case_evidence_funnel_coverage",
    "compile_seed_migration_queue",
    "verify_case_evidence_funnel_coverage",
    "verify_case_evidence_funnel_standard",
]
