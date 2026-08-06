from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


SCHEMA = "ProofLaunchGTMMarketNeighborhoodV1"


class MarketNeighborhoodError(ValueError):
    """Market-neighbor evidence is incomplete or would require invention."""


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


def _tokens(value: object) -> set[str]:
    text = str(value or "").casefold().replace("&", " and ")
    for mark in ("/", "-", "_", ",", ".", "(", ")"):
        text = text.replace(mark, " ")
    return {token for token in text.split() if token}


_B2B_GRAPH: tuple[dict[str, object], ...] = (
    {
        "node_id": "b2b-saas",
        "label": "software as a service",
        "aliases": ("saas", "software", "cloud software", "enterprise software"),
        "subcategories": ("horizontal", "vertical", "developer tools", "security", "data", "finops", "customer operations"),
        "buying_system": "multi-role value, implementation, security and economic proof",
    },
    {
        "node_id": "b2b-ai",
        "label": "artificial intelligence",
        "aliases": ("ai", "generative ai", "machine learning", "agent", "foundation model"),
        "subcategories": ("infrastructure", "model platform", "agent", "copilot", "vertical application", "evaluation"),
        "buying_system": "capability evidence, workflow fit, governance and measured labor or revenue impact",
    },
    {
        "node_id": "b2b-manufacturing",
        "label": "manufacturing",
        "aliases": ("industrial", "factory", "plant", "oem", "production"),
        "subcategories": ("discrete", "process", "electronics", "automotive", "food", "medical device", "contract manufacturing"),
        "buying_system": "throughput, quality, downtime, safety, integration and payback proof",
    },
    {
        "node_id": "b2b-engineering",
        "label": "engineering",
        "aliases": ("engineering services", "construction", "civil", "mep", "architecture", "infrastructure"),
        "subcategories": ("civil", "structural", "mep", "architecture", "energy", "industrial", "construction technology"),
        "buying_system": "technical credibility, delivery risk, compliance, schedule and lifecycle-cost proof",
    },
    {
        "node_id": "b2b-real-estate",
        "label": "real estate",
        "aliases": ("property", "proptech", "commercial property", "residential property", "property management"),
        "subcategories": ("commercial", "residential", "brokerage", "property management", "development", "facilities", "proptech"),
        "buying_system": "local demand, asset economics, trust, transaction friction and regulatory proof",
    },
    {
        "node_id": "b2b-professional-services",
        "label": "professional services",
        "aliases": ("consulting", "legal", "accounting", "recruiting", "agency", "advisory"),
        "subcategories": ("consulting", "legal", "accounting", "talent", "marketing agency", "research", "advisory"),
        "buying_system": "expertise signal, diagnostic specificity, trust, conflict management and outcome proof",
    },
    {
        "node_id": "b2b-supply-chain",
        "label": "supply chain",
        "aliases": ("logistics", "freight", "warehouse", "procurement", "shipping", "distribution"),
        "subcategories": ("procurement", "freight", "warehousing", "last mile", "planning", "trade", "reverse logistics"),
        "buying_system": "service level, resilience, cost-to-serve, visibility and exception-handling proof",
    },
    {
        "node_id": "b2b-enterprise-services",
        "label": "enterprise services",
        "aliases": ("managed services", "it services", "bpo", "facilities", "outsourcing", "business services"),
        "subcategories": ("managed IT", "business process", "facilities", "security services", "support", "field service"),
        "buying_system": "operational continuity, governance, service level, transition risk and total-cost proof",
    },
)


_B2C_GRAPH: tuple[dict[str, object], ...] = (
    {
        "node_id": "b2c-mobile-apps",
        "label": "mobile applications",
        "aliases": ("ios", "android", "mobile app", "app", "consumer software"),
        "subcategories": ("productivity", "photo and video", "social", "utilities", "lifestyle", "shopping", "games"),
        "decision_system": "instant comprehension, first-session value, permission trust and retention trigger",
    },
    {
        "node_id": "b2c-consumer-goods",
        "label": "consumer goods",
        "aliases": ("consumer product", "cpg", "retail", "ecommerce", "beauty", "home goods"),
        "subcategories": ("beauty", "food and beverage", "apparel", "home", "electronics", "personal care", "pet"),
        "decision_system": "sensory promise, identity, social proof, availability and purchase-friction closure",
    },
    {
        "node_id": "b2c-education",
        "label": "education",
        "aliases": ("learning", "course", "tutoring", "edtech", "language learning"),
        "subcategories": ("language", "career", "school", "creator education", "tutoring", "test preparation"),
        "decision_system": "credible progress, effort realism, teaching fit, proof of mastery and continuation habit",
    },
    {
        "node_id": "b2c-health",
        "label": "health and wellness",
        "aliases": ("health", "wellness", "fitness", "nutrition", "mental health", "care"),
        "subcategories": ("fitness", "nutrition", "sleep", "mental wellbeing", "care navigation", "women's health"),
        "decision_system": "felt need, safety, qualified evidence, privacy, adherence and non-guaranteed outcome framing",
    },
    {
        "node_id": "b2c-travel",
        "label": "travel",
        "aliases": ("trip", "hotel", "flight", "tourism", "vacation", "mobility"),
        "subcategories": ("planning", "lodging", "transport", "experiences", "business travel", "local discovery"),
        "decision_system": "dream-to-decision compression, availability, price clarity, trust and disruption recovery",
    },
    {
        "node_id": "b2c-finance",
        "label": "consumer finance",
        "aliases": ("finance", "fintech", "banking", "investing", "insurance", "payments"),
        "subcategories": ("banking", "payments", "investing", "insurance", "credit", "budgeting", "tax"),
        "decision_system": "security, suitability, fee transparency, downside clarity and regulated-claim discipline",
    },
    {
        "node_id": "b2c-local-services",
        "label": "local services",
        "aliases": ("local service", "home service", "restaurant", "salon", "repair", "clinic"),
        "subcategories": ("home", "repair", "beauty", "food", "care", "events", "professional local"),
        "decision_system": "proximity, urgency, availability, reputation, price confidence and booking friction",
    },
    {
        "node_id": "b2c-media-entertainment",
        "label": "media and entertainment",
        "aliases": ("media", "entertainment", "music", "video", "creator", "streaming"),
        "subcategories": ("video", "music", "publishing", "creator tools", "live", "fan community"),
        "decision_system": "attention promise, taste identity, novelty, participation and repeat-consumption loop",
    },
)


_REGIONS: tuple[dict[str, object], ...] = (
    {"region_id": "us", "label": "United States", "aliases": ("us", "usa", "united states", "america"), "language_tag": "en-US", "default_style": "direct, concrete and evidence-forward", "localization_checks": ("state-level regulation", "price and tax clarity", "accessible inclusive language")},
    {"region_id": "ca", "label": "Canada", "aliases": ("ca", "canada"), "language_tag": "en-CA", "default_style": "clear, measured and locally specific", "localization_checks": ("province-level regulation", "English/French obligations where applicable", "currency and tax clarity")},
    {"region_id": "gb", "label": "United Kingdom", "aliases": ("uk", "gb", "united kingdom", "britain", "england"), "language_tag": "en-GB", "default_style": "plain-spoken, specific and resistant to hype", "localization_checks": ("UK spelling", "ASA/CAP claim discipline", "VAT and price clarity")},
    {"region_id": "au", "label": "Australia", "aliases": ("au", "australia"), "language_tag": "en-AU", "default_style": "plain, useful and low on inflated claims", "localization_checks": ("Australian spelling", "ACCC claim discipline", "local time and season")},
    {"region_id": "sg", "label": "Singapore", "aliases": ("sg", "singapore"), "language_tag": "en-SG", "default_style": "compact, pragmatic and regionally aware", "localization_checks": ("PDPA relevance", "Singapore dollars", "multicultural audience assumptions")},
    {"region_id": "hk", "label": "Hong Kong", "aliases": ("hk", "hong kong"), "language_tag": "en-HK", "default_style": "concise, commercially specific and bilingual-ready", "localization_checks": ("English/Traditional Chinese handoff", "Hong Kong dollars", "sector-specific regulation")},
    {"region_id": "za", "label": "South Africa", "aliases": ("za", "south africa"), "language_tag": "en-ZA", "default_style": "clear, context-aware and value specific", "localization_checks": ("rand pricing", "POPIA relevance", "avoid treating one English register as nationally universal")},
)


def _resolve_node(value: object, graph: Sequence[Mapping[str, object]]) -> dict[str, Any]:
    query_tokens = _tokens(value)
    ranked: list[tuple[float, str, Mapping[str, object]]] = []
    for node in graph:
        phrases = (str(node["label"]), *tuple(node.get("aliases", ())), *tuple(node.get("subcategories", ())))
        best = 0.0
        for phrase_index, phrase in enumerate(phrases):
            candidate_tokens = _tokens(phrase)
            if not candidate_tokens or not query_tokens:
                continue
            overlap = len(query_tokens & candidate_tokens)
            score = overlap / len(query_tokens | candidate_tokens)
            if str(value).casefold().strip() == phrase.casefold().strip():
                score = 1.0
            elif candidate_tokens.issubset(query_tokens):
                score = max(score, 0.9 if phrase_index == 0 else 0.75)
            best = max(best, score)
        if best > 0:
            ranked.append((best, str(node["node_id"]), node))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return {
            "status": "unresolved_owner_input_required",
            "declared_value": str(value),
            "node_id": None,
            "confidence": 0.0,
            "candidate_node_ids": [],
        }
    score, _, node = ranked[0]
    return {
        "status": "resolved" if score >= 0.34 else "provisional_human_confirmation_required",
        "declared_value": str(value),
        "node_id": node["node_id"],
        "label": node["label"],
        "confidence": round(score, 6),
        "subcategories": list(node.get("subcategories", ())),
        "decision_system": node.get("buying_system") or node.get("decision_system"),
        "candidate_node_ids": [item[1] for item in ranked[:3]],
    }


def _resolve_region(value: object) -> dict[str, Any]:
    query = str(value or "").casefold().strip()
    for region in _REGIONS:
        if query in {str(alias).casefold() for alias in region["aliases"]}:
            return {
                "status": "resolved",
                "declared_value": str(value),
                "region_id": region["region_id"],
                "label": region["label"],
                "language_tag": region["language_tag"],
                "default_style": region["default_style"],
                "localization_checks": list(region["localization_checks"]),
                "human_localization_review_required": True,
            }
    return {
        "status": "unresolved_owner_input_required",
        "declared_value": str(value),
        "region_id": None,
        "language_tag": None,
        "human_localization_review_required": True,
    }


def _valid_time(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _candidate_score(query: Mapping[str, object], candidate: Mapping[str, object]) -> tuple[float, list[dict[str, object]]]:
    dimensions = (
        ("business_model", 18.0),
        ("taxonomy_node_id", 22.0),
        ("market_region_id", 12.0),
        ("price_band", 12.0),
        ("sales_cycle", 12.0),
        ("company_scale", 10.0),
        ("budget", 7.0),
        ("brand_reach", 7.0),
    )
    weighted = 0.0
    available = 0.0
    evidence: list[dict[str, object]] = []
    for field, weight in dimensions:
        expected = query.get(field)
        actual = candidate.get(field)
        if expected in (None, "", "unknown") or actual in (None, "", "unknown"):
            continue
        available += weight
        matched = str(expected).casefold() == str(actual).casefold()
        if matched:
            weighted += weight
        evidence.append({"dimension": field, "matched": matched, "weight": weight})
    return ((weighted / available) if available else 0.0), evidence


def compile_market_neighborhood(
    context: Mapping[str, object],
    *,
    candidates: Sequence[Mapping[str, object]] = (),
    maximum_neighbors: int = 5,
) -> dict[str, Any]:
    """Resolve market taxonomy and rank evidence-bound comparable companies.

    Missing price or sales-cycle inputs stay explicit gaps. The function never
    invents a company, converts a similarity score into causal proof, or copies
    candidate creative expression into the result.
    """

    business_model = str(context.get("business_model") or "")
    if business_model not in {"b2b", "b2c"}:
        raise MarketNeighborhoodError("business_model must be b2b or b2c")
    if isinstance(maximum_neighbors, bool) or not 1 <= maximum_neighbors <= 20:
        raise MarketNeighborhoodError("maximum_neighbors must be between 1 and 20")
    declared_taxonomy = context.get("industry") if business_model == "b2b" else context.get("product_category")
    taxonomy = _resolve_node(declared_taxonomy, _B2B_GRAPH if business_model == "b2b" else _B2C_GRAPH)
    region = _resolve_region(context.get("market"))
    query = {
        "business_model": business_model,
        "taxonomy_node_id": taxonomy.get("node_id"),
        "market_region_id": region.get("region_id"),
        "price_band": context.get("price_band") or "unknown",
        "sales_cycle": context.get("sales_cycle") or "unknown",
        "company_scale": context.get("company_scale") or "unknown",
        "budget": context.get("budget") or "unknown",
        "brand_reach": context.get("brand_reach") or "unknown",
    }
    unresolved_dimensions = [field for field, value in query.items() if value in (None, "", "unknown")]

    ranked: list[dict[str, Any]] = []
    rejected_counts: dict[str, int] = {}
    for candidate in candidates:
        failures: list[str] = []
        candidate_id = candidate.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            failures.append("candidate_id_missing")
        uri = candidate.get("source_uri")
        parsed = urlparse(str(uri or ""))
        if parsed.scheme != "https" or not parsed.hostname:
            failures.append("public_or_authorized_source_missing")
        digest = candidate.get("source_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            failures.append("source_sha256_invalid")
        if not _valid_time(candidate.get("observed_at")):
            failures.append("observed_at_invalid")
        if candidate.get("rights_status") not in {"public_measurement", "licensed", "owner_approved"}:
            failures.append("rights_status_not_admissible")
        if failures:
            for failure in failures:
                rejected_counts[failure] = rejected_counts.get(failure, 0) + 1
            continue
        score, dimension_evidence = _candidate_score(query, candidate)
        ranked.append(
            {
                "candidate_id": candidate_id,
                "source_uri": uri,
                "source_sha256": digest,
                "observed_at": candidate["observed_at"],
                "rights_status": candidate["rights_status"],
                "similarity_score": round(score, 6),
                "dimension_evidence": dimension_evidence,
                "creative_expression_retained": False,
                "causal_transfer_claim_allowed": False,
                "human_case_review_required": True,
            }
        )
    ranked.sort(key=lambda row: (-float(row["similarity_score"]), str(row["candidate_id"])))
    ranked = ranked[:maximum_neighbors]
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "business_model": business_model,
        "taxonomy_graph_version": "2026-08-05-v1",
        "taxonomy_root_count": len(_B2B_GRAPH if business_model == "b2b" else _B2C_GRAPH),
        "taxonomy_resolution": taxonomy,
        "regional_language_graph_version": "2026-08-05-v1",
        "supported_region_count": len(_REGIONS),
        "regional_language_resolution": region,
        "similar_company_query": query,
        "unresolved_query_dimensions": unresolved_dimensions,
        "candidate_input_count": len(candidates),
        "admitted_neighbor_count": len(ranked),
        "rejected_candidate_counts": dict(sorted(rejected_counts.items())),
        "neighbors": ranked,
        "automatic_strategy_mutation_executed": False,
        "automatic_training_admission_executed": False,
        "truth_boundary": (
            "Taxonomy resolution and weighted proximity are retrieval aids, not evidence that a "
            "neighbor caused growth or that its tactic will transfer. Missing price and sales-cycle "
            "inputs remain explicit, and every case requires named-human review."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_market_neighborhood(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise MarketNeighborhoodError("market neighborhood seal is invalid")
    neighbors = payload.get("neighbors")
    if not isinstance(neighbors, list) or payload.get("admitted_neighbor_count") != len(neighbors):
        raise MarketNeighborhoodError("market neighborhood count drifted")
    if payload.get("automatic_strategy_mutation_executed") is not False:
        raise MarketNeighborhoodError("market neighborhood cannot mutate strategy")
    previous = math.inf
    for neighbor in neighbors:
        score = neighbor.get("similarity_score") if isinstance(neighbor, Mapping) else None
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= float(score) <= previous:
            raise MarketNeighborhoodError("market neighbors are not deterministically ranked")
        previous = float(score)
