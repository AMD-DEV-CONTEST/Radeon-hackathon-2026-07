from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMSubverticalOntologyV1"
CHANGE_SCHEMA = "ProofLaunchGTMSubverticalOntologyChangeProposalV1"
ONTOLOGY_VERSION = "1.0.0"


class GTMSubverticalOntologyError(ValueError):
    pass


DESCRIPTIONS = {
    "b2b.developer_tools.application_development": "Developer products used to design, code, assemble, debug, or ship software applications, including IDE, API-development, and app-builder workflows.",
    "b2b.developer_tools.devops_observability": "Products that operate, deploy, monitor, trace, secure, or remediate software and infrastructure after code enters delivery and production systems.",
    "b2b.developer_tools.testing_quality": "Products whose primary job is automated or human-assisted verification of software correctness, reliability, performance, accessibility, or release quality.",
    "b2b.developer_tools.open_source_infrastructure": "Commercial or community infrastructure distributed primarily through open-source software, where adoption, contribution, hosting, or support drives the GTM motion.",
    "b2b.ai_data_infrastructure.foundation_model_tools": "Tools for building, adapting, evaluating, governing, or operating foundation models and model-enabled applications, excluding general data platforms.",
    "b2b.ai_data_infrastructure.data_platforms": "Warehouses, lakes, databases, integration, transformation, catalog, governance, and query systems whose primary job is managing enterprise data.",
    "b2b.ai_data_infrastructure.analytics_bi": "Business intelligence and analytics products that turn organizational data into decisions, reports, dashboards, forecasts, or governed analysis.",
    "b2b.ai_data_infrastructure.mlops_and_inference": "Systems for packaging, deploying, serving, scaling, monitoring, or optimizing machine-learning models and inference workloads in production.",
    "b2b.cybersecurity.identity": "Enterprise identity, authentication, authorization, privileged-access, and identity-governance products protecting workforce, customer, or machine access.",
    "b2b.cybersecurity.application_security": "Products that find, prevent, prioritize, or remediate security risk in application code, dependencies, APIs, builds, and software supply chains.",
    "b2b.cybersecurity.cloud_security": "Products protecting cloud infrastructure, workloads, configurations, networks, and runtime environments across public, private, or hybrid clouds.",
    "b2b.cybersecurity.governance_risk_compliance": "Security and compliance products centered on control evidence, policy, risk, audit, regulatory readiness, vendor assurance, and trust operations.",
    "b2b.b2b_saas.horizontal_saas": "Cross-industry business software serving a broadly shared workflow that is not primarily collaboration, finance operations, or a vertical-specific system.",
    "b2b.b2b_saas.vertical_saas": "Business software purpose-built around the regulated, operational, or commercial workflow of one clearly bounded industry or profession.",
    "b2b.b2b_saas.collaboration": "Products whose primary value is shared communication, coordination, knowledge, documents, projects, meetings, or team execution across users.",
    "b2b.b2b_saas.finance_operations": "Software for accounting, billing, spend, procurement, treasury, close, planning, tax, or other internal business-finance operations.",
    "b2b.fintech_regtech.payments": "Business payment acceptance, movement, orchestration, settlement, issuing, acquiring, or payment-infrastructure products sold to organizations.",
    "b2b.fintech_regtech.banking": "Banking accounts, embedded banking, cash management, lending, or bank-platform products designed primarily for organizational customers.",
    "b2b.fintech_regtech.insurance": "Commercial insurance carriers, brokers, infrastructure, underwriting, claims, or risk-transfer products serving organizations or professional intermediaries.",
    "b2b.fintech_regtech.regulatory_technology": "Technology whose primary job is regulatory interpretation, surveillance, reporting, screening, monitoring, or regulated-process automation in financial markets.",
    "b2b.martech_sales_tech.crm": "Systems of record and workflow for managing accounts, contacts, opportunities, relationships, and revenue-team activity across the customer lifecycle.",
    "b2b.martech_sales_tech.marketing_automation": "Products for campaign orchestration, lifecycle messaging, segmentation, lead nurture, journey automation, and marketing operations.",
    "b2b.martech_sales_tech.commerce_enablement": "Technology enabling merchants, suppliers, or business sellers to create, transact, merchandise, fulfill, or optimize digital commerce.",
    "b2b.martech_sales_tech.revenue_intelligence": "Products for prospecting, enrichment, intent, conversation intelligence, forecasting, sales productivity, or revenue decision support beyond CRM recordkeeping.",
    "b2b.hr_future_of_work.talent": "Products for recruiting, sourcing, assessment, hiring, talent marketplaces, succession, or career mobility inside and across organizations.",
    "b2b.hr_future_of_work.workforce_operations": "Systems for payroll, benefits, scheduling, time, attendance, workforce administration, compliance, and employee-record operations.",
    "b2b.hr_future_of_work.learning": "Enterprise learning, enablement, skills, training, coaching, and knowledge-assessment products purchased for workforce development.",
    "b2b.hr_future_of_work.employee_experience": "Products centered on employee engagement, workplace experience, internal communication, recognition, feedback, wellbeing, or organizational listening.",
    "b2b.professional_services.consulting": "Advisory businesses whose primary deliverable is expert diagnosis, strategy, transformation, research, or implementation guidance rather than managed execution.",
    "b2b.professional_services.agency_services": "Creative, media, marketing, communications, design, production, or growth services delivered as accountable client work.",
    "b2b.professional_services.legal_accounting": "Legal, accounting, audit, tax, bookkeeping, and related regulated or credentialed professional services sold to organizations.",
    "b2b.professional_services.managed_and_field_services": "Outsourced recurring operations or field-delivered business services where labor, service levels, geography, and execution capacity are central to value.",
    "b2b.industrial_climate.manufacturing": "Manufacturers whose GTM episode centers on selling produced components, materials, or finished industrial goods rather than standalone equipment or services.",
    "b2b.industrial_climate.industrial_equipment": "Capital equipment, machinery, instrumentation, industrial hardware, parts, or service systems purchased to operate physical production and facilities.",
    "b2b.industrial_climate.engineering_construction": "Engineering, architecture, construction, infrastructure, contractor, and built-project businesses whose revenue is tied to designed or delivered projects.",
    "b2b.industrial_climate.commercial_real_estate": "Commercial property brokerage, development, leasing, investment, operations, workplace, or property-service businesses serving organizational buyers.",
    "b2b.industrial_climate.energy_climate": "Enterprise energy, electrification, climate technology, carbon, grid, efficiency, environmental, and industrial decarbonization products or services.",
    "b2b.healthcare_life_sciences.provider": "Healthcare delivery organizations and provider-facing products whose primary customer or operating context is clinical care delivery.",
    "b2b.healthcare_life_sciences.biotechnology": "Biotechnology, therapeutics, diagnostics research, laboratory, and life-science platform businesses centered on biological innovation and development.",
    "b2b.healthcare_life_sciences.medical_devices": "Regulated or clinically used physical devices, instruments, equipment, and connected hardware sold into healthcare markets.",
    "b2b.healthcare_life_sciences.healthcare_operations": "Nonclinical healthcare administration, revenue cycle, scheduling, data exchange, benefits, workforce, procurement, and operational infrastructure.",
    "b2c.consumer_ai_mobile_apps.assistants": "Consumer applications whose primary value is a general or specialized AI assistant completing conversational, planning, research, or task-support jobs.",
    "b2c.consumer_ai_mobile_apps.creative_apps": "Consumer applications primarily used to generate, edit, remix, or publish visual, video, audio, design, or written creative work.",
    "b2c.consumer_ai_mobile_apps.utility_apps": "Consumer mobile or web applications solving a focused practical utility job outside creative, social, or general assistant categories.",
    "b2c.consumer_ai_mobile_apps.social_apps": "Consumer applications whose core value depends on identity, communication, community, matching, sharing, or interaction with other users.",
    "b2c.personal_finance.banking": "Consumer accounts, cards, money movement, savings, borrowing, and everyday banking experiences marketed to individuals or households.",
    "b2c.personal_finance.investing": "Consumer brokerage, investing, wealth, trading, portfolio, and long-term asset-building products for individuals.",
    "b2c.personal_finance.insurance": "Personal insurance discovery, purchase, servicing, claims, and protection products marketed primarily to individuals or households.",
    "b2c.personal_finance.credit_and_budgeting": "Consumer credit building, debt, budgeting, financial planning, cash-flow, and money-management products outside primary banking.",
    "b2c.health_wellness.fitness": "Consumer exercise, movement, training, recovery, and physical-performance products, services, devices, memberships, or applications.",
    "b2c.health_wellness.nutrition": "Consumer nutrition guidance, meal planning, supplements, diet programs, and nutrition-tracking products where health behavior is primary.",
    "b2c.health_wellness.mental_wellbeing_nonclinical": "Nonclinical consumer products for mindfulness, stress, sleep, emotional wellbeing, reflection, and self-guided mental wellness.",
    "b2c.health_wellness.care_navigation": "Consumer services and applications that help people find, access, coordinate, understand, or pay for appropriate care without acting as the provider.",
    "b2c.education_language.language_learning": "Consumer products whose primary job is acquiring or practicing a spoken, written, or signed language.",
    "b2c.education_language.tutoring": "Consumer one-to-one or small-group academic instruction and learning support tied to a learner, subject, or assessment need.",
    "b2c.education_language.skills": "Consumer courses, coaching, practice, and credential products for vocational, professional, technical, creative, or personal skill acquisition.",
    "b2c.education_language.family_learning": "Learning products purchased or used by families for children, parents, shared education, enrichment, or home learning.",
    "b2c.gaming_entertainment.mobile_games": "Games designed primarily for smartphone or tablet distribution, monetization, engagement, and live operation.",
    "b2c.gaming_entertainment.pc_console": "Games and interactive entertainment designed primarily for personal computer or dedicated console play.",
    "b2c.gaming_entertainment.streaming": "Consumer video, audio, live, or interactive entertainment streaming services where ongoing media consumption is primary.",
    "b2c.gaming_entertainment.fan_communities": "Products and communities organized around fandom, creators, sports, entertainment properties, collectibles, or participatory fan identity.",
    "b2c.commerce_marketplaces.general_ecommerce": "Consumer ecommerce merchants or broad marketplaces selling across multiple general merchandise categories without a narrower primary vertical.",
    "b2c.commerce_marketplaces.local_marketplaces": "Consumer marketplaces whose value depends on geographically local supply, demand, pickup, delivery, or neighborhood trust.",
    "b2c.commerce_marketplaces.home_property": "Consumer commerce and marketplaces centered on homes, furnishings, renovation, residential property, moving, or household projects.",
    "b2c.commerce_marketplaces.services_marketplaces": "Consumer marketplaces matching buyers with independent service providers, professionals, freelancers, or task completion.",
    "b2c.beauty_fashion.beauty": "Consumer skincare, cosmetics, haircare, fragrance, grooming, and beauty services where appearance or care ritual is primary.",
    "b2c.beauty_fashion.apparel": "Consumer clothing, footwear, accessories, and functional wear outside luxury-led or resale-led business models.",
    "b2c.beauty_fashion.luxury": "Premium consumer fashion, beauty, accessories, jewelry, or lifestyle products where scarcity, heritage, craft, and prestige materially shape demand.",
    "b2c.beauty_fashion.resale": "Consumer recommerce, secondhand, consignment, rental, authentication, and circular fashion or beauty marketplaces.",
    "b2c.food_beverage.consumer_packaged_goods": "Packaged consumer food and beverage brands sold through retail, ecommerce, wholesale, or recurring household purchase.",
    "b2c.food_beverage.restaurants": "Consumer restaurant, café, foodservice, and dining brands where prepared food experience and location or format are primary.",
    "b2c.food_beverage.delivery": "Consumer meal, grocery, restaurant, and prepared-food delivery products where logistics and fulfillment are central to the offer.",
    "b2c.food_beverage.functional_food": "Consumer food and beverage positioned around a specific functional, performance, wellness, or dietary benefit beyond ordinary packaged consumption.",
    "b2c.travel_hospitality.destinations": "Destination, tourism board, city, region, attraction cluster, and place-brand GTM intended to drive visits or visitor spend.",
    "b2c.travel_hospitality.lodging": "Hotels, resorts, hostels, vacation rentals, and lodging marketplaces centered on overnight stay selection and experience.",
    "b2c.travel_hospitality.transport": "Consumer air, rail, road, maritime, mobility, and travel-transport products used to reach or move within a destination.",
    "b2c.travel_hospitality.experiences": "Tours, activities, events, guides, attractions, and bookable travel experiences beyond transport and lodging.",
    "b2c.creator_productivity.creator_tools": "Consumer or prosumer products for audience building, publishing, monetization, sponsorship, community, and creator-business operations.",
    "b2c.creator_productivity.focus_productivity": "Consumer productivity, focus, notes, habits, planning, personal knowledge, and individual work-organization products.",
    "b2c.creator_productivity.audio_video": "Prosumer recording, editing, transcription, streaming, production, and distribution products centered specifically on audio or video workflows.",
    "b2c.creator_productivity.independent_business": "Products enabling solo operators and very small businesses to sell, administer, finance, schedule, deliver, or grow independent work.",
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def scope_for_subvertical(subvertical_id: str, sibling_ids: Sequence[str]) -> dict[str, Any]:
    definition = DESCRIPTIONS.get(subvertical_id)
    if not definition:
        raise GTMSubverticalOntologyError(f"missing definition for {subvertical_id}")
    return {
        "definition": definition,
        "inclusion_scope": [
            "The episode's primary monetized offer and audience job match this definition during the observed window.",
            "The reported GTM mechanism and outcome can be attributed to the named product, service, or business line rather than only to a diversified parent.",
            "A multi-product company is included only when the episode is product-, market-, and time-bounded enough to preserve one primary subvertical.",
        ],
        "exclusion_scope": [
            "Generic corporate brand activity without a product-, audience-, market-, and outcome-bounded episode.",
            "Episodes whose primary monetized offer belongs to one of the listed sibling subverticals.",
            "Duplicate cross-listing of one episode across multiple subverticals; ambiguous cases require named review and receive zero credit.",
        ],
        "sibling_subvertical_ids": sorted(value for value in sibling_ids if value != subvertical_id),
        "exclusive_primary_subvertical": True,
    }


def build_ontology(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [str(row.get("subvertical_id")) for row in rows]
    if len(ids) != 81 or len(set(ids)) != 81 or set(ids) != set(DESCRIPTIONS):
        raise GTMSubverticalOntologyError("ontology registry and 81 scoped definitions do not match")
    sibling_index: dict[str, list[str]] = {}
    for row in rows:
        sibling_index.setdefault(str(row["vertical"]), []).append(str(row["subvertical_id"]))
    scoped = [{**dict(row), **scope_for_subvertical(str(row["subvertical_id"]), sibling_index[str(row["vertical"])])} for row in rows]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ontology_version": ONTOLOGY_VERSION,
        "subvertical_count": len(scoped),
        "subverticals": scoped,
        "classification_policy": {
            "one_primary_subvertical_per_episode": True,
            "ambiguous_classification_requires_named_review": True,
            "ambiguous_classification_quota_credit": 0,
            "cross_listed_duplicate_quota_credit": 0,
        },
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_ontology(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload); supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMSubverticalOntologyError("ontology seal is invalid")
    rows = payload.get("subverticals")
    if not isinstance(rows, list) or len(rows) != 81 or payload.get("subvertical_count") != 81:
        raise GTMSubverticalOntologyError("ontology must contain exactly 81 subverticals")
    for row in rows:
        if len(str(row.get("definition", ""))) < 80 or len(row.get("inclusion_scope", [])) < 3 or len(row.get("exclusion_scope", [])) < 3:
            raise GTMSubverticalOntologyError("a subvertical lacks a substantive definition or boundary")
        if row.get("exclusive_primary_subvertical") is not True:
            raise GTMSubverticalOntologyError("subvertical classification is not exclusive")


def compile_change_proposal(
    current: Mapping[str, Any],
    proposed_new_subverticals: Sequence[Mapping[str, Any]],
    *,
    proposed_version: str,
    proposer_name: str,
) -> dict[str, Any]:
    verify_ontology(current)
    if not re.fullmatch(r"\d+\.\d+\.\d+", proposed_version) or proposed_version == current.get("ontology_version"):
        raise GTMSubverticalOntologyError("a distinct semantic proposed_version is required")
    if len(proposer_name.strip()) < 3:
        raise GTMSubverticalOntologyError("a named proposer is required")
    existing = {row["subvertical_id"] for row in current["subverticals"]}
    additions = []
    for row in proposed_new_subverticals:
        subvertical_id = str(row.get("subvertical_id") or "")
        if not subvertical_id or subvertical_id in existing or len(str(row.get("definition") or "")) < 80:
            raise GTMSubverticalOntologyError("new subvertical identity or definition is invalid")
        additions.append({
            **dict(row),
            "required_structured_candidates": 200,
            "required_mechanism_deep_audits": 40,
            "required_outcome_cross_verifications": 10,
            "required_execution_case_blueprints": 5,
            "quota_credit_before_approval": 0,
        })
    payload: dict[str, Any] = {
        "schema": CHANGE_SCHEMA,
        "current_ontology_sha256": current["content_sha256"],
        "current_version": current["ontology_version"],
        "proposed_version": proposed_version,
        "proposer_name": proposer_name.strip(),
        "status": "pending_named_approval",
        "automatic_application_allowed": False,
        "new_subverticals": additions,
        "new_denominator_if_approved": current["subvertical_count"] + len(additions),
        "approval_requirements": ["named ontology owner", "scope collision review", "quota impact review", "version migration test"],
    }
    payload["content_sha256"] = _digest(payload)
    return payload


__all__ = ["GTMSubverticalOntologyError", "build_ontology", "compile_change_proposal", "scope_for_subvertical", "verify_ontology"]
