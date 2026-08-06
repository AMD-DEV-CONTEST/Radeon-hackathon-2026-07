from __future__ import annotations

import hashlib
import json
from itertools import product
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGlobalOrganicSignalSamplingStandardV1"


class OrganicSignalSamplingStandardError(ValueError):
    pass


MARKETS = {
    "north_america": ["United States", "Canada"],
    "uk_ireland": ["United Kingdom", "Ireland"],
    "europe_english": ["Netherlands", "Germany", "France", "Nordics"],
    "southern_africa_english": ["South Africa"],
    "singapore": ["Singapore"],
    "hong_kong": ["Hong Kong"],
    "anz": ["Australia", "New Zealand"],
}

B2B_VERTICALS = (
    "developer_tools", "ai_data_infrastructure", "cybersecurity", "b2b_saas",
    "fintech_regtech", "martech_sales_tech", "hr_future_of_work",
    "professional_services", "industrial_climate", "healthcare_life_sciences",
)

B2C_VERTICALS = (
    "consumer_ai_mobile_apps", "personal_finance", "health_wellness", "education_language",
    "gaming_entertainment", "commerce_marketplaces", "beauty_fashion", "food_beverage",
    "travel_hospitality", "creator_productivity",
)

SUBVERTICAL_REQUIREMENTS = {
    "developer_tools": ["application_development", "devops_observability", "testing_quality", "open_source_infrastructure"],
    "ai_data_infrastructure": ["foundation_model_tools", "data_platforms", "analytics_bi", "mlops_and_inference"],
    "cybersecurity": ["identity", "application_security", "cloud_security", "governance_risk_compliance"],
    "b2b_saas": ["horizontal_saas", "vertical_saas", "collaboration", "finance_operations"],
    "fintech_regtech": ["payments", "banking", "insurance", "regulatory_technology"],
    "martech_sales_tech": ["crm", "marketing_automation", "commerce_enablement", "revenue_intelligence"],
    "hr_future_of_work": ["talent", "workforce_operations", "learning", "employee_experience"],
    "professional_services": ["consulting", "agency_services", "legal_accounting", "managed_and_field_services"],
    "industrial_climate": ["manufacturing", "industrial_equipment", "engineering_construction", "commercial_real_estate", "energy_climate"],
    "healthcare_life_sciences": ["provider", "biotechnology", "medical_devices", "healthcare_operations"],
    "consumer_ai_mobile_apps": ["assistants", "creative_apps", "utility_apps", "social_apps"],
    "personal_finance": ["banking", "investing", "insurance", "credit_and_budgeting"],
    "health_wellness": ["fitness", "nutrition", "mental_wellbeing_nonclinical", "care_navigation"],
    "education_language": ["language_learning", "tutoring", "skills", "family_learning"],
    "gaming_entertainment": ["mobile_games", "pc_console", "streaming", "fan_communities"],
    "commerce_marketplaces": ["general_ecommerce", "local_marketplaces", "home_property", "services_marketplaces"],
    "beauty_fashion": ["beauty", "apparel", "luxury", "resale"],
    "food_beverage": ["consumer_packaged_goods", "restaurants", "delivery", "functional_food"],
    "travel_hospitality": ["destinations", "lodging", "transport", "experiences"],
    "creator_productivity": ["creator_tools", "focus_productivity", "audio_video", "independent_business"],
}

PLATFORMS = (
    {
        "platform": "linkedin", "priority": "b2b_primary", "oss_routes": ["crawlee-python", "rsshub", "scrapy"],
        "access": "ordinary_public_pages_or_operator_authorized_session_only",
    },
    {
        "platform": "youtube", "priority": "b2b_b2c_primary", "oss_routes": ["yt-dlp", "rsshub"],
        "access": "public_metadata_first",
    },
    {
        "platform": "tiktok", "priority": "b2c_primary", "oss_routes": ["yt-dlp", "rsshub"],
        "access": "public_metadata_or_operator_authorized_session_only",
    },
    {
        "platform": "instagram", "priority": "b2c_primary", "oss_routes": ["gallery-dl", "instaloader", "rsshub"],
        "access": "public_metadata_or_operator_authorized_session_only",
    },
    {
        "platform": "reddit", "priority": "b2b_b2c_primary", "oss_routes": ["praw", "rsshub"],
        "access": "official_credential_or_public_feed",
    },
    {
        "platform": "x", "priority": "b2b_b2c_secondary", "oss_routes": ["gallery-dl", "yt-dlp", "rsshub"],
        "access": "public_metadata_or_operator_authorized_session_only",
    },
    {
        "platform": "facebook", "priority": "b2c_regional", "oss_routes": ["yt-dlp", "rsshub"],
        "access": "public_metadata_or_operator_authorized_session_only",
    },
    {
        "platform": "pinterest", "priority": "b2c_visual", "oss_routes": ["gallery-dl", "rsshub"],
        "access": "public_metadata_first",
    },
    {
        "platform": "bluesky", "priority": "open_social", "oss_routes": ["atproto"],
        "access": "official_public_appview",
    },
    {
        "platform": "mastodon", "priority": "open_social", "oss_routes": ["mastodon.py"],
        "access": "same_origin_public_status_api",
    },
    {
        "platform": "podcast_rss", "priority": "long_form_authority", "oss_routes": ["feedparser", "yt-dlp"],
        "access": "public_feed_first",
    },
    {
        "platform": "owned_blog_newsletter", "priority": "search_geo_authority", "oss_routes": ["feedparser", "trafilatura", "scrapy"],
        "access": "public_feed_or_static_page",
    },
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def build_global_organic_signal_sampling_standard() -> dict[str, Any]:
    segment_market_cells = []
    verticals = {"b2b": B2B_VERTICALS, "b2c": B2C_VERTICALS}
    for business_model, market, vertical in product(("b2b", "b2c"), MARKETS, range(10)):
        named_vertical = verticals[business_model][vertical]
        segment_market_cells.append(
            {
                "cell_id": f"{business_model}:{market}:{named_vertical}",
                "business_model": business_model,
                "market": market,
                "vertical": named_vertical,
                "required_subverticals": SUBVERTICAL_REQUIREMENTS[named_vertical],
                "required_company_scales": ["small", "mid_market", "enterprise_or_mass_brand"],
                "required_lifecycle_states": ["pre_pmf", "launch", "growth", "mature"],
                "minimum_distinct_sources": 6,
                "minimum_recent_items_per_source": 20,
                "minimum_relative_breakout_candidates": 1,
            }
        )

    platform_market_lanes = [
        {
            "lane_id": f"{business_model}:{market}:{row['platform']}",
            "business_model": business_model,
            "market": market,
            "platform": row["platform"],
            "minimum_distinct_sources": 3,
            "minimum_recent_items": 60,
        }
        for business_model, market, row in product(("b2b", "b2c"), MARKETS, PLATFORMS)
    ]

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "language_priority": ["English"],
        "market_groups": MARKETS,
        "business_models": {
            "b2b": list(B2B_VERTICALS),
            "b2c": list(B2C_VERTICALS),
        },
        "company_scales": ["small", "mid_market", "enterprise_or_mass_brand"],
        "lifecycle_states": ["pre_pmf", "launch", "growth", "mature"],
        "platform_contracts": list(PLATFORMS),
        "segment_market_cells": segment_market_cells,
        "platform_market_lanes": platform_market_lanes,
        "sample_design": {
            "preferred_window_days": 90,
            "maximum_window_days": 180,
            "same_source_minimum_items_for_baseline": 10,
            "preferred_items_per_source": 30,
            "relative_attention_breakout_threshold": 2.0,
            "relative_interaction_breakout_threshold": 1.5,
            "absolute_cross_account_ranking_forbidden": True,
            "paid_or_sponsored_content_must_be_separated": True,
            "bot_or_duplicate_filter_required": True,
            "source_and_capture_receipt_required": True,
        },
        "strategy_abstraction_contract": {
            "extract_only": [
                "audience_tension", "hook_structure", "proof_mechanism", "narrative_progression",
                "format_grammar", "participation_mechanic", "relay_object", "platform_native_pacing",
                "local_cultural_context", "cta_job", "conversion_path", "failure_and_kill_rule",
            ],
            "forbid": [
                "source_copy", "creator_voice_clone", "raw_comment_training", "identity_retention",
                "causal_claim_from_public_counter", "automatic_strategy_mutation",
            ],
            "generalization_unit": (
                "business_model + vertical + lifecycle + scale + market + platform + audience_job; "
                "never a universal viral formula"
            ),
            "industry_language_requirement": (
                "Every generated strategy must select one subvertical, buyer or user, decision tension, proof language, "
                "native voice, and forbidden shortcut before producing platform copy."
            ),
        },
        "learning_memory_contract": {
            "public_signal_role": "hypothesis_generation_only",
            "eligible_learning_evidence": "observed_result_bound_to_exact_strategy_and_first_party_or_official_export",
            "required_human_approval": "named approver + exact evidence SHA-256 + promote/repair/retire verdict",
            "automatic_write_count": 0,
            "current_run_mutation_allowed": False,
        },
        "coverage_truth": {
            "segment_market_cell_count": len(segment_market_cells),
            "platform_market_lane_count": len(platform_market_lanes),
            "live_collection_is_not_implied": True,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_global_organic_signal_sampling_standard(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise OrganicSignalSamplingStandardError("organic signal sampling standard seal is invalid")
    if payload.get("coverage_truth", {}).get("segment_market_cell_count") != 140:
        raise OrganicSignalSamplingStandardError("segment-market coverage drifted")
    if payload.get("coverage_truth", {}).get("platform_market_lane_count") != 168:
        raise OrganicSignalSamplingStandardError("platform-market coverage drifted")
    cells = payload.get("segment_market_cells")
    if not isinstance(cells, list) or any(
        not isinstance(row, Mapping)
        or len(row.get("required_subverticals", [])) < 4
        or len(set(row.get("required_subverticals", []))) != len(row.get("required_subverticals", []))
        for row in cells
    ):
        raise OrganicSignalSamplingStandardError("subvertical and industry-language coverage drifted")
    memory = payload.get("learning_memory_contract")
    if not isinstance(memory, Mapping) or memory.get("automatic_write_count") != 0:
        raise OrganicSignalSamplingStandardError("public signals were allowed to auto-write memory")


def compile_global_organic_signal_coverage_receipt(
    standard: Mapping[str, Any],
    signal_packs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Measure actual evidence coverage without confusing a target matrix with collection."""

    verify_global_organic_signal_sampling_standard(standard)
    from .gtm_recent_organic_signal_pack import verify_recent_organic_signal_pack

    cell_targets = {row["cell_id"]: row for row in standard["segment_market_cells"]}
    lane_targets = {row["lane_id"]: row for row in standard["platform_market_lanes"]}
    cells: dict[str, dict[str, Any]] = {}
    lanes: dict[str, dict[str, Any]] = {}
    unclassified = 0
    for pack in signal_packs:
        verify_recent_organic_signal_pack(pack)
        for source in pack.get("sources", []):
            if not isinstance(source, Mapping):
                continue
            context = source.get("sampling_context")
            if not isinstance(context, Mapping):
                unclassified += 1
                continue
            cell_id = f"{context.get('business_model')}:{context.get('market')}:{context.get('vertical')}"
            lane_id = f"{context.get('business_model')}:{context.get('market')}:{source.get('platform')}"
            if cell_id not in cell_targets or lane_id not in lane_targets:
                unclassified += 1
                continue
            source_sha = str(source.get("source_url_sha256"))
            recent = int(source.get("recent_item_count_maximum_window", 0))
            breakouts = int(source.get("relative_attention_index_ge_2_count", 0))
            cell = cells.setdefault(cell_id, {
                "sources": set(), "source_recent_items": {}, "source_breakouts": {},
                "scales": set(), "lifecycles": set(),
            })
            cell["sources"].add(source_sha)
            cell["source_recent_items"][source_sha] = max(
                recent, cell["source_recent_items"].get(source_sha, 0)
            )
            cell["source_breakouts"][source_sha] = max(
                breakouts, cell["source_breakouts"].get(source_sha, 0)
            )
            cell["scales"].add(context.get("company_scale"))
            cell["lifecycles"].add(context.get("lifecycle"))
            lane = lanes.setdefault(lane_id, {"sources": set(), "source_recent_items": {}})
            lane["sources"].add(source_sha)
            lane["source_recent_items"][source_sha] = max(
                recent, lane["source_recent_items"].get(source_sha, 0)
            )

    qualified_cells: list[str] = []
    for cell_id, observed in cells.items():
        target = cell_targets[cell_id]
        if (
            len(observed["sources"]) >= target["minimum_distinct_sources"]
            and sum(observed["source_recent_items"].values())
            >= target["minimum_distinct_sources"] * target["minimum_recent_items_per_source"]
            and sum(observed["source_breakouts"].values())
            >= target["minimum_relative_breakout_candidates"]
            and set(target["required_company_scales"]).issubset(observed["scales"])
            and set(target["required_lifecycle_states"]).issubset(observed["lifecycles"])
        ):
            qualified_cells.append(cell_id)
    qualified_lanes = [
        lane_id
        for lane_id, observed in lanes.items()
        if len(observed["sources"]) >= lane_targets[lane_id]["minimum_distinct_sources"]
        and sum(observed["source_recent_items"].values())
        >= lane_targets[lane_id]["minimum_recent_items"]
    ]
    observed_cell_rows = []
    for cell_id, observed in sorted(cells.items()):
        target = cell_targets[cell_id]
        recent_items = sum(observed["source_recent_items"].values())
        breakout_count = sum(observed["source_breakouts"].values())
        observed_cell_rows.append({
            "cell_id": cell_id,
            "distinct_source_count": len(observed["sources"]),
            "recent_item_count": recent_items,
            "relative_attention_breakout_count": breakout_count,
            "observed_company_scales": sorted(observed["scales"]),
            "observed_lifecycle_states": sorted(observed["lifecycles"]),
            "remaining_distinct_sources": max(
                0, target["minimum_distinct_sources"] - len(observed["sources"])
            ),
            "remaining_recent_items": max(
                0,
                target["minimum_distinct_sources"]
                * target["minimum_recent_items_per_source"]
                - recent_items,
            ),
            "missing_company_scales": sorted(
                set(target["required_company_scales"]) - observed["scales"]
            ),
            "missing_lifecycle_states": sorted(
                set(target["required_lifecycle_states"]) - observed["lifecycles"]
            ),
        })
    observed_lane_rows = []
    for lane_id, observed in sorted(lanes.items()):
        target = lane_targets[lane_id]
        recent_items = sum(observed["source_recent_items"].values())
        observed_lane_rows.append({
            "lane_id": lane_id,
            "distinct_source_count": len(observed["sources"]),
            "recent_item_count": recent_items,
            "remaining_distinct_sources": max(
                0, target["minimum_distinct_sources"] - len(observed["sources"])
            ),
            "remaining_recent_items": max(
                0, target["minimum_recent_items"] - recent_items
            ),
        })
    payload: dict[str, Any] = {
        "schema": "ProofLaunchGlobalOrganicSignalCoverageReceiptV1",
        "sampling_standard_sha256": standard["content_sha256"],
        "signal_pack_sha256s": [pack["content_sha256"] for pack in signal_packs],
        "target_segment_market_cell_count": len(cell_targets),
        "observed_segment_market_cell_count": len(cells),
        "qualified_segment_market_cell_count": len(qualified_cells),
        "target_platform_market_lane_count": len(lane_targets),
        "observed_platform_market_lane_count": len(lanes),
        "qualified_platform_market_lane_count": len(qualified_lanes),
        "classified_source_count": sum(len(row["sources"]) for row in cells.values()),
        "unclassified_source_count": unclassified,
        "qualified_segment_market_cell_ids": sorted(qualified_cells),
        "qualified_platform_market_lane_ids": sorted(qualified_lanes),
        "observed_segment_market_cells": observed_cell_rows,
        "observed_platform_market_lanes": observed_lane_rows,
        "missing_segment_market_cell_ids": sorted(set(cell_targets) - set(qualified_cells)),
        "missing_platform_market_lane_ids": sorted(set(lane_targets) - set(qualified_lanes)),
        "global_coverage_complete": (
            len(qualified_cells) == len(cell_targets) and len(qualified_lanes) == len(lane_targets)
        ),
        "automatic_learning_memory_write_count": 0,
        "truth_boundary": (
            "This receipt measures collection coverage against the frozen sampling standard. "
            "It does not prove creative effectiveness, causal lift or global representativeness."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


__all__ = [
    "OrganicSignalSamplingStandardError",
    "SCHEMA",
    "build_global_organic_signal_sampling_standard",
    "compile_global_organic_signal_coverage_receipt",
    "verify_global_organic_signal_sampling_standard",
]
