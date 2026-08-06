from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .gtm_strategy import (
    BudgetTier,
    BusinessModel,
    CampaignStrategyInput,
    IndustryRisk,
    LifecycleStage,
)


class IndustryProfileError(ValueError):
    """Raised when an industry execution profile is unsafe or incoherent."""


class IndustryArchetype(str, Enum):
    B2B_SAAS = "b2b_saas"
    CONSUMER_APP = "consumer_app"
    ECOMMERCE_DTC = "ecommerce_dtc"
    MARKETPLACE = "marketplace"
    DEVELOPER_TOOLS = "developer_tools"
    PROFESSIONAL_SERVICES = "professional_services"
    FINANCIAL_SERVICES = "financial_services"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    TRAVEL_HOSPITALITY = "travel_hospitality"
    MEDIA_GAMING = "media_gaming"
    MANUFACTURING_INDUSTRIAL = "manufacturing_industrial"
    HARDWARE_IOT = "hardware_iot"
    LOCAL_SERVICES = "local_services"
    NONPROFIT_PUBLIC = "nonprofit_public"
    CPG_RETAIL = "cpg_retail"
    REAL_ESTATE = "real_estate"
    CLIMATE_ENERGY = "climate_energy"
    GENERAL_B2B = "general_b2b"
    GENERAL_B2C = "general_b2c"


@dataclass(frozen=True)
class IndustryDefinition:
    keywords: tuple[str, ...]
    business_model_fit: tuple[BusinessModel, ...]
    buying_motion: str
    decision_unit: tuple[str, ...]
    conversion_unit: str
    evidence_ladder: tuple[str, ...]
    zero_budget_growth_engine: str
    distribution_surfaces: tuple[str, ...]
    unit_economics_metrics: tuple[str, ...]
    feedback_signals: tuple[str, ...]
    creative_constraints: tuple[str, ...]
    specialist_roles: tuple[str, ...] = ()
    default_high_regulation: bool = False


_COMMON_EVIDENCE = (
    "owner-verified product or service fact",
    "observable workflow or delivery proof",
    "customer evidence with explicit usage rights",
    "measured outcome with denominator, window, and limitations",
)


_DEFINITIONS: dict[IndustryArchetype, IndustryDefinition] = {
    IndustryArchetype.B2B_SAAS: IndustryDefinition(
        ("b2b saas", "enterprise software", "workflow software", "martech", "crm", "software as a service"),
        (BusinessModel.B2B,),
        "multi-stakeholder problem discovery, proof-of-value, security review, and commercial approval",
        ("daily user", "functional champion", "economic buyer", "security or procurement reviewer"),
        "qualified activation that reaches the product's first verified value event",
        _COMMON_EVIDENCE,
        "publish a useful benchmark or teardown, run founder-led problem clinics, and convert repeated questions into search-led proof assets",
        ("founder_conversations", "linkedin_organic", "search_education", "partner_communities"),
        ("gross_margin", "sales_accepted_activation_rate", "cac_payback_months", "net_revenue_retention"),
        ("time_to_first_value", "qualified_pipeline_conversion", "expansion_or_churn_reason"),
        ("do not invent product UI", "show the workflow before the superlative", "separate pipeline from recognized revenue"),
    ),
    IndustryArchetype.CONSUMER_APP: IndustryDefinition(
        ("consumer app", "mobile app", "social app", "consumer software", "mobile application"),
        (BusinessModel.B2C,),
        "low-friction discovery, install or signup, first-value activation, habit formation, and voluntary referral",
        ("end user", "household influencer", "platform gatekeeper"),
        "new user completes the first repeatable value moment",
        _COMMON_EVIDENCE,
        "turn the product's smallest useful action into a participatory challenge, template, or shareable artifact with a voluntary referral loop",
        ("short_video_organic", "creator_community", "owned_social", "community_listening"),
        ("activation_rate", "day_7_retention", "cost_per_retained_user", "paid_or_organic_conversion_rate"),
        ("first_session_success", "habit_frequency", "invited_user_activation"),
        ("never fabricate app screens", "avoid dark-pattern urgency", "opt-in sharing only"),
    ),
    IndustryArchetype.ECOMMERCE_DTC: IndustryDefinition(
        ("ecommerce", "e-commerce", "dtc", "direct to consumer", "online store", "shopify"),
        (BusinessModel.B2C,),
        "need recognition, product evaluation, basket formation, purchase, fulfillment, and repeat purchase",
        ("shopper", "gift or household influencer", "fulfillment and support owner"),
        "paid and fulfilled order net of cancellation, return, and chargeback",
        _COMMON_EVIDENCE,
        "build an owned customer transformation library, seed rights-cleared creator demonstrations, and make the product's use ritual inherently shareable",
        ("short_video_organic", "creator_community", "customer_evidence", "customer_email"),
        ("net_revenue", "contribution_margin", "average_order_value", "return_rate", "repeat_purchase_rate"),
        ("product_page_to_order", "fulfillment_success", "cohort_repeat_purchase"),
        ("show real product scale and texture", "disclose creator relationships", "never count gross merchandise value as net revenue"),
    ),
    IndustryArchetype.MARKETPLACE: IndustryDefinition(
        ("marketplace", "two-sided", "two sided", "platform marketplace", "gig platform"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "solve a narrow liquidity wedge, recruit constrained supply, activate demand, and improve repeat matching",
        ("supply participant", "demand participant", "trust and safety owner", "platform operator"),
        "successful, policy-compliant match or transaction with both sides retained",
        _COMMON_EVIDENCE,
        "win one dense geographic or category wedge with a supply utility, a demand utility, and reciprocal referral after a successful match",
        ("community_listening", "partner_communities", "customer_evidence", "search_education"),
        ("match_rate", "time_to_match", "take_rate", "contribution_margin", "repeat_transaction_rate"),
        ("supply_fill_rate", "demand_conversion", "trust_incident_rate"),
        ("do not imply unavailable supply", "do not manufacture reviews", "report GMV separately from revenue"),
    ),
    IndustryArchetype.DEVELOPER_TOOLS: IndustryDefinition(
        ("developer tool", "developer tools", "devtool", "devtools", "api platform", "open source software", "sdk", "database infrastructure", "cloud infrastructure"),
        (BusinessModel.B2B,),
        "technical discovery, reproducible trial, team adoption, security review, and usage or contract expansion",
        ("individual developer", "technical champion", "platform owner", "security and economic buyer"),
        "reproducible technical success followed by retained team usage",
        _COMMON_EVIDENCE,
        "ship a genuinely useful open utility, reproducible benchmark, migration recipe, or reference implementation and let technical proof earn distribution",
        ("search_education", "partner_communities", "founder_conversations", "customer_evidence"),
        ("activated_projects", "weekly_retained_developers", "compute_or_api_gross_margin", "expansion_revenue"),
        ("time_to_hello_world", "error_free_task_completion", "team_adoption_depth"),
        ("publish runnable reproduction details", "do not cherry-pick benchmarks", "state environment and version limits"),
    ),
    IndustryArchetype.PROFESSIONAL_SERVICES: IndustryDefinition(
        ("consulting", "agency", "professional services", "legal services", "accounting", "advisory"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "trust discovery, diagnostic fit, scoped proposal, expert delivery, and referral or renewal",
        ("problem owner", "subject-matter evaluator", "economic buyer", "delivery owner"),
        "paid scoped engagement accepted after evidence-bound diagnosis",
        _COMMON_EVIDENCE,
        "publish a diagnostic, benchmark, or teardown that creates value before the sales call, then convert qualified self-assessment into a bounded expert review",
        ("founder_conversations", "search_education", "customer_evidence", "partner_communities"),
        ("qualified_diagnostic_rate", "proposal_to_win_rate", "delivery_gross_margin", "referral_or_renewal_rate"),
        ("diagnostic_completion", "scope_accuracy", "client_outcome_with_limitations"),
        ("do not promise outcomes outside the engagement scope", "protect client confidentiality", "separate expert opinion from verified fact"),
    ),
    IndustryArchetype.FINANCIAL_SERVICES: IndustryDefinition(
        ("fintech", "financial services", "banking", "insurance", "payments", "lending", "investment platform", "wealth management"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "trust and eligibility education, regulated disclosure, identity or risk review, funded activation, and retained compliant usage",
        ("customer", "financial decision maker", "compliance reviewer", "risk owner"),
        "compliant funded or bound account after all eligibility and disclosure gates",
        ("approved product terms", "jurisdiction-specific disclosure", "audited operational evidence", "measured outcome without individualized promise"),
        "offer plain-language education, transparent calculators with assumptions, and expert-reviewed myth correction instead of performance promises",
        ("search_education", "customer_evidence", "partner_communities", "customer_email"),
        ("net_revenue", "loss_or_claim_ratio", "cost_to_serve", "compliant_activation_rate", "retention"),
        ("disclosure_comprehension", "verification_completion", "complaint_and_harm_rate"),
        ("no individualized financial advice", "no return or approval promise", "show assumptions and jurisdiction"),
        ("licensed compliance specialist", "risk owner"),
        True,
    ),
    IndustryArchetype.HEALTHCARE: IndustryDefinition(
        ("healthcare", "health tech", "healthtech", "medical", "clinical", "pharma", "pharmaceutical", "diagnostic"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "need and eligibility education, clinical or operational validation, privacy review, supervised adoption, and safe follow-up",
        ("patient or end user", "clinician or domain champion", "privacy and safety reviewer", "payer or economic buyer"),
        "eligible user completes an approved, non-harmful care or workflow step",
        ("approved indication or intended use", "clinical or operational protocol", "privacy and safety validation", "measured outcome with population and limitations"),
        "publish clinician-reviewed education and non-diagnostic workflow utilities that answer real questions without replacing professional care",
        ("search_education", "partner_communities", "customer_evidence", "customer_email"),
        ("eligible_activation_rate", "care_or_workflow_completion", "cost_to_serve", "safety_event_rate", "retention"),
        ("comprehension", "protocol_adherence", "adverse_or_privacy_event"),
        ("no diagnosis or treatment promise", "no unconsented health story", "show population and evidence limitations"),
        ("licensed clinical specialist", "privacy or safety owner"),
        True,
    ),
    IndustryArchetype.EDUCATION: IndustryDefinition(
        ("education", "edtech", "learning platform", "school", "university", "training provider", "course platform"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "learning need diagnosis, sample lesson or pilot, learner activation, demonstrated progress, and cohort continuation",
        ("learner", "parent or manager", "educator or champion", "institutional buyer"),
        "learner completes a verified learning milestone rather than merely enrolling",
        _COMMON_EVIDENCE,
        "release a genuinely useful lesson, assessment, or study tool and turn learner-created progress artifacts into opt-in community proof",
        ("search_education", "creator_community", "partner_communities", "customer_evidence"),
        ("learning_activation", "milestone_completion", "cohort_retention", "refund_rate", "contribution_margin"),
        ("lesson_completion", "verified_skill_gain", "learner_retention"),
        ("do not equate enrollment with learning", "protect minors and student data", "avoid promising career outcomes"),
    ),
    IndustryArchetype.TRAVEL_HOSPITALITY: IndustryDefinition(
        ("travel", "hospitality", "hotel", "tourism", "airline", "vacation", "booking"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "inspiration, itinerary or venue evaluation, availability check, booking, fulfilled experience, and repeat or referral",
        ("traveler", "trip organizer", "property or service operator", "support owner"),
        "fulfilled booking net of cancellation, refund, and service failure",
        _COMMON_EVIDENCE,
        "create an itinerary, local guide, availability utility, or traveler ritual valuable enough to save and share before asking for a booking",
        ("search_education", "short_video_organic", "creator_community", "customer_evidence"),
        ("net_booking_revenue", "contribution_margin", "cancellation_rate", "repeat_booking_rate", "service_recovery_cost"),
        ("search_to_availability", "booking_completion", "experience_quality_and_referral"),
        ("never imply unavailable inventory", "label sponsored travel", "use rights-cleared location and guest media"),
    ),
    IndustryArchetype.MEDIA_GAMING: IndustryDefinition(
        ("media", "entertainment", "gaming", "game studio", "streaming", "music platform", "creator platform"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "discovery, sampling, fandom identity, recurring engagement, subscription or purchase, and community participation",
        ("audience member", "creator or talent", "community moderator", "distribution platform"),
        "rights-compliant retained engagement or paid conversion",
        _COMMON_EVIDENCE,
        "design a repeatable fandom ritual, remixable prompt, community challenge, or creator collaboration with explicit rights and attribution",
        ("short_video_organic", "creator_community", "owned_social", "community_listening"),
        ("retained_audience", "completion_or_play_rate", "subscriber_or_purchase_conversion", "rights_cost", "contribution_margin"),
        ("first_minute_retention", "return_frequency", "voluntary_creation_or_referral"),
        ("clear every music and likeness right", "do not simulate fan consensus", "moderate community participation"),
    ),
    IndustryArchetype.MANUFACTURING_INDUSTRIAL: IndustryDefinition(
        ("manufacturing", "industrial", "factory", "automation equipment", "robotics", "supply chain equipment"),
        (BusinessModel.B2B,),
        "engineering problem definition, application fit, technical validation, safety and procurement review, deployment, and service renewal",
        ("operator", "engineering champion", "safety or quality reviewer", "plant and procurement buyer"),
        "validated application or pilot that meets the documented operating envelope",
        _COMMON_EVIDENCE,
        "publish an engineering calculator, application note, failure-mode teardown, or operator checklist that earns technical trust before a sales conversation",
        ("search_education", "partner_communities", "customer_evidence", "founder_conversations"),
        ("validated_application_rate", "sales_cycle_days", "deployment_margin", "downtime_or_defect_change", "service_renewal"),
        ("technical_fit", "pilot_acceptance", "deployment_and_safety_incidents"),
        ("state operating envelope", "do not imply certifications", "show installation and safety dependencies"),
    ),
    IndustryArchetype.HARDWARE_IOT: IndustryDefinition(
        ("hardware", "iot", "internet of things", "device", "wearable", "electronics"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "use-case discovery, physical demonstration, compatibility and reliability proof, purchase, setup, and retained usage",
        ("end user", "technical evaluator", "operations or household buyer", "support owner"),
        "successfully installed device reaches its first verified recurring value event",
        _COMMON_EVIDENCE,
        "publish transparent build logs, compatibility tools, durability demonstrations, and owner-created use cases with real-device provenance",
        ("short_video_organic", "search_education", "creator_community", "customer_evidence"),
        ("activated_devices", "return_and_failure_rate", "hardware_gross_margin", "attach_or_subscription_revenue", "retained_usage"),
        ("setup_success", "device_reliability", "thirty_day_active_device_rate"),
        ("never render nonexistent hardware as shipped", "state compatibility", "show physical safety and privacy limits"),
    ),
    IndustryArchetype.LOCAL_SERVICES: IndustryDefinition(
        ("local service", "home service", "restaurant", "salon", "clinic practice", "repair service", "local business"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "local discovery, trust and availability check, booking or visit, fulfilled service, and repeat or neighborhood referral",
        ("local customer", "household or business decision maker", "service operator"),
        "fulfilled appointment or visit net of cancellation and refund",
        _COMMON_EVIDENCE,
        "own one neighborhood question with useful local content, partner with adjacent businesses, and turn excellent fulfilled service into opt-in proof and referral",
        ("search_education", "partner_communities", "customer_evidence", "owned_social"),
        ("fulfilled_booking_revenue", "capacity_utilization", "contribution_margin", "cancellation_rate", "repeat_visit_rate"),
        ("search_to_booking", "service_fulfillment", "review_and_referral_rate"),
        ("do not fabricate local reviews", "show real service area and availability", "respect customer privacy"),
    ),
    IndustryArchetype.NONPROFIT_PUBLIC: IndustryDefinition(
        ("nonprofit", "non-profit", "ngo", "public sector", "government", "civic", "foundation"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "community need validation, stakeholder trust, participation or funding decision, transparent delivery, and public accountability",
        ("beneficiary", "community advocate", "program owner", "funder or public decision maker"),
        "verified participation, service delivery, donation, or approved program milestone",
        _COMMON_EVIDENCE,
        "turn mission data into a transparent community utility, coalition action, or volunteer ritual while preserving beneficiary dignity and consent",
        ("partner_communities", "customer_evidence", "search_education", "owned_social"),
        ("program_delivery_cost", "verified_participation", "donor_retention", "funds_to_program_ratio"),
        ("participant_completion", "service_delivery_quality", "community_trust_or_harm"),
        ("never exploit beneficiary stories", "distinguish outputs from outcomes", "publish funding and data limitations"),
    ),
    IndustryArchetype.CPG_RETAIL: IndustryDefinition(
        ("cpg", "consumer packaged goods", "retail", "grocery", "food brand", "beverage", "beauty brand", "fashion brand"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "category discovery, sensory or use-case evaluation, trial, retail or direct purchase, repeat habit, and household advocacy",
        ("consumer", "household influencer", "retail buyer", "merchandising or operations owner"),
        "net sold unit followed by verified repeat purchase or replenishment",
        _COMMON_EVIDENCE,
        "create a repeatable recipe, ritual, style, sampling moment, or store utility and seed it through rights-cleared micro-communities",
        ("short_video_organic", "creator_community", "owned_social", "customer_evidence"),
        ("net_sales", "gross_margin", "sell_through", "return_or_waste_rate", "repeat_purchase_rate"),
        ("trial_to_purchase", "retail_availability", "repeat_or_replenishment"),
        ("show real pack and serving", "disclose creator and sampling relationship", "avoid unsupported health or sustainability claims"),
    ),
    IndustryArchetype.REAL_ESTATE: IndustryDefinition(
        ("real estate", "proptech", "property", "housing", "mortgage brokerage"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "local market education, eligibility or fit, property evaluation, regulated transaction, closing, and post-close referral",
        ("buyer renter or seller", "household decision maker", "licensed agent or advisor", "lender or transaction reviewer"),
        "verified qualified appointment or completed transaction without fair-housing breach",
        ("verified listing or market data", "licensed disclosure", "inspection or transaction evidence", "measured outcome with geography and period"),
        "publish neighborhood utilities, transparent market explainers, and decision checklists that earn local search and referral demand",
        ("search_education", "customer_evidence", "partner_communities", "owned_social"),
        ("qualified_appointment_rate", "transaction_net_revenue", "cycle_days", "cost_to_close", "referral_rate"),
        ("search_to_inquiry", "appointment_quality", "close_and_post_close_satisfaction"),
        ("no steering or discriminatory targeting", "never imply stale listing availability", "state licensed role and data date"),
        ("licensed real-estate or lending reviewer",),
        True,
    ),
    IndustryArchetype.CLIMATE_ENERGY: IndustryDefinition(
        ("climate", "clean energy", "renewable energy", "solar", "battery", "energy efficiency", "carbon"),
        (BusinessModel.B2B, BusinessModel.B2C),
        "baseline measurement, technical and financial fit, incentive or procurement review, deployment, and verified savings or impact",
        ("site or household user", "technical evaluator", "finance or procurement buyer", "regulatory or sustainability reviewer"),
        "installed or contracted solution reaches a measured operating milestone",
        ("verified technical specification", "site-specific baseline and assumptions", "third-party certification where claimed", "measured impact with boundary and method"),
        "publish transparent calculators, site checklists, incentive explainers, and measured case evidence with assumptions visible",
        ("search_education", "partner_communities", "customer_evidence", "founder_conversations"),
        ("verified_project_value", "deployment_margin", "payback_period", "measured_energy_or_emissions_change", "renewal_or_referral"),
        ("assessment_to_project", "deployment_completion", "measurement_and_verification_quality"),
        ("no unbounded green claim", "show system boundary and assumptions", "do not imply unavailable incentives"),
    ),
    IndustryArchetype.GENERAL_B2B: IndustryDefinition(
        (),
        (BusinessModel.B2B,),
        "problem discovery, stakeholder proof, bounded trial or proposal, commercial decision, and expansion",
        ("user", "functional champion", "economic buyer", "risk or procurement reviewer"),
        "verified qualified next step tied to an owner-defined value event",
        _COMMON_EVIDENCE,
        "create an expert utility, benchmark, teardown, or problem clinic that earns attention before a commercial ask",
        ("founder_conversations", "search_education", "partner_communities", "customer_evidence"),
        ("net_revenue", "contribution_margin", "qualified_conversion", "retention_or_expansion"),
        ("first_value_event", "qualified_progression", "retention_reason"),
        ("require human confirmation of industry profile", "do not invent industry norms", "measure before scaling"),
    ),
    IndustryArchetype.GENERAL_B2C: IndustryDefinition(
        (),
        (BusinessModel.B2C,),
        "need recognition, low-friction trial, first value, repeat behavior, purchase, and voluntary advocacy",
        ("end user", "household or social influencer", "platform gatekeeper"),
        "verified first-value event followed by retained or paid action",
        _COMMON_EVIDENCE,
        "make one useful or identity-expressive action saveable and shareable, then invite an opt-in next step",
        ("community_listening", "short_video_organic", "creator_community", "owned_social"),
        ("net_revenue", "contribution_margin", "activation_rate", "retention_or_repeat_purchase"),
        ("first_value_event", "repeat_behavior", "voluntary_referral"),
        ("require human confirmation of industry profile", "avoid manipulative urgency", "measure before scaling"),
    ),
}


_LIFECYCLE_FOCUS = {
    LifecycleStage.PRE_PMF: "maximize falsifiable problem and first-value learning before reach",
    LifecycleStage.LAUNCH: "prove one narrow audience-message-channel wedge with a frozen baseline",
    LifecycleStage.GROWTH: "improve repeatable conversion, retention, and contribution margin without eroding trust",
    LifecycleStage.MATURE: "defend retention, expansion, brand distinctiveness, and incrementality",
}

_BUDGET_MODE = {
    BudgetTier.ZERO: "owned, earned, community, partner, and product-loop distribution only; no media spend",
    BudgetTier.SMALL: "organic core plus bounded manual experiments after evidence and stop-rule review",
    BudgetTier.SCALED: "organic core plus incremental paid amplification only after holdout and contribution-margin gates",
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.casefold()).strip()


def _keyword_match(text: str, keyword: str) -> bool:
    normalized_keyword = _normalized(keyword)
    if not normalized_keyword:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_keyword):
        return normalized_keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", text) is not None


def _classify(industry: str, business_model: BusinessModel) -> tuple[IndustryArchetype, str, tuple[str, ...]]:
    normalized = _normalized(industry)
    matches: list[tuple[int, IndustryArchetype, tuple[str, ...]]] = []
    for archetype, definition in _DEFINITIONS.items():
        if archetype in {IndustryArchetype.GENERAL_B2B, IndustryArchetype.GENERAL_B2C}:
            continue
        matched = tuple(keyword for keyword in definition.keywords if _keyword_match(normalized, keyword))
        if matched:
            matches.append((len(matched), archetype, matched))
    if not matches:
        fallback = IndustryArchetype.GENERAL_B2B if business_model is BusinessModel.B2B else IndustryArchetype.GENERAL_B2C
        return fallback, "fallback_requires_human_confirmation", ()
    maximum = max(row[0] for row in matches)
    leaders = [row for row in matches if row[0] == maximum]
    if len(leaders) != 1:
        fallback = IndustryArchetype.GENERAL_B2B if business_model is BusinessModel.B2B else IndustryArchetype.GENERAL_B2C
        combined = tuple(sorted({keyword for _, _, keywords in leaders for keyword in keywords}))
        return fallback, "ambiguous_requires_human_confirmation", combined
    _, archetype, matched = leaders[0]
    return archetype, "classified", matched


def compile_industry_gtm_profile(
    request: CampaignStrategyInput,
    *,
    source_strategy_sha256: str,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", source_strategy_sha256):
        raise IndustryProfileError("source_strategy_sha256 must be a lowercase SHA-256")
    business_model = request.audience.business_model
    archetype, classification_status, matched_keywords = _classify(request.industry, business_model)
    definition = _DEFINITIONS[archetype]
    risk_mismatch = definition.default_high_regulation and request.industry_risk is not IndustryRisk.HIGH_REGULATION
    if risk_mismatch:
        raise IndustryProfileError(
            f"{archetype.value} requires high_regulation risk and named specialist approval"
        )
    business_model_fit = business_model in definition.business_model_fit
    human_confirmation = classification_status != "classified" or not business_model_fit
    payload: dict[str, Any] = {
        "schema": "ProofLaunchIndustryGTMProfileV1",
        "campaign_id": request.campaign_id,
        "strategy_id": None,
        "source_strategy_sha256": source_strategy_sha256,
        "industry_input": request.industry,
        "industry_archetype": archetype.value,
        "classification_status": classification_status,
        "matched_keywords": list(matched_keywords),
        "human_classification_confirmation_required": human_confirmation,
        "business_model": business_model.value,
        "business_model_fit": business_model_fit,
        "lifecycle": request.lifecycle.value,
        "lifecycle_operating_focus": _LIFECYCLE_FOCUS[request.lifecycle],
        "budget": request.budget.value,
        "budget_operating_mode": _BUDGET_MODE[request.budget],
        "industry_risk": request.industry_risk.value,
        "buying_motion": definition.buying_motion,
        "decision_unit": list(definition.decision_unit),
        "conversion_unit": definition.conversion_unit,
        "evidence_ladder": list(definition.evidence_ladder),
        "proof_gate": (
            "named specialist approval plus source, rights, validity, population, limitations, and exact wording"
            if request.industry_risk is IndustryRisk.HIGH_REGULATION
            else "source, rights, validity, limitations, and accountable-owner approval"
        ),
        "zero_budget_growth_engine": definition.zero_budget_growth_engine,
        "distribution_surfaces": list(definition.distribution_surfaces),
        "unit_economics_metrics": list(definition.unit_economics_metrics),
        "feedback_signals": list(definition.feedback_signals),
        "creative_constraints": list(definition.creative_constraints),
        "specialist_roles": list(definition.specialist_roles),
        "external_activation_executed": False,
        "automatic_budget_allocation_enabled": False,
        "causal_revenue_claim_allowed": False,
        "truth_boundary": (
            "This deterministic profile supplies an industry operating hypothesis, not market proof. "
            "Unknown, ambiguous, or business-model-mismatched classifications require named human confirmation. "
            "No profile proves product-market fit, creative quality, causal lift, revenue, or universal applicability."
        ),
    }
    payload["profile_id"] = f"industry-profile-{_digest(payload)[:16]}"
    payload["content_sha256"] = _digest(payload)
    verify_industry_gtm_profile(payload)
    return payload


def bind_industry_profile_strategy(
    profile: Mapping[str, Any],
    *,
    strategy_id: str,
) -> dict[str, Any]:
    if not strategy_id.strip():
        raise IndustryProfileError("strategy_id is required")
    payload = dict(profile)
    payload.pop("content_sha256", None)
    payload["strategy_id"] = strategy_id
    payload["content_sha256"] = _digest(payload)
    verify_industry_gtm_profile(payload)
    return payload


def verify_industry_gtm_profile(profile: Mapping[str, Any]) -> None:
    if profile.get("schema") != "ProofLaunchIndustryGTMProfileV1":
        raise IndustryProfileError("industry profile schema is invalid")
    for key in (
        "campaign_id",
        "source_strategy_sha256",
        "industry_input",
        "industry_archetype",
        "classification_status",
        "buying_motion",
        "conversion_unit",
        "zero_budget_growth_engine",
        "proof_gate",
        "truth_boundary",
        "profile_id",
        "content_sha256",
    ):
        if not isinstance(profile.get(key), str) or not str(profile[key]).strip():
            raise IndustryProfileError(f"industry profile {key} is required")
    if not re.fullmatch(r"[0-9a-f]{64}", str(profile["source_strategy_sha256"])):
        raise IndustryProfileError("industry profile source strategy digest is invalid")
    for key in (
        "decision_unit",
        "evidence_ladder",
        "distribution_surfaces",
        "unit_economics_metrics",
        "feedback_signals",
        "creative_constraints",
    ):
        values = profile.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
            raise IndustryProfileError(f"industry profile {key} must be a non-empty string list")
    if profile.get("external_activation_executed") is not False:
        raise IndustryProfileError("industry profile cannot activate externally")
    if profile.get("automatic_budget_allocation_enabled") is not False:
        raise IndustryProfileError("industry profile cannot allocate budget")
    if profile.get("causal_revenue_claim_allowed") is not False:
        raise IndustryProfileError("industry profile cannot claim causal revenue")
    payload = dict(profile)
    supplied = payload.pop("content_sha256", None)
    if supplied != _digest(payload):
        raise IndustryProfileError("industry profile content digest does not match")


def industry_archetype_contracts() -> dict[str, dict[str, Any]]:
    return {
        archetype.value: {
            **asdict(definition),
            "business_model_fit": [value.value for value in definition.business_model_fit],
        }
        for archetype, definition in _DEFINITIONS.items()
    }
