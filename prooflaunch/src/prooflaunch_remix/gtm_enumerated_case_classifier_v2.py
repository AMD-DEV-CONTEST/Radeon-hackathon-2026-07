from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from .gtm_public_source_capture import verify_public_source_capture


SCHEMA = "ProofLaunchGTMEnumeratedCaseClassificationV2"


class GTMEnumeratedCaseClassificationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _rule(rule_id: str, route: str, phrases: Sequence[str]) -> dict[str, Any]:
    return {"rule_id": rule_id, "route": route, "phrases": tuple(phrases)}


# These phrases describe the featured business itself, not merely a tool or tactic it used.
# Generic nouns such as "bank", "restaurant", "marketplace", "payments", "AI", and
# "retailer" are deliberately excluded because vendor customer stories use them in solution
# descriptions and would otherwise misroute the subject company.
SUBJECT_PHRASE_RULES = (
    _rule("agency_subject", "b2b.professional_services.agency_services", ("marketing agency", "digital agency", "creative agency", "advertising agency")),
    _rule("legal_subject", "b2b.professional_services.legal_accounting", ("law firm", "legal practice", "accounting firm", "bookkeeping firm", "audit firm")),
    _rule("staffing_subject", "b2b.professional_services.managed_and_field_services", ("staffing firm", "recruitment firm", "recruiting firm", "field services company")),
    _rule("manufacturer_subject", "b2b.industrial_climate.manufacturing", ("industrial manufacturer", "global manufacturer", "manufacturing company", "components manufacturer", "materials manufacturer", "packaging manufacturer")),
    _rule("equipment_subject", "b2b.industrial_climate.industrial_equipment", ("industrial equipment manufacturer", "machinery manufacturer", "industrial automation company", "robotics manufacturer")),
    _rule("engineering_subject", "b2b.industrial_climate.engineering_construction", ("engineering firm", "construction company", "construction contractor", "architecture firm", "infrastructure contractor")),
    _rule("commercial_property_subject", "b2b.industrial_climate.commercial_real_estate", ("commercial real estate firm", "commercial property company", "commercial property manager")),
    _rule("energy_subject", "b2b.industrial_climate.energy_climate", ("renewable energy company", "clean energy company", "climate technology company", "electric utility company")),
    _rule("provider_subject", "b2b.healthcare_life_sciences.provider", ("health system", "hospital network", "hospital group", "dental group", "clinic network", "care provider")),
    _rule("biotech_subject", "b2b.healthcare_life_sciences.biotechnology", ("biotech company", "biotechnology company", "genomics company", "life sciences company")),
    _rule("medical_device_subject", "b2b.healthcare_life_sciences.medical_devices", ("medical device company", "medical device manufacturer", "medical equipment company")),
    _rule("health_ops_subject", "b2b.healthcare_life_sciences.healthcare_operations", ("healthcare operations platform", "patient scheduling platform", "healthcare administration platform")),
    _rule("business_banking_subject", "b2b.fintech_regtech.banking", ("business banking platform", "commercial lending platform", "small business lender")),
    _rule("commercial_insurance_subject", "b2b.fintech_regtech.insurance", ("commercial insurance platform", "commercial insurer", "insurance broker platform")),
    _rule("regtech_subject", "b2b.fintech_regtech.regulatory_technology", ("regtech platform", "regulatory technology company", "compliance automation platform")),
    _rule("developer_subject", "b2b.developer_tools.application_development", ("developer platform", "developer tools company", "application development platform", "app development platform")),
    _rule("devops_subject", "b2b.developer_tools.devops_observability", ("observability platform", "devops platform", "incident response platform", "cloud operations platform")),
    _rule("testing_subject", "b2b.developer_tools.testing_quality", ("software testing platform", "test automation platform", "quality assurance platform")),
    _rule("open_source_subject", "b2b.developer_tools.open_source_infrastructure", ("open-source infrastructure company", "open source infrastructure company", "open-source developer platform")),
    _rule("foundation_model_subject", "b2b.ai_data_infrastructure.foundation_model_tools", ("foundation model platform", "generative ai platform", "llm platform", "ai agent platform")),
    _rule("data_subject", "b2b.ai_data_infrastructure.data_platforms", ("enterprise data platform", "data warehouse platform", "data integration platform", "database company")),
    _rule("analytics_subject", "b2b.ai_data_infrastructure.analytics_bi", ("business intelligence platform", "analytics platform", "decision intelligence platform")),
    _rule("mlops_subject", "b2b.ai_data_infrastructure.mlops_and_inference", ("mlops platform", "model serving platform", "inference platform")),
    _rule("identity_subject", "b2b.cybersecurity.identity", ("identity security platform", "identity management platform", "authentication platform")),
    _rule("appsec_subject", "b2b.cybersecurity.application_security", ("application security platform", "appsec platform", "code security platform")),
    _rule("cloud_security_subject", "b2b.cybersecurity.cloud_security", ("cloud security platform", "cloud workload security platform")),
    _rule("grc_subject", "b2b.cybersecurity.governance_risk_compliance", ("grc platform", "security compliance platform", "audit readiness platform")),
    _rule("collaboration_subject", "b2b.b2b_saas.collaboration", ("collaboration platform", "project management platform", "team communication platform")),
    _rule("finance_ops_subject", "b2b.b2b_saas.finance_operations", ("spend management platform", "expense management platform", "financial operations platform", "procurement platform")),
    _rule("commerce_enablement_subject", "b2b.martech_sales_tech.commerce_enablement", ("commerce enablement platform", "ecommerce platform for brands", "merchant commerce platform")),
    _rule("revenue_intelligence_subject", "b2b.martech_sales_tech.revenue_intelligence", ("revenue intelligence platform", "sales intelligence platform", "conversation intelligence platform")),
    _rule("talent_subject", "b2b.hr_future_of_work.talent", ("recruiting platform", "talent platform", "applicant tracking platform", "hiring platform")),
    _rule("workforce_subject", "b2b.hr_future_of_work.workforce_operations", ("workforce management platform", "payroll platform", "employee benefits platform")),
    _rule("enterprise_learning_subject", "b2b.hr_future_of_work.learning", ("corporate learning platform", "employee training platform", "learning management platform")),
    _rule("employee_experience_subject", "b2b.hr_future_of_work.employee_experience", ("employee experience platform", "employee engagement platform", "employee recognition platform")),
    _rule("consumer_investing_subject", "b2c.personal_finance.investing", ("investing app", "consumer investment platform", "personal investing platform")),
    _rule("consumer_insurance_subject", "b2c.personal_finance.insurance", ("pet insurance company", "personal insurance company", "consumer insurer")),
    _rule("consumer_budget_subject", "b2c.personal_finance.credit_and_budgeting", ("budgeting app", "credit building app", "personal finance app")),
    _rule("fitness_subject", "b2c.health_wellness.fitness", ("fitness app", "fitness brand", "workout app", "fitness platform")),
    _rule("nutrition_subject", "b2c.health_wellness.nutrition", ("nutrition app", "nutrition platform", "meal planning app")),
    _rule("wellbeing_subject", "b2c.health_wellness.mental_wellbeing_nonclinical", ("meditation app", "mindfulness app", "sleep app", "mental wellbeing app")),
    _rule("care_navigation_subject", "b2c.health_wellness.care_navigation", ("care navigation platform", "doctor search platform", "patient navigation app")),
    _rule("language_subject", "b2c.education_language.language_learning", ("language learning app", "language learning platform")),
    _rule("tutoring_subject", "b2c.education_language.tutoring", ("tutoring platform", "online tutoring company", "test preparation platform")),
    _rule("skills_subject", "b2c.education_language.skills", ("online course platform", "skills training platform", "coding bootcamp")),
    _rule("family_learning_subject", "b2c.education_language.family_learning", ("family learning app", "children's learning platform", "k-12 learning platform")),
    _rule("mobile_game_subject", "b2c.gaming_entertainment.mobile_games", ("mobile game studio", "mobile gaming company", "mobile game publisher")),
    _rule("pc_console_subject", "b2c.gaming_entertainment.pc_console", ("console game studio", "pc game studio", "video game publisher")),
    _rule("streaming_subject", "b2c.gaming_entertainment.streaming", ("video streaming service", "music streaming service", "streaming platform")),
    _rule("fan_subject", "b2c.gaming_entertainment.fan_communities", ("fan community platform", "sports fan platform", "fandom platform")),
    _rule("general_ecommerce_subject", "b2c.commerce_marketplaces.general_ecommerce", ("ecommerce brand", "e-commerce brand", "online retail brand")),
    _rule("local_marketplace_subject", "b2c.commerce_marketplaces.local_marketplaces", ("local marketplace", "neighborhood marketplace")),
    _rule("home_subject", "b2c.commerce_marketplaces.home_property", ("home improvement brand", "furniture brand", "home furnishings brand", "residential property marketplace")),
    _rule("services_marketplace_subject", "b2c.commerce_marketplaces.services_marketplaces", ("services marketplace", "freelance marketplace", "task marketplace")),
    _rule("beauty_subject", "b2c.beauty_fashion.beauty", ("beauty brand", "skincare brand", "cosmetics brand", "haircare brand", "fragrance brand")),
    _rule("apparel_subject", "b2c.beauty_fashion.apparel", ("fashion brand", "apparel brand", "clothing brand", "footwear brand")),
    _rule("luxury_subject", "b2c.beauty_fashion.luxury", ("luxury brand", "luxury jewelry brand", "designer fashion brand")),
    _rule("resale_subject", "b2c.beauty_fashion.resale", ("re-commerce app", "recommerce app", "resale platform", "second-hand marketplace")),
    _rule("food_subject", "b2c.food_beverage.consumer_packaged_goods", ("food brand", "beverage brand", "snack brand", "coffee brand", "grocery brand")),
    _rule("restaurant_subject", "b2c.food_beverage.restaurants", ("restaurant chain", "restaurant brand", "restaurant group", "coffee shop chain")),
    _rule("delivery_subject", "b2c.food_beverage.delivery", ("food delivery platform", "meal delivery service", "grocery delivery platform")),
    _rule("functional_food_subject", "b2c.food_beverage.functional_food", ("nutrition brand", "supplement brand", "sports nutrition brand", "functional beverage brand")),
    _rule("destination_subject", "b2c.travel_hospitality.destinations", ("tourism board", "destination marketing organization", "destination marketing company")),
    _rule("lodging_subject", "b2c.travel_hospitality.lodging", ("hotel group", "hotel brand", "resort group", "vacation rental platform")),
    _rule("transport_subject", "b2c.travel_hospitality.transport", ("airline group", "airline company", "ride-hailing app", "mobility app")),
    _rule("experience_subject", "b2c.travel_hospitality.experiences", ("tour operator", "travel experiences platform", "activities marketplace")),
    _rule("creator_subject", "b2c.creator_productivity.creator_tools", ("creator platform", "creator tools company", "newsletter platform")),
    _rule("productivity_subject", "b2c.creator_productivity.focus_productivity", ("productivity app", "note-taking app", "personal knowledge app", "focus app")),
    _rule("audio_video_subject", "b2c.creator_productivity.audio_video", ("video editing platform", "audio editing platform", "podcast platform", "recording platform")),
    _rule("independent_business_subject", "b2c.creator_productivity.independent_business", ("small business platform", "appointment booking platform", "independent business platform")),
)


def _verify_delta_seal(delta: Mapping[str, Any]) -> None:
    unsigned = dict(delta)
    supplied = unsigned.pop("content_sha256", None)
    if delta.get("schema") != "ProofLaunchGTMDiscoveryDeltaV2" or supplied != _digest(unsigned):
        raise GTMEnumeratedCaseClassificationError("discovery delta seal is invalid")


def _matched_phrases(surface: str, phrases: Sequence[str]) -> list[str]:
    lowered = surface.casefold()
    result = []
    for phrase in phrases:
        pattern = rf"(?<![a-z0-9]){re.escape(phrase.casefold())}(?![a-z0-9])"
        if re.search(pattern, lowered):
            result.append(phrase)
    return result


_COMPANY_SLUG_STOP_TOKENS = {
    "bfcm", "case", "customer", "drives", "email", "growth", "marketing", "multichannel",
    "omnichannel", "predictive", "retention", "revenue", "sidekick", "sms", "success", "tiktok",
}
_GENERIC_COMPANY_CANDIDATES = {
    "beauty brand", "coffee", "coffee brand", "ecommerce brand", "fashion ecommerce brand",
    "fitness app", "nutrition app", "restaurant brand", "streaming platform",
}


def _company_candidate(source_url: str) -> str:
    slug = urlsplit(source_url).path.rstrip("/").rsplit("/", 1)[-1]
    tokens = [token for token in re.split(r"[-_]+", slug) if token]
    kept: list[str] = []
    for token in tokens:
        if kept and token.casefold() in _COMPANY_SLUG_STOP_TOKENS:
            break
        kept.append(token)
    candidate = " ".join(kept).strip().title()
    if candidate.casefold() in _GENERIC_COMPANY_CANDIDATES or len(candidate) < 2:
        return ""
    return candidate[:160]


def classify_enumerated_cases(
    delta: Mapping[str, Any],
    public_capture: Mapping[str, Any],
    allowed_subverticals: set[str],
) -> dict[str, Any]:
    _verify_delta_seal(delta)
    verify_public_source_capture(public_capture)
    if any(rule["route"] not in allowed_subverticals for rule in SUBJECT_PHRASE_RULES):
        raise GTMEnumeratedCaseClassificationError("a subject phrase rule references an unknown subvertical")
    captures = {str(row["source_url"]): row for row in public_capture["records"]}
    suggestions: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for lead in delta["records"]:
        capture = captures.get(str(lead["source_url"]))
        if capture is None or capture.get("capture_status") != "captured_metadata_only":
            gaps.append({
                "lead_id": lead["lead_id"],
                "source_url": lead["source_url"],
                "status": "public_capture_gap",
                "candidate_routes": [],
                "formal_candidate_quota_credit": 0,
                "automatic_promotion_allowed": False,
            })
            continue
        surface = " ".join((str(capture.get("title") or ""), str(capture.get("description") or "")))
        matches = []
        for rule in SUBJECT_PHRASE_RULES:
            phrases = _matched_phrases(surface, rule["phrases"])
            if phrases:
                matches.append({
                    "rule_id": rule["rule_id"],
                    "subvertical_id": rule["route"],
                    "matched_subject_phrases": phrases,
                })
        routes = sorted({row["subvertical_id"] for row in matches})
        if len(routes) != 1:
            gaps.append({
                "lead_id": lead["lead_id"],
                "source_url": lead["source_url"],
                "status": "classification_gap" if not matches else "ambiguous_route_conflict",
                "candidate_routes": matches[:8],
                "formal_candidate_quota_credit": 0,
                "automatic_promotion_allowed": False,
            })
            continue
        evidence = sorted({phrase for row in matches for phrase in row["matched_subject_phrases"]})
        winner_rules = sorted(row["rule_id"] for row in matches if row["subvertical_id"] == routes[0])
        suggestions.append({
            "lead_id": lead["lead_id"],
            "source_url": lead["source_url"],
            "source_family_ids": lead["source_family_ids"],
            "discovery_method": "model_assisted_public_search_result",
            "company": _company_candidate(str(lead["source_url"])),
            "title": str(capture.get("title") or lead["title"]),
            "directory_industry": "public_case_metadata_strong_subject_phrase",
            "source_excerpt": (
                f"High-precision provisional subject route {routes[0]} from exact metadata phrases {evidence!r}; "
                f"capture receipt {capture['content_sha256']}. Vendor/platform claims remain non-independent and "
                "named human identity, episode, budget, outcome and deduplication review is required."
            ),
            "provisional_subvertical_ids": routes,
            "routing_rule_ids": winner_rules,
            "routing_subject_phrases": evidence,
            "routing_capture_sha256": capture["content_sha256"],
            "routing_confidence": "high_precision_subject_phrase_provisional",
            "human_classification_required": True,
            "formal_candidate_quota_credit": 0,
            "automatic_promotion_allowed": False,
        })
    suggestions.sort(key=lambda row: row["lead_id"])
    gaps.sort(key=lambda row: row["lead_id"])
    route_counts = Counter(row["provisional_subvertical_ids"][0] for row in suggestions)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_delta_sha256": delta["content_sha256"],
        "public_capture_sha256": public_capture["content_sha256"],
        "input_count": len(delta["records"]),
        "provisional_route_suggestion_count": len(suggestions),
        "classification_gap_count": len(gaps),
        "represented_subvertical_count": len(route_counts),
        "route_counts": dict(sorted(route_counts.items())),
        "records": suggestions,
        "rejected_records": gaps,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": (
            "Only exact, strong phrases describing the featured business are eligible for provisional exclusive-primary "
            "routing. Generic vendor solution nouns are excluded. Routes remain vendor/platform-attributed discovery cues, "
            "not independent outcome evidence or formal candidate credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_enumerated_case_classification(
    payload: Mapping[str, Any],
    delta: Mapping[str, Any],
    public_capture: Mapping[str, Any],
    allowed_subverticals: set[str],
) -> None:
    _verify_delta_seal(delta)
    verify_public_source_capture(public_capture)
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMEnumeratedCaseClassificationError("enumerated case classification seal is invalid")
    if payload.get("source_delta_sha256") != delta.get("content_sha256"):
        raise GTMEnumeratedCaseClassificationError("classification is stale against discovery delta")
    if payload.get("public_capture_sha256") != public_capture.get("content_sha256"):
        raise GTMEnumeratedCaseClassificationError("classification is stale against public capture")
    records, rejected = payload.get("records"), payload.get("rejected_records")
    if not isinstance(records, list) or not isinstance(rejected, list):
        raise GTMEnumeratedCaseClassificationError("classification partitions are malformed")
    if payload.get("input_count") != len(delta["records"]) or len(records) + len(rejected) != len(delta["records"]):
        raise GTMEnumeratedCaseClassificationError("classification coverage aggregate drifted")
    ids = [row.get("lead_id") for row in records + rejected]
    expected_ids = {row["lead_id"] for row in delta["records"]}
    if len(ids) != len(set(ids)) or set(ids) != expected_ids:
        raise GTMEnumeratedCaseClassificationError("classification input partition drifted")
    if payload.get("formal_candidate_quota_credit") != 0 or payload.get("automatic_promotion_allowed") is not False:
        raise GTMEnumeratedCaseClassificationError("classification escaped zero-credit mode")
    for row in records:
        routes = row.get("provisional_subvertical_ids")
        if (
            not isinstance(routes, list)
            or len(routes) != 1
            or routes[0] not in allowed_subverticals
            or row.get("routing_confidence") != "high_precision_subject_phrase_provisional"
            or not row.get("routing_subject_phrases")
            or row.get("human_classification_required") is not True
            or row.get("formal_candidate_quota_credit") != 0
            or row.get("automatic_promotion_allowed") is not False
        ):
            raise GTMEnumeratedCaseClassificationError("a route suggestion escaped provisional review")
    if any(row.get("formal_candidate_quota_credit") != 0 for row in rejected):
        raise GTMEnumeratedCaseClassificationError("a rejected record minted candidate credit")


__all__ = [
    "GTMEnumeratedCaseClassificationError",
    "SUBJECT_PHRASE_RULES",
    "classify_enumerated_cases",
    "verify_enumerated_case_classification",
]
