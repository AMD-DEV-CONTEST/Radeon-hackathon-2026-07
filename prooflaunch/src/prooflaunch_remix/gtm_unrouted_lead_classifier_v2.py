from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_all_subvertical_discovery_v2 import verify_all_subvertical_discovery
from .gtm_public_source_capture import verify_public_source_capture


SCHEMA = "ProofLaunchGTMUnroutedLeadClassificationV2"


class GTMUnroutedLeadClassificationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _rule(rule_id: str, route: str, industries: Sequence[str], terms: Sequence[str]) -> dict[str, Any]:
    return {"rule_id": rule_id, "route": route, "industries": tuple(industries), "terms": tuple(terms)}


# These rules intentionally optimize precision over coverage. A directory industry is never
# sufficient on its own except for narrowly bounded licensed professions. Every other route
# requires a category-specific lexical signal in the company/title/URL surface.
RULES = (
    _rule("agency_explicit", "b2b.professional_services.agency_services", ("Marketing & Advertising",), ("agency", "marketer", "marketing partner", "digital marketing", "inboundcycle")),
    _rule("legal_profession", "b2b.professional_services.legal_accounting", ("Legal Services",), ("legal services", "law firm", "legal practice")),
    _rule("accounting_profession", "b2b.professional_services.legal_accounting", ("Banking & Financial Services", "Software & Technology"), ("accounting", "bookkeeping", "tax practice", "audit firm")),
    _rule("staffing_service", "b2b.professional_services.managed_and_field_services", ("Staffing and Recruiting",), ("staffing", "recruiting firm", "recruitment firm", "talent agency")),
    _rule("manufactured_goods", "b2b.industrial_climate.manufacturing", ("industrial_case_directory", "industrial_b2b", "Chemical & Biotechnology"), ("manufacturer", "manufacturing", "components", "materials", "plastics", "chemical", "food industry", "packaging")),
    _rule("industrial_equipment", "b2b.industrial_climate.industrial_equipment", ("industrial_case_directory", "industrial_b2b", "Software & Technology"), ("machinery", "industrial machine", "capital equipment", "industrial equipment", "instrumentation", "industrial automation", "robotics", "hvac", "pump", "valve")),
    _rule("engineering_projects", "b2b.industrial_climate.engineering_construction", ("industrial_case_directory", "industrial_b2b", "Software & Technology"), ("engineering", "construction", "contractor", "architecture", "infrastructure project")),
    _rule("commercial_property", "b2b.industrial_climate.commercial_real_estate", ("Software & Technology", "Consumer Services", "Home"), ("commercial real estate", "commercial property", "workplace leasing", "property management")),
    _rule("energy_enterprise", "b2b.industrial_climate.energy_climate", ("Energy & Utilities", "industrial_case_directory", "Software & Technology"), ("energy", "utility", "carbon", "climate", "solar", "grid", "electrification", "decarbon")),
    _rule("health_provider", "b2b.healthcare_life_sciences.provider", ("Healthcare",), ("hospital", "clinic", "dental", "dentist", "health system", "patient care", "care provider")),
    _rule("biotechnology", "b2b.healthcare_life_sciences.biotechnology", ("Healthcare", "Chemical & Biotechnology", "Software & Technology"), ("biotech", "therapeutic", "genomic", "laboratory", "diagnostic research", "life science")),
    _rule("medical_device", "b2b.healthcare_life_sciences.medical_devices", ("Healthcare", "industrial_case_directory"), ("medical device", "clinical device", "surgical device", "medical equipment")),
    _rule("healthcare_operations", "b2b.healthcare_life_sciences.healthcare_operations", ("Healthcare", "Software & Technology"), ("revenue cycle", "patient scheduling", "healthcare operations", "health data", "care administration", "health benefits")),
    _rule("finance_ops", "b2b.b2b_saas.finance_operations", ("Software & Technology", "Banking & Financial Services", "Human Resources"), ("accounting software", "cash flow", "cashflow", "expense management", "spend management", "financial close", "treasury", "payroll software", "procurement")),
    _rule("vertical_saas_explicit", "b2b.b2b_saas.vertical_saas", ("Software & Technology", "Consumer Services", "Healthcare"), ("salon owner", "dental software", "restaurant platform", "property management software", "legal practice software")),
    _rule("business_payments", "b2b.fintech_regtech.payments", ("Banking & Financial Services", "Software & Technology", "Ecommerce"), ("payment", "merchant", "checkout", "cardup", "payplug", "money movement", "payment acceptance")),
    _rule("business_banking", "b2b.fintech_regtech.banking", ("Banking & Financial Services",), ("sme lending", "business lending", "business banking", "working capital", "business finance", "commercial lending")),
    _rule("commercial_insurance", "b2b.fintech_regtech.insurance", ("Insurance", "Banking & Financial Services"), ("commercial insurance", "insurance broker", "underwriting platform", "claims platform")),
    _rule("regtech", "b2b.fintech_regtech.regulatory_technology", ("Banking & Financial Services", "Software & Technology", "Cybersecurity"), ("regtech", "regulatory", "compliance automation", "aml", "kyc", "transaction monitoring")),
    _rule("developer_app_build", "b2b.developer_tools.application_development", ("Software & Technology",), ("developer platform", "api development", "app builder", "software development", "developer tool", "ide")),
    _rule("devops_observability", "b2b.developer_tools.devops_observability", ("Software & Technology", "Cybersecurity"), ("devops", "observability", "monitoring", "incident response", "deployment", "cloud operations", "site reliability")),
    _rule("software_testing", "b2b.developer_tools.testing_quality", ("Software & Technology",), ("software testing", "test automation", "quality assurance", "qa platform", "accessibility testing")),
    _rule("open_source_gtm", "b2b.developer_tools.open_source_infrastructure", ("Software & Technology",), ("open source", "opensource", "developer community")),
    _rule("foundation_model_tools", "b2b.ai_data_infrastructure.foundation_model_tools", ("Software & Technology",), ("foundation model", "generative ai platform", "llm", "ai agent platform", "prompt evaluation")),
    _rule("data_platform", "b2b.ai_data_infrastructure.data_platforms", ("Software & Technology",), ("data platform", "data warehouse", "database", "data integration", "data catalog", "etl", "data governance")),
    _rule("analytics_bi", "b2b.ai_data_infrastructure.analytics_bi", ("Software & Technology",), ("business intelligence", "analytics platform", "revenue analytics", "data analytics", "decision intelligence")),
    _rule("mlops_inference", "b2b.ai_data_infrastructure.mlops_and_inference", ("Software & Technology",), ("mlops", "model serving", "inference", "machine learning operations", "model monitoring")),
    _rule("identity_security", "b2b.cybersecurity.identity", ("Cybersecurity", "Software & Technology"), ("identity security", "authentication", "authorization", "privileged access", "identity governance", "single sign-on")),
    _rule("application_security", "b2b.cybersecurity.application_security", ("Cybersecurity", "Software & Technology"), ("application security", "appsec", "software supply chain", "code security", "api security")),
    _rule("cloud_security", "b2b.cybersecurity.cloud_security", ("Cybersecurity", "Software & Technology"), ("cloud security", "cloud workload", "cloud posture", "runtime security")),
    _rule("grc_security", "b2b.cybersecurity.governance_risk_compliance", ("Cybersecurity", "Software & Technology"), ("governance risk compliance", "grc", "security compliance", "audit readiness", "vendor risk", "trust center")),
    _rule("collaboration", "b2b.b2b_saas.collaboration", ("Software & Technology",), ("collaboration platform", "project management software", "team communication platform", "document workflow platform", "meeting platform", "knowledge management platform")),
    _rule("commerce_enablement", "b2b.martech_sales_tech.commerce_enablement", ("Software & Technology", "Ecommerce"), ("ecommerce platform", "commerce platform", "merchant platform", "dropshipping", "marketplace seller", "retail technology")),
    _rule("revenue_intelligence", "b2b.martech_sales_tech.revenue_intelligence", ("Software & Technology",), ("revenue intelligence", "sales intelligence", "conversation intelligence", "sales forecasting")),
    _rule("talent_technology", "b2b.hr_future_of_work.talent", ("Human Resources", "Staffing and Recruiting", "Software & Technology"), ("recruiting platform", "talent platform", "applicant tracking", "candidate assessment", "hiring platform")),
    _rule("workforce_operations", "b2b.hr_future_of_work.workforce_operations", ("Human Resources", "Software & Technology"), ("payroll", "workforce management", "time and attendance", "employee benefits", "staff scheduling")),
    _rule("enterprise_learning", "b2b.hr_future_of_work.learning", ("Education", "Human Resources", "Software & Technology"), ("employee training", "workforce learning", "corporate learning", "sales training", "learning management")),
    _rule("employee_experience", "b2b.hr_future_of_work.employee_experience", ("Human Resources", "Healthcare", "Software & Technology"), ("employee engagement platform", "employee wellbeing platform", "workplace experience platform", "employee recognition platform")),
    _rule("consumer_banking", "b2c.personal_finance.banking", ("Banking & Financial Services",), ("personal banking", "consumer bank", "savings account", "debit card", "mobile banking")),
    _rule("consumer_investing", "b2c.personal_finance.investing", ("Banking & Financial Services",), ("investing", "brokerage", "wealth app", "trading app", "portfolio")),
    _rule("consumer_insurance", "b2c.personal_finance.insurance", ("Insurance",), ("personal insurance", "consumer insurance", "life insurance", "pet insurance", "home insurance")),
    _rule("consumer_budgeting", "b2c.personal_finance.credit_and_budgeting", ("Banking & Financial Services", "Software & Technology"), ("credit score", "credit building", "budgeting", "debt management", "personal finance app")),
    _rule("consumer_fitness", "b2c.health_wellness.fitness", ("Consumer Services", "Healthcare", "Software & Technology"), ("fitness", "workout", "training app", "gym", "exercise", "recovery")),
    _rule("consumer_nutrition", "b2c.health_wellness.nutrition", ("Consumer Services", "Healthcare", "Software & Technology"), ("nutrition", "meal planning", "diet app", "calorie", "food tracking")),
    _rule("consumer_wellbeing", "b2c.health_wellness.mental_wellbeing_nonclinical", ("Consumer Services", "Healthcare", "Software & Technology"), ("mindfulness", "meditation", "sleep app", "stress management app")),
    _rule("care_navigation", "b2c.health_wellness.care_navigation", ("Healthcare", "Consumer Services", "Software & Technology"), ("find care", "care navigation", "doctor search", "healthcare access", "patient navigation")),
    _rule("language_learning", "b2c.education_language.language_learning", ("Education", "Software & Technology"), ("language learning", "learn english", "learn spanish", "language app")),
    _rule("consumer_tutoring", "b2c.education_language.tutoring", ("Education",), ("tutoring", "tutor", "test prep", "academic support")),
    _rule("consumer_skills", "b2c.education_language.skills", ("Education", "Consumer Services"), ("online course", "skills training", "professional course", "coding bootcamp", "career course", "institute of fitness")),
    _rule("family_learning", "b2c.education_language.family_learning", ("Education",), ("student enrollment", "children learning", "parent learning", "home learning", "k-12")),
    _rule("mobile_game", "b2c.gaming_entertainment.mobile_games", ("Gaming", "Software & Technology"), ("mobile game", "gaming app", "android game", "ios game")),
    _rule("pc_console_game", "b2c.gaming_entertainment.pc_console", ("Gaming",), ("pc game", "console game", "playstation", "xbox", "steam game")),
    _rule("streaming_media", "b2c.gaming_entertainment.streaming", ("Media & Communications", "Consumer Services", "Software & Technology"), ("streaming service", "video streaming", "music streaming", "podcast network")),
    _rule("fan_community", "b2c.gaming_entertainment.fan_communities", ("Sports", "Media & Communications", "Gaming"), ("fan", "sports club", "creator community", "fandom", "collectibles")),
    _rule("general_ecommerce", "b2c.commerce_marketplaces.general_ecommerce", ("Ecommerce", "E-commerce", "Retail"), ("online retailer", "online store", "ecommerce brand", "e-commerce brand", "retail brand")),
    _rule("local_marketplace", "b2c.commerce_marketplaces.local_marketplaces", ("Consumer Services", "Software & Technology"), ("local marketplace", "neighborhood marketplace", "local community app")),
    _rule("home_property", "b2c.commerce_marketplaces.home_property", ("Home", "Consumer Services", "Ecommerce", "Energy & Utilities"), ("home improvement", "furniture", "residential property", "home marketplace", "moving service", "homeowner")),
    _rule("services_marketplace", "b2c.commerce_marketplaces.services_marketplaces", ("Consumer Services", "Software & Technology"), ("services marketplace", "freelance marketplace", "task marketplace", "book a professional")),
    _rule("beauty", "b2c.beauty_fashion.beauty", ("Consumer Services", "Ecommerce", "Retail"), ("beauty brand", "skincare", "cosmetics", "haircare", "fragrance")),
    _rule("apparel", "b2c.beauty_fashion.apparel", ("Retail", "Ecommerce", "E-commerce"), ("apparel", "clothing", "footwear", "fashion brand")),
    _rule("luxury", "b2c.beauty_fashion.luxury", ("Fashion & luxury", "Retail", "Ecommerce"), ("luxury", "jewelry", "heritage fashion", "designer fashion")),
    _rule("resale", "b2c.beauty_fashion.resale", ("Retail", "Ecommerce", "E-commerce"), ("resale", "secondhand", "consignment", "recommerce", "fashion rental")),
    _rule("packaged_food", "b2c.food_beverage.consumer_packaged_goods", ("Ecommerce", "Retail", "Consumer Services"), ("food brand", "beverage brand", "packaged food", "snack brand", "grocery brand")),
    _rule("restaurant", "b2c.food_beverage.restaurants", ("Consumer Services", "Ecommerce"), ("restaurant", "cafe", "dining", "foodservice")),
    _rule("food_delivery", "b2c.food_beverage.delivery", ("Consumer Services", "Software & Technology", "Logistics"), ("food delivery", "grocery delivery", "meal delivery", "restaurant delivery")),
    _rule("functional_food", "b2c.food_beverage.functional_food", ("Healthcare", "Ecommerce", "Consumer Services"), ("functional food", "protein", "supplement", "wellness beverage", "sports nutrition")),
    _rule("destination", "b2c.travel_hospitality.destinations", ("Consumer Services", "Marketing & Advertising"), ("tourism", "destination", "visit ", "city marketing")),
    _rule("lodging", "b2c.travel_hospitality.lodging", ("Consumer Services", "Software & Technology"), ("hotel", "resort", "hostel", "vacation rental", "lodging")),
    _rule("travel_transport", "b2c.travel_hospitality.transport", ("Automotive & Transportation", "Consumer Services", "Software & Technology"), ("airline", "rail", "mobility app", "ride hailing", "travel transport")),
    _rule("travel_experience", "b2c.travel_hospitality.experiences", ("Consumer Services", "Events"), ("tour operator", "travel experience", "activities marketplace", "attraction", "guided tour")),
    _rule("creator_tools", "b2c.creator_productivity.creator_tools", ("Software & Technology", "Media & Communications"), ("creator platform", "creator tool", "newsletter platform", "audience monetization", "creator economy")),
    _rule("focus_productivity", "b2c.creator_productivity.focus_productivity", ("Software & Technology", "Consumer Services"), ("productivity app", "focus app", "note-taking", "personal knowledge", "habit app", "task app")),
    _rule("audio_video_tool", "b2c.creator_productivity.audio_video", ("Software & Technology", "Media & Communications"), ("video editor", "audio editor", "podcast tool", "recording platform", "transcription", "livestream tool")),
    _rule("independent_business", "b2c.creator_productivity.independent_business", ("Software & Technology", "Consumer Services", "Ecommerce"), ("small business platform", "solo business", "freelancer business", "appointment booking", "independent business")),
)


def _matched_terms(text: str, terms: Sequence[str]) -> list[str]:
    lowered = text.casefold()
    matched = []
    for term in terms:
        normalized = term.casefold().strip()
        pattern = rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])"
        if re.search(pattern, lowered):
            matched.append(term)
    return matched


def _definition_supported_terms(description: str, terms: Sequence[str]) -> list[str]:
    """Accept metadata-only terms only when the sentence defines the subject's offer.

    Case-study descriptions often mention the software or payment mechanism the featured
    company used. Requiring a local definitional construction prevents those tools from being
    mistaken for the featured company's own primary product.
    """
    lowered = description.casefold()
    supported = []
    suffix = r"(?:company|firm|agency|provider|platform|software|service|system|brand|manufacturer|marketplace|app)"
    for term in terms:
        normalized = term.casefold().strip()
        escaped = re.escape(normalized)
        patterns = (
            rf"(?<![a-z0-9]){escaped}(?![a-z0-9])\s+{suffix}",
            rf"(?:is|are|offers|provides|builds|operates|runs)\s+(?:an?\s+|the\s+)?[^.!?]{{0,60}}(?<![a-z0-9]){escaped}(?![a-z0-9])",
        )
        if any(re.search(pattern, lowered) for pattern in patterns):
            supported.append(term)
    return supported


def classify_unrouted_leads(
    discovery: Mapping[str, Any],
    allowed_subverticals: set[str],
    public_capture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_all_subvertical_discovery(discovery)
    if public_capture is not None:
        verify_public_source_capture(public_capture)
    captures = {row["source_url"]: row for row in (public_capture or {}).get("records", [])}
    if any(rule["route"] not in allowed_subverticals for rule in RULES):
        raise GTMUnroutedLeadClassificationError("a routing rule references an unknown subvertical")
    suggestions: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for lead in discovery["records"]:
        if lead["provisional_subvertical_ids"]:
            continue
        industry = lead["directory_industry"]
        capture = captures.get(lead["source_url"])
        captured_ok = capture is not None and capture.get("capture_status") == "captured_metadata_only"
        primary_surface = " ".join((
            lead["company"],
            lead["title"],
            lead["source_excerpt"],
        ))
        captured_description = str((capture or {}).get("description") or "")
        matches = []
        for rule in RULES:
            if industry not in rule["industries"]:
                continue
            primary_terms = _matched_terms(primary_surface, rule["terms"])
            definition_terms = _definition_supported_terms(captured_description, rule["terms"])
            terms = list(dict.fromkeys(primary_terms + definition_terms))
            if terms:
                matches.append({
                    "rule_id": rule["rule_id"],
                    "subvertical_id": rule["route"],
                    "matched_terms": terms,
                    "primary_surface_terms": primary_terms,
                    "definition_supported_terms": definition_terms,
                    "score": (
                        2
                        + min(3, len(terms))
                        + min(2, max(len(term.split()) - 1 for term in terms))
                        + (3 if primary_terms else 0)
                    ),
                })
        matches.sort(key=lambda row: (-row["score"], row["subvertical_id"], row["rule_id"]))
        top_score = matches[0]["score"] if matches else 0
        top_routes = sorted({row["subvertical_id"] for row in matches if row["score"] == top_score})
        if not captured_ok or top_score < 3 or len(top_routes) != 1:
            rejected.append({
                "lead_id": lead["lead_id"],
                "source_url": lead["source_url"],
                "company": lead["company"],
                "title": lead["title"],
                "directory_industry": industry,
                "status": (
                    "public_capture_gap" if not captured_ok else
                    "classification_gap" if not matches else
                    "ambiguous_route_conflict"
                ),
                "candidate_routes": matches[:5],
                "formal_candidate_quota_credit": 0,
                "automatic_promotion_allowed": False,
            })
            continue
        winner = next(row for row in matches if row["subvertical_id"] == top_routes[0] and row["score"] == top_score)
        suggestions.append({
            "lead_id": lead["lead_id"],
            "source_url": lead["source_url"],
            "source_family_ids": lead["source_family_ids"],
            "discovery_method": "model_assisted_public_search_result",
            "company": lead["company"],
            "title": lead["title"],
            "directory_industry": industry,
            "source_excerpt": (
                f"Deterministic provisional route {winner['subvertical_id']} from directory industry "
                f"{industry!r}, bounded public metadata receipt {capture['content_sha256']}, and exact lexical signals "
                f"{winner['matched_terms']!r}; named human classification remains required."
            ),
            "provisional_subvertical_ids": [winner["subvertical_id"]],
            "routing_rule_id": winner["rule_id"],
            "routing_evidence_terms": winner["matched_terms"],
            "routing_primary_surface_terms": winner["primary_surface_terms"],
            "routing_definition_supported_terms": winner["definition_supported_terms"],
            "routing_score": winner["score"],
            "routing_confidence": "high_precision_provisional",
            "routing_capture_sha256": capture["content_sha256"],
            "human_classification_required": True,
            "formal_candidate_quota_credit": 0,
            "automatic_promotion_allowed": False,
        })
    suggestions.sort(key=lambda row: row["lead_id"])
    rejected.sort(key=lambda row: row["lead_id"])
    route_counts = Counter(row["provisional_subvertical_ids"][0] for row in suggestions)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_discovery_sha256": discovery["content_sha256"],
        "public_capture_sha256": (public_capture or {}).get("content_sha256"),
        "unrouted_input_count": sum(not row["provisional_subvertical_ids"] for row in discovery["records"]),
        "provisional_route_suggestion_count": len(suggestions),
        "classification_gap_count": len(rejected),
        "represented_subvertical_count": len(route_counts),
        "route_counts": dict(sorted(route_counts.items())),
        "records": suggestions,
        "rejected_records": rejected,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": (
            "Rules use only bounded directory metadata and exact lexical signals. Suggestions are provisional, exclusive-primary "
            "classification hypotheses that require named human source inspection. Ambiguous and unmatched leads remain gaps; "
            "no suggestion grants candidate, mechanism, outcome or blueprint credit."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_unrouted_lead_classification(
    payload: Mapping[str, Any],
    discovery: Mapping[str, Any],
    allowed_subverticals: set[str],
    public_capture: Mapping[str, Any] | None = None,
) -> None:
    verify_all_subvertical_discovery(discovery)
    if public_capture is not None:
        verify_public_source_capture(public_capture)
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMUnroutedLeadClassificationError("classification ledger seal is invalid")
    if payload.get("source_discovery_sha256") != discovery.get("content_sha256"):
        raise GTMUnroutedLeadClassificationError("classification ledger is stale")
    if payload.get("public_capture_sha256") != (public_capture or {}).get("content_sha256"):
        raise GTMUnroutedLeadClassificationError("classification capture binding is stale")
    records, rejected = payload.get("records"), payload.get("rejected_records")
    if not isinstance(records, list) or not isinstance(rejected, list):
        raise GTMUnroutedLeadClassificationError("classification record sets are invalid")
    unrouted = {row["lead_id"]: row for row in discovery["records"] if not row["provisional_subvertical_ids"]}
    if payload.get("unrouted_input_count") != len(unrouted) or len(records) + len(rejected) != len(unrouted):
        raise GTMUnroutedLeadClassificationError("classification coverage aggregate drifted")
    ids = [row.get("lead_id") for row in records + rejected]
    if len(ids) != len(set(ids)) or set(ids) != set(unrouted):
        raise GTMUnroutedLeadClassificationError("classification input partition drifted")
    if payload.get("provisional_route_suggestion_count") != len(records) or payload.get("classification_gap_count") != len(rejected):
        raise GTMUnroutedLeadClassificationError("classification result aggregate drifted")
    if payload.get("formal_candidate_quota_credit") != 0 or payload.get("automatic_promotion_allowed") is not False:
        raise GTMUnroutedLeadClassificationError("classification ledger escaped zero-credit mode")
    for row in records:
        routes = row.get("provisional_subvertical_ids")
        if (
            not isinstance(routes, list)
            or len(routes) != 1
            or routes[0] not in allowed_subverticals
            or row.get("routing_confidence") != "high_precision_provisional"
            or not row.get("routing_evidence_terms")
            or not row.get("routing_capture_sha256")
            or row.get("human_classification_required") is not True
            or row.get("formal_candidate_quota_credit") != 0
            or row.get("automatic_promotion_allowed") is not False
        ):
            raise GTMUnroutedLeadClassificationError("a route suggestion escaped the provisional boundary")
    if any(row.get("formal_candidate_quota_credit") != 0 or row.get("automatic_promotion_allowed") is not False for row in rejected):
        raise GTMUnroutedLeadClassificationError("a rejected classification minted credit")


__all__ = [
    "GTMUnroutedLeadClassificationError",
    "RULES",
    "classify_unrouted_leads",
    "verify_unrouted_lead_classification",
]
