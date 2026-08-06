from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import re
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "ProofLaunchGTMStartupLandscapeV1"
DISTILLATION_SCHEMA = "ProofLaunchGTMStartupDistillationQueueV1"
SAMPLING_BRIDGE_SCHEMA = "ProofLaunchGTMStartupSamplingBridgeV1"
POSITIONING_SCHEMA = "ProofLaunchGTMStartupPositioningPatternsV1"
EXPANSION_BACKLOG_SCHEMA = "ProofLaunchGTMStartupExpansionBacklogV1"


class GTMStartupLandscapeError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _clean_text(value: Any, limit: int = 600) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def parse_yc_directory_page(page_html: str, source_url: str, cohort: str) -> dict[str, Any]:
    match = re.search(r'data-page="(.*?)"', page_html, flags=re.DOTALL)
    if not match:
        raise GTMStartupLandscapeError(f"YC data-page payload missing: {source_url}")
    try:
        payload = json.loads(html.unescape(match.group(1)))
    except (TypeError, json.JSONDecodeError) as exc:
        raise GTMStartupLandscapeError(f"YC data-page payload invalid: {source_url}") from exc
    props = payload.get("props")
    if not isinstance(props, dict) or not isinstance(props.get("companies"), list):
        raise GTMStartupLandscapeError(f"YC companies payload missing: {source_url}")
    current_page = props.get("currentPage")
    total_pages = props.get("totalPages")
    if not isinstance(current_page, int) or not isinstance(total_pages, int) or current_page < 1 or total_pages < current_page:
        raise GTMStartupLandscapeError(f"YC pagination invalid: {source_url}")
    return {
        "cohort": cohort,
        "source_url": source_url,
        "current_page": current_page,
        "total_pages": total_pages,
        "record_count": len(props["companies"]),
        "page_sha256": hashlib.sha256(page_html.encode("utf-8")).hexdigest(),
        "title": _clean_text(props.get("title"), 240),
        "description": _clean_text(props.get("description"), 400),
        "companies": props["companies"],
    }


INDUSTRY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ai_ml", ("artificial-intelligence", "machine-learning", "ai", "llm", "computer-vision", "voice-ai")),
    ("developer_tools", ("developer-tools", "devtools", "open-source", "api", "cloud-computing", "infrastructure")),
    ("enterprise_saas", ("saas", "enterprise", "b2b", "workflow", "automation", "productivity")),
    ("data_analytics", ("analytics", "data", "databases", "data-engineering", "data-visualization", "search")),
    ("cybersecurity", ("security", "cybersecurity", "privacy", "fraud", "identity")),
    ("fintech_insurance", ("fintech", "finance", "banking", "payments", "insurance", "investing", "crypto")),
    ("health_biotech", ("health", "healthcare", "biotech", "medical", "pharma", "digital-health", "mental-health")),
    ("industrial_manufacturing_robotics", ("manufacturing", "industrial", "robotics", "drones", "3d-printing", "factory")),
    ("climate_energy_agriculture", ("climate", "energy", "agriculture", "agtech", "solar", "carbon", "food-tech")),
    ("logistics_supply_chain_mobility", ("logistics", "supply-chain", "freight", "transportation", "mobility", "delivery", "automotive")),
    ("construction_real_estate", ("construction", "real-estate", "proptech", "architecture", "housing")),
    ("commerce_retail_marketplace", ("e-commerce", "ecommerce", "retail", "marketplace", "shopping", "d2c")),
    ("consumer_apps_lifestyle", ("consumer", "consumer-products", "lifestyle", "fitness", "personal", "social")),
    ("media_creator_gaming", ("media", "creator", "gaming", "entertainment", "music", "video", "social-media")),
    ("education_learning", ("education", "edtech", "learning", "tutoring", "training")),
    ("hr_workplace_services", ("hr", "recruiting", "payroll", "future-of-work", "customer-service", "professional-services")),
    ("food_hospitality_travel", ("food", "restaurant", "hospitality", "travel", "tourism", "hotel", "grocery")),
    ("legal_compliance_government", ("legal", "compliance", "govtech", "government", "regtech", "public-safety")),
    ("hardware_electronics", ("hardware", "electronics", "iot", "semiconductors", "wearables", "consumer-electronics")),
)


def _industry_families(tags: Sequence[str], one_liner: str) -> list[str]:
    searchable = " ".join([*tags, one_liner.casefold().replace(" ", "-")])
    families = [family for family, terms in INDUSTRY_RULES if any(term in searchable for term in terms)]
    return families or ["other_specialist_vertical"]


def _size_stage(team_size: Any) -> str:
    size = team_size if isinstance(team_size, int) and team_size >= 0 else None
    if size is None:
        return "unknown"
    if size <= 5:
        return "micro_0_5"
    if size <= 20:
        return "early_6_20"
    if size <= 100:
        return "growth_21_100"
    if size <= 500:
        return "scale_101_500"
    return "large_501_plus"


def _market_region(country: str, location: str) -> str:
    value = f"{country} {location}".casefold()
    groups = (
        ("north_america", (" us ", "usa", "united states", "canada")),
        ("uk_ireland", ("united kingdom", "england", "scotland", "ireland", "london")),
        ("anz", ("australia", "new zealand")),
        ("southeast_asia", ("singapore", "indonesia", "malaysia", "philippines", "vietnam", "thailand")),
        ("south_asia", ("india", "pakistan", "bangladesh", "sri lanka")),
        ("latin_america", ("brazil", "mexico", "colombia", "argentina", "chile", "peru", "latin america")),
        ("europe", ("france", "germany", "spain", "italy", "netherlands", "sweden", "norway", "denmark", "finland", "poland", "europe")),
        ("africa", ("south africa", "nigeria", "kenya", "ghana", "egypt", "africa")),
        ("middle_east", ("israel", "uae", "united arab emirates", "saudi", "turkey", "middle east")),
        ("east_asia", ("china", "hong kong", "taiwan", "japan", "korea")),
    )
    padded = f" {value} "
    for region, terms in groups:
        if any(term in padded for term in terms):
            return region
    return "global_or_unresolved"


def _normalize_url(value: Any) -> str | None:
    text = _clean_text(value, 500)
    return text if text.startswith(("http://", "https://")) else None


def _normalize_company(raw: Mapping[str, Any], cohorts: Sequence[str], source_urls: Sequence[str]) -> dict[str, Any]:
    company_id = raw.get("id")
    slug = _clean_text(raw.get("slug"), 180)
    name = _clean_text(raw.get("name"), 240)
    if not isinstance(company_id, int) or not slug or not name:
        raise GTMStartupLandscapeError("company identity is incomplete")
    cohort_set = set(cohorts)
    business_model = (
        "mixed"
        if {"b2b", "b2c"}.issubset(cohort_set)
        else "b2b"
        if "b2b" in cohort_set
        else "b2c"
        if "b2c" in cohort_set
        else "unresolved"
    )
    tags = sorted({_clean_text(tag, 100).casefold() for tag in raw.get("tags", []) if _clean_text(tag, 100)})
    one_liner = _clean_text(raw.get("one_liner"), 500)
    location = _clean_text(raw.get("location"), 240)
    country = _clean_text(raw.get("country"), 40)
    return {
        "company_id": company_id,
        "slug": slug,
        "name": name,
        "business_model": business_model,
        "directory_cohorts": sorted(cohort_set),
        "batch_name": _clean_text(raw.get("batch_name"), 40) or None,
        "year_founded": raw.get("year_founded") if isinstance(raw.get("year_founded"), int) else None,
        "team_size": raw.get("team_size") if isinstance(raw.get("team_size"), int) else None,
        "size_stage_proxy": _size_stage(raw.get("team_size")),
        "directory_status": _clean_text(raw.get("ycdc_status"), 80) or "unknown",
        "one_liner": one_liner,
        "tags": tags,
        "industry_families": _industry_families(tags, one_liner),
        "location": location or None,
        "country": country or None,
        "market_region": _market_region(country, location),
        "website": _normalize_url(raw.get("website")),
        "linkedin_url": _normalize_url(raw.get("linkedin_url")),
        "twitter_url": _normalize_url(raw.get("twitter_url")),
        "facebook_url": _normalize_url(raw.get("fb_url")),
        "github_url": _normalize_url(raw.get("github_url")),
        "official_directory_url": f"https://www.ycombinator.com/companies/{slug}",
        "source_page_urls": sorted(set(source_urls)),
        "evidence_scope": "Official directory facts and company-supplied description only.",
        "growth_case_status": "not_yet_audited",
        "training_eligible": False,
    }


def compile_startup_landscape(
    pages: Sequence[Mapping[str, Any]],
    *,
    captured_at: str | None = None,
    minimum_records: int = 1,
) -> dict[str, Any]:
    if not pages:
        raise GTMStartupLandscapeError("at least one directory page is required")
    captured_at = captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    by_company: dict[int, dict[str, Any]] = {}
    cohorts_by_company: dict[int, set[str]] = defaultdict(set)
    sources_by_company: dict[int, set[str]] = defaultdict(set)
    page_manifest: list[dict[str, Any]] = []
    page_keys: set[tuple[str, int]] = set()
    cohort_pages: dict[str, set[int]] = defaultdict(set)
    cohort_totals: dict[str, int] = {}
    for page in pages:
        cohort = _clean_text(page.get("cohort"), 40)
        current_page = page.get("current_page")
        total_pages = page.get("total_pages")
        companies = page.get("companies")
        if not cohort or not isinstance(current_page, int) or not isinstance(total_pages, int) or not isinstance(companies, list):
            raise GTMStartupLandscapeError("directory page metadata is incomplete")
        key = (cohort, current_page)
        if key in page_keys:
            raise GTMStartupLandscapeError(f"duplicate directory page: {key}")
        page_keys.add(key)
        cohort_pages[cohort].add(current_page)
        if cohort in cohort_totals and cohort_totals[cohort] != total_pages:
            raise GTMStartupLandscapeError(f"pagination total drifted for {cohort}")
        cohort_totals[cohort] = total_pages
        source_url = _clean_text(page.get("source_url"), 500)
        page_sha256 = _clean_text(page.get("page_sha256"), 80)
        if not source_url.startswith("https://") or not re.fullmatch(r"[0-9a-f]{64}", page_sha256):
            raise GTMStartupLandscapeError("directory page provenance is invalid")
        page_manifest.append(
            {
                "cohort": cohort,
                "page": current_page,
                "source_url": source_url,
                "page_sha256": page_sha256,
                "record_count": len(companies),
            }
        )
        for raw in companies:
            if not isinstance(raw, dict) or not isinstance(raw.get("id"), int):
                raise GTMStartupLandscapeError("company record is invalid")
            company_id = raw["id"]
            if company_id in by_company and _clean_text(by_company[company_id].get("slug")) != _clean_text(raw.get("slug")):
                raise GTMStartupLandscapeError(f"company id collision: {company_id}")
            by_company[company_id] = dict(raw)
            cohorts_by_company[company_id].add(cohort)
            sources_by_company[company_id].add(source_url)
    for cohort, total_pages in cohort_totals.items():
        if cohort_pages[cohort] != set(range(1, total_pages + 1)):
            raise GTMStartupLandscapeError(f"directory pagination is incomplete for {cohort}")
    if len(by_company) < minimum_records:
        raise GTMStartupLandscapeError(f"startup landscape requires at least {minimum_records} unique records")
    records = [
        _normalize_company(by_company[company_id], sorted(cohorts_by_company[company_id]), sorted(sources_by_company[company_id]))
        for company_id in sorted(by_company)
    ]
    business_counts = Counter(record["business_model"] for record in records)
    stage_counts = Counter(record["size_stage_proxy"] for record in records)
    status_counts = Counter(record["directory_status"] for record in records)
    region_counts = Counter(record["market_region"] for record in records)
    industry_counts: Counter[str] = Counter()
    coverage_cells: Counter[tuple[str, str, str, str]] = Counter()
    for record in records:
        for family in record["industry_families"]:
            industry_counts[family] += 1
            coverage_cells[(record["business_model"], family, record["size_stage_proxy"], record["market_region"])] += 1
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": captured_at,
        "source_authority": "Y Combinator official public Startup Directory",
        "record_count": len(records),
        "source_page_count": len(page_manifest),
        "business_model_counts": dict(sorted(business_counts.items())),
        "size_stage_proxy_counts": dict(sorted(stage_counts.items())),
        "directory_status_counts": dict(sorted(status_counts.items())),
        "market_region_counts": dict(sorted(region_counts.items())),
        "industry_family_counts": dict(sorted(industry_counts.items())),
        "coverage_cell_count": len(coverage_cells),
        "coverage_cells": [
            {
                "business_model": key[0],
                "industry_family": key[1],
                "size_stage_proxy": key[2],
                "market_region": key[3],
                "company_count": count,
            }
            for key, count in sorted(coverage_cells.items())
        ],
        "page_manifest": sorted(page_manifest, key=lambda item: (item["cohort"], item["page"])),
        "records": records,
        "truth_boundary": (
            "This artifact is a directory landscape, not a growth-case corpus. Directory presence, tags, team size, status, "
            "descriptions, and social links do not prove product-market fit, organic growth, spend, conversion, revenue, or causality."
        ),
        "training_policy": {
            "directory_records_training_eligible": False,
            "company_copy_or_voice_reuse_allowed": False,
            "human_case_evidence_review_required": True,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


DISTILLATION_FIELDS: tuple[str, ...] = (
    "audience_and_buyer",
    "problem_and_switching_tension",
    "positioning_and_category_language",
    "proof_object_and_product_value",
    "distribution_channel_and_first_hundred_route",
    "platform_native_content_and_voice",
    "spend_scope_and_resource_cost",
    "outcome_chain_baseline_window_and_confounds",
)


def compile_startup_distillation_queue(landscape: Mapping[str, Any]) -> dict[str, Any]:
    verify_startup_landscape(landscape)
    queue = []
    for record in landscape["records"]:
        score = 0
        score += 40 if record["directory_status"].casefold() == "active" else 0
        score += 30 if record["size_stage_proxy"] in {"micro_0_5", "early_6_20"} else 15 if record["size_stage_proxy"] == "growth_21_100" else 0
        score += 15 if record["year_founded"] and record["year_founded"] >= 2020 else 0
        score += 10 if record["market_region"] in {"north_america", "uk_ireland", "anz", "southeast_asia"} else 0
        score += 5 if record["linkedin_url"] or record["twitter_url"] or record["github_url"] else 0
        queue.append(
            {
                "company_id": record["company_id"],
                "name": record["name"],
                "business_model": record["business_model"],
                "industry_families": record["industry_families"],
                "size_stage_proxy": record["size_stage_proxy"],
                "market_region": record["market_region"],
                "priority_score": score,
                "priority_band": "p0" if score >= 90 else "p1" if score >= 70 else "p2",
                "missing_distillation_fields": list(DISTILLATION_FIELDS),
                "promotion_status": "blocked_pending_case_and_channel_evidence",
                "training_eligible": False,
            }
        )
    queue.sort(key=lambda item: (-item["priority_score"], item["business_model"], item["name"].casefold()))
    payload: dict[str, Any] = {
        "schema": DISTILLATION_SCHEMA,
        "source_landscape_sha256": landscape["content_sha256"],
        "company_count": len(queue),
        "distillation_fields_per_company": len(DISTILLATION_FIELDS),
        "distillation_audit_unit_count": len(queue) * len(DISTILLATION_FIELDS),
        "priority_band_counts": dict(sorted(Counter(item["priority_band"] for item in queue).items())),
        "queue": queue,
        "promotion_gate": {
            "all_fields_required": True,
            "at_least_one_primary_company_source_required": True,
            "observed_channel_artifact_required": True,
            "baseline_spend_window_outcome_and_confounds_required_for_growth_claim": True,
            "human_approval_required": True,
            "automatic_training_promotion_allowed": False,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_startup_landscape(landscape: Mapping[str, Any]) -> None:
    unsigned = dict(landscape)
    supplied = unsigned.pop("content_sha256", None)
    if landscape.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMStartupLandscapeError("startup landscape digest or schema is invalid")
    if landscape.get("record_count") != len(landscape.get("records", [])):
        raise GTMStartupLandscapeError("startup landscape record count drifted")
    if not all(record.get("training_eligible") is False for record in landscape.get("records", [])):
        raise GTMStartupLandscapeError("a directory record escaped the training boundary")


def verify_startup_distillation_queue(queue: Mapping[str, Any], landscape: Mapping[str, Any]) -> None:
    unsigned = dict(queue)
    supplied = unsigned.pop("content_sha256", None)
    if queue.get("schema") != DISTILLATION_SCHEMA or supplied != _digest(unsigned):
        raise GTMStartupLandscapeError("startup distillation queue digest or schema is invalid")
    rebuilt = compile_startup_distillation_queue(landscape)
    if rebuilt != queue:
        raise GTMStartupLandscapeError("startup distillation queue drifted")


def _standard_vertical(record: Mapping[str, Any]) -> str:
    families = set(record["industry_families"])
    tags = set(record["tags"])
    if record["business_model"] == "b2b":
        if "cybersecurity" in families:
            return "cybersecurity"
        if "health_biotech" in families:
            return "healthcare_life_sciences"
        if "fintech_insurance" in families:
            return "fintech_regtech"
        if families & {"industrial_manufacturing_robotics", "climate_energy_agriculture", "logistics_supply_chain_mobility", "construction_real_estate", "hardware_electronics"}:
            return "industrial_climate"
        if "developer_tools" in families:
            return "developer_tools"
        if families & {"ai_ml", "data_analytics"}:
            return "ai_data_infrastructure"
        if "hr_workplace_services" in families:
            return "hr_future_of_work"
        if tags & {"marketing", "sales", "sales-enablement", "advertising", "martech"}:
            return "martech_sales_tech"
        if families & {"legal_compliance_government", "other_specialist_vertical"}:
            return "professional_services"
        return "b2b_saas"
    if "fintech_insurance" in families:
        return "personal_finance"
    if "health_biotech" in families:
        return "health_wellness"
    if "education_learning" in families:
        return "education_language"
    if "media_creator_gaming" in families and tags & {"gaming", "entertainment", "music", "sports-tech"}:
        return "gaming_entertainment"
    if "commerce_retail_marketplace" in families:
        return "commerce_marketplaces"
    if tags & {"beauty", "fashion", "cosmetics", "apparel", "smart-clothing"}:
        return "beauty_fashion"
    if "food_hospitality_travel" in families and tags & {"travel", "tourism", "hotel", "hospitality"}:
        return "travel_hospitality"
    if "food_hospitality_travel" in families:
        return "food_beverage"
    if "media_creator_gaming" in families or tags & {"productivity", "creator", "social-media"}:
        return "creator_productivity"
    return "consumer_ai_mobile_apps"


def _standard_market(record: Mapping[str, Any]) -> str | None:
    region = record["market_region"]
    location = (record.get("location") or "").casefold()
    if region in {"north_america", "uk_ireland", "anz"}:
        return region
    if region == "europe":
        return "europe_english"
    if region == "southeast_asia" and "singapore" in location:
        return "singapore"
    if region == "east_asia" and "hong kong" in location:
        return "hong_kong"
    if region == "africa" and "south africa" in location:
        return "southern_africa_english"
    return None


def _standard_scale(record: Mapping[str, Any]) -> str:
    stage = record["size_stage_proxy"]
    if stage in {"micro_0_5", "early_6_20", "unknown"}:
        return "small"
    if stage in {"growth_21_100", "scale_101_500"}:
        return "mid_market"
    return "enterprise_or_mass_brand"


def _standard_lifecycle(record: Mapping[str, Any]) -> str:
    if record["directory_status"] in {"Public", "Acquired"} or record["size_stage_proxy"] == "large_501_plus":
        return "mature"
    founded = record.get("year_founded")
    if founded and founded >= 2025 and record["size_stage_proxy"] in {"micro_0_5", "early_6_20"}:
        return "pre_pmf"
    if founded and founded >= 2022:
        return "launch"
    return "growth"


def compile_startup_sampling_bridge(landscape: Mapping[str, Any], standard: Mapping[str, Any]) -> dict[str, Any]:
    verify_startup_landscape(landscape)
    cells = standard.get("segment_market_cells")
    lanes = standard.get("platform_market_lanes")
    if standard.get("schema") != "ProofLaunchGlobalOrganicSignalSamplingStandardV1" or not isinstance(cells, list) or not isinstance(lanes, list):
        raise GTMStartupLandscapeError("organic sampling standard is invalid")
    assignments: dict[int, dict[str, Any]] = {}
    by_cell: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmapped_markets = 0
    for record in landscape["records"]:
        if record["business_model"] not in {"b2b", "b2c"}:
            assignments[record["company_id"]] = {
                "company_id": record["company_id"],
                "business_model": record["business_model"],
                "vertical": None,
                "market": None,
                "company_scale": _standard_scale(record),
                "lifecycle_state": _standard_lifecycle(record),
            }
            unmapped_markets += 1
            continue
        market = _standard_market(record)
        vertical = _standard_vertical(record)
        assignment = {
            "company_id": record["company_id"],
            "business_model": record["business_model"],
            "vertical": vertical,
            "market": market,
            "company_scale": _standard_scale(record),
            "lifecycle_state": _standard_lifecycle(record),
        }
        assignments[record["company_id"]] = assignment
        if market is None:
            unmapped_markets += 1
            continue
        cell_id = f"{record['business_model']}:{market}:{vertical}"
        by_cell[cell_id].append(record)
    bridged_cells = []
    populated = 0
    for cell in cells:
        records = by_cell.get(cell["cell_id"], [])
        if records:
            populated += 1
        scales = sorted({assignments[record["company_id"]]["company_scale"] for record in records})
        lifecycles = sorted({assignments[record["company_id"]]["lifecycle_state"] for record in records})
        bridged_cells.append(
            {
                "cell_id": cell["cell_id"],
                "business_model": cell["business_model"],
                "market": cell["market"],
                "vertical": cell["vertical"],
                "directory_company_count": len(records),
                "company_ids": sorted(record["company_id"] for record in records),
                "observed_company_scales": scales,
                "missing_company_scales": sorted(set(cell["required_company_scales"]) - set(scales)),
                "observed_lifecycle_states": lifecycles,
                "missing_lifecycle_states": sorted(set(cell["required_lifecycle_states"]) - set(lifecycles)),
                "coverage_status": "directory_population_present" if records else "no_directory_population",
                "recent_signal_status": "not_collected_by_this_bridge",
                "growth_mechanism_status": "not_audited",
            }
        )
    platform_field = {
        "linkedin": "linkedin_url",
        "x": "twitter_url",
        "facebook": "facebook_url",
        "owned_blog_newsletter": "website",
    }
    bridged_lanes = []
    for lane in lanes:
        eligible = [
            record
            for record in landscape["records"]
            if record["business_model"] == lane["business_model"]
            and assignments[record["company_id"]]["market"] == lane["market"]
        ]
        field = platform_field.get(lane["platform"])
        candidates = [record for record in eligible if field and record.get(field)]
        bridged_lanes.append(
            {
                "lane_id": lane["lane_id"],
                "business_model": lane["business_model"],
                "market": lane["market"],
                "platform": lane["platform"],
                "directory_company_population": len(eligible),
                "direct_handle_candidate_count": len(candidates),
                "candidate_company_ids": sorted(record["company_id"] for record in candidates),
                "signal_collection_status": "not_collected_by_this_bridge",
                "minimum_recent_items": lane["minimum_recent_items"],
            }
        )
    payload: dict[str, Any] = {
        "schema": SAMPLING_BRIDGE_SCHEMA,
        "source_landscape_sha256": landscape["content_sha256"],
        "source_sampling_standard_sha256": standard["content_sha256"],
        "mapped_company_count": landscape["record_count"] - unmapped_markets,
        "unmapped_market_company_count": unmapped_markets,
        "segment_market_cell_count": len(bridged_cells),
        "populated_segment_market_cell_count": populated,
        "empty_segment_market_cell_count": len(bridged_cells) - populated,
        "platform_market_lane_count": len(bridged_lanes),
        "segment_market_cells": bridged_cells,
        "platform_market_lanes": bridged_lanes,
        "generalization_gate": {
            "directory_population_is_not_signal_evidence": True,
            "recent_three_to_six_month_artifacts_required": True,
            "minimum_three_audited_companies_per_promoted_pattern": True,
            "minimum_two_distinct_channels_per_promoted_pattern": True,
            "b2b_and_b2c_patterns_must_remain_separate": True,
            "local_market_validation_required": True,
            "human_approval_required": True,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_startup_sampling_bridge(
    bridge: Mapping[str, Any], landscape: Mapping[str, Any], standard: Mapping[str, Any]
) -> None:
    unsigned = dict(bridge)
    supplied = unsigned.pop("content_sha256", None)
    if bridge.get("schema") != SAMPLING_BRIDGE_SCHEMA or supplied != _digest(unsigned):
        raise GTMStartupLandscapeError("startup sampling bridge digest or schema is invalid")
    rebuilt = compile_startup_sampling_bridge(landscape, standard)
    if rebuilt != bridge:
        raise GTMStartupLandscapeError("startup sampling bridge drifted")


POSITIONING_FRAMES: tuple[tuple[str, str], ...] = (
    ("ai_native_or_ai_for_job", r"\b(ai|artificial intelligence|machine learning)\b"),
    ("marketplace_or_network", r"\b(marketplace|network|connects?|matching)\b"),
    ("workflow_or_automation", r"\b(automat(?:e|es|ed|ing|ion)|workflow|agentic)\b"),
    ("platform_or_operating_system", r"\b(platform|operating system|infrastructure)\b"),
    ("replacement_or_displacement", r"\b(replace|replaces|replacing|instead of|alternative to)\b"),
    ("speed_cost_or_efficiency", r"\b(fast|faster|speed|cheap|cheaper|reduce|reduces|saving|saves|efficient)\b"),
    ("all_in_one_or_end_to_end", r"\b(all[- ]in[- ]one|end[- ]to[- ]end|one[- ]stop|full[- ]stack)\b"),
    ("personalized_or_adaptive", r"\b(personalized|personalised|personalization|adaptive|tailored)\b"),
    ("trust_safety_or_compliance", r"\b(trust|safe|safety|secure|security|compliance|risk|fraud)\b"),
    ("creator_expression_or_sharing", r"\b(create|creates|creator|share|story|stories|content)\b"),
    ("revenue_sales_or_growth", r"\b(revenue|sales|growth|grow|conversion|customers?)\b"),
    ("measurement_or_decision_support", r"\b(analytics|insight|measure|monitor|decision|data)\b"),
    ("access_or_democratization", r"\b(access|accessible|affordable|democratiz|everyone|anyone)\b"),
    ("human_expert_augmentation", r"\b(expert|human|team|coworker|assistant|copilot|professional)\b"),
)


def compile_startup_positioning_patterns(
    landscape: Mapping[str, Any], standard: Mapping[str, Any]
) -> dict[str, Any]:
    verify_startup_landscape(landscape)
    business_models = standard.get("business_models")
    if standard.get("schema") != "ProofLaunchGlobalOrganicSignalSamplingStandardV1" or not isinstance(business_models, dict):
        raise GTMStartupLandscapeError("organic sampling standard is invalid")
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in landscape["records"]:
        grouped[(record["business_model"], _standard_vertical(record))].append(record)
    profiles = []
    for business_model in ("b2b", "b2c"):
        for vertical in business_models[business_model]:
            records = grouped.get((business_model, vertical), [])
            tag_counts: Counter[str] = Counter()
            stage_counts: Counter[str] = Counter()
            market_counts: Counter[str] = Counter()
            frame_counts: Counter[str] = Counter()
            for record in records:
                tag_counts.update(record["tags"])
                stage_counts[record["size_stage_proxy"]] += 1
                market_counts[record["market_region"]] += 1
                text = record["one_liner"].casefold()
                for frame, pattern in POSITIONING_FRAMES:
                    if re.search(pattern, text):
                        frame_counts[frame] += 1
            profiles.append(
                {
                    "business_model": business_model,
                    "vertical": vertical,
                    "company_count": len(records),
                    "size_stage_proxy_counts": dict(sorted(stage_counts.items())),
                    "market_region_counts": dict(sorted(market_counts.items())),
                    "top_directory_tags": [
                        {"tag": tag, "company_count": count}
                        for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
                    ],
                    "positioning_frames": [
                        {
                            "frame": frame,
                            "company_count": frame_counts.get(frame, 0),
                            "share_of_vertical": round(frame_counts.get(frame, 0) / len(records), 6) if records else 0.0,
                        }
                        for frame, _ in POSITIONING_FRAMES
                    ],
                    "descriptive_status": "directory_language_distribution_only",
                    "performance_status": "not_measured",
                }
            )
    payload: dict[str, Any] = {
        "schema": POSITIONING_SCHEMA,
        "source_landscape_sha256": landscape["content_sha256"],
        "source_sampling_standard_sha256": standard["content_sha256"],
        "profile_count": len(profiles),
        "positioning_frame_count": len(POSITIONING_FRAMES),
        "profiles": profiles,
        "top_level_generalization_contract": {
            "frequency_is_not_effectiveness": True,
            "company_wording_reuse_allowed": False,
            "industry_and_business_model_profile_required": True,
            "buyer_or_user_and_switching_tension_required": True,
            "inspectable_product_proof_required": True,
            "platform_native_distribution_route_required": True,
            "activation_retention_conversion_and_revenue_chain_required": True,
            "novel_combination_must_be_checked_against_recent_competitors": True,
            "recent_signal_and_human_preference_evidence_required_before_promotion": True,
        },
        "truth_boundary": (
            "These are aggregate positioning-language distributions from directory one-liners. They describe how startups present "
            "themselves; they do not show which positioning, copy, channel, or creative caused growth."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_startup_positioning_patterns(
    patterns: Mapping[str, Any], landscape: Mapping[str, Any], standard: Mapping[str, Any]
) -> None:
    unsigned = dict(patterns)
    supplied = unsigned.pop("content_sha256", None)
    if patterns.get("schema") != POSITIONING_SCHEMA or supplied != _digest(unsigned):
        raise GTMStartupLandscapeError("startup positioning patterns digest or schema is invalid")
    rebuilt = compile_startup_positioning_patterns(landscape, standard)
    if rebuilt != patterns:
        raise GTMStartupLandscapeError("startup positioning patterns drifted")


def compile_startup_expansion_backlog(
    bridge: Mapping[str, Any], source_candidates: Sequence[Mapping[str, Any]], *, target_per_cell: int = 30
) -> dict[str, Any]:
    if bridge.get("schema") != SAMPLING_BRIDGE_SCHEMA or not isinstance(bridge.get("segment_market_cells"), list):
        raise GTMStartupLandscapeError("startup sampling bridge is invalid")
    if not isinstance(target_per_cell, int) or target_per_cell < 10:
        raise GTMStartupLandscapeError("target_per_cell must be at least ten")
    sources_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    normalized_sources = []
    source_ids = set()
    for raw in source_candidates:
        source = dict(raw)
        source_id = _clean_text(source.get("source_id"), 120)
        url = _clean_text(source.get("url"), 500)
        markets = source.get("markets")
        if not source_id or source_id in source_ids or not url.startswith("https://") or not isinstance(markets, list) or not markets:
            raise GTMStartupLandscapeError("startup expansion source is invalid")
        source_ids.add(source_id)
        if source.get("authority") not in {"official_government", "official_accelerator", "official_investor", "official_award_body", "official_product_directory"}:
            raise GTMStartupLandscapeError(f"startup expansion source authority is invalid: {source_id}")
        if source.get("collection_status") not in {"captured", "pending_structure_and_terms_audit"}:
            raise GTMStartupLandscapeError(f"startup expansion source status is invalid: {source_id}")
        source["training_eligible"] = False
        normalized_sources.append(source)
        for market in markets:
            sources_by_market[str(market)].append(source)
    backlog = []
    total_shortfall = 0
    for cell in bridge["segment_market_cells"]:
        shortfall = max(0, target_per_cell - cell["directory_company_count"])
        total_shortfall += shortfall
        priority = shortfall + (40 if cell["directory_company_count"] == 0 else 0) + (20 if cell["market"] != "north_america" else 0)
        backlog.append(
            {
                "cell_id": cell["cell_id"],
                "business_model": cell["business_model"],
                "market": cell["market"],
                "vertical": cell["vertical"],
                "current_directory_company_count": cell["directory_company_count"],
                "target_directory_company_count": target_per_cell,
                "additional_company_record_target": shortfall,
                "priority_score": priority,
                "priority_band": "p0" if priority >= 70 else "p1" if priority >= 40 else "p2",
                "candidate_source_ids": sorted(source["source_id"] for source in sources_by_market.get(cell["market"], [])),
                "completion_status": "target_met" if shortfall == 0 else "collection_required",
                "recent_signal_and_growth_case_status": "not_satisfied_by_directory_expansion",
            }
        )
    backlog.sort(key=lambda item: (-item["priority_score"], item["market"], item["business_model"], item["vertical"]))
    market_shortfalls: Counter[str] = Counter()
    for item in backlog:
        market_shortfalls[item["market"]] += item["additional_company_record_target"]
    payload: dict[str, Any] = {
        "schema": EXPANSION_BACKLOG_SCHEMA,
        "source_bridge_sha256": bridge["content_sha256"],
        "target_per_segment_market_cell": target_per_cell,
        "segment_market_cell_count": len(backlog),
        "additional_company_record_target": total_shortfall,
        "market_shortfall_counts": dict(sorted(market_shortfalls.items())),
        "priority_band_counts": dict(sorted(Counter(item["priority_band"] for item in backlog).items())),
        "source_candidates": sorted(normalized_sources, key=lambda item: item["source_id"]),
        "backlog": backlog,
        "completion_gate": {
            "directory_record_deduplication_required": True,
            "official_source_provenance_required": True,
            "source_terms_and_access_audit_required": True,
            "directory_record_is_not_growth_case": True,
            "recent_signal_collection_remains_separate": True,
            "training_promotion_allowed": False,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_startup_expansion_backlog(
    backlog: Mapping[str, Any], bridge: Mapping[str, Any], source_candidates: Sequence[Mapping[str, Any]]
) -> None:
    unsigned = dict(backlog)
    supplied = unsigned.pop("content_sha256", None)
    if backlog.get("schema") != EXPANSION_BACKLOG_SCHEMA or supplied != _digest(unsigned):
        raise GTMStartupLandscapeError("startup expansion backlog digest or schema is invalid")
    rebuilt = compile_startup_expansion_backlog(
        bridge, source_candidates, target_per_cell=backlog["target_per_segment_market_cell"]
    )
    if rebuilt != backlog:
        raise GTMStartupLandscapeError("startup expansion backlog drifted")
