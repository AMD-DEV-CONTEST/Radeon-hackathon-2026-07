from __future__ import annotations

from collections import Counter
import copy
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit

from .gtm_final_acceptance_matrix_v2 import B2B_GOLD, B2C_GOLD


SCHEMA = "ProofLaunchGTMGoldCaseDiscoveryV2"
GOLD_SUBVERTICALS = B2B_GOLD + B2C_GOLD
MARKETS = (
    "north_america",
    "uk_ireland",
    "europe_english",
    "australia_new_zealand",
    "singapore",
    "hong_kong",
    "southern_africa",
    "multi_market",
)
OUTCOME_INTENTS = (
    "recent_breakout",
    "durable_repeat",
    "failed_or_stalled",
    "mature_control",
    "turnaround",
)
QUERY_MODES = ("official_case", "independent_outcome", "first_party_result")
TARGETED_DISCOVERY_METHODS = {
    "operator_reviewed_public_search_result",
    "model_assisted_public_search_result",
}


class GTMGoldCaseDiscoveryError(ValueError):
    pass


SOURCE_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "source_family_id": "hubspot_case_directory",
        "source_class": "vendor_case_directory",
        "access_mode": "ordinary_public_https",
        "discovery_role": "structured case lead discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "tiktok_business_success_stories",
        "source_class": "platform_case_directory",
        "access_mode": "ordinary_public_https_or_documented_public_endpoint",
        "discovery_role": "platform execution and reported outcome discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "meta_business_success_stories",
        "source_class": "platform_case_directory",
        "access_mode": "ordinary_public_https_or_documented_public_endpoint",
        "discovery_role": "platform execution and reported outcome discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "think_with_google_case_studies",
        "source_class": "platform_case_directory",
        "access_mode": "ordinary_public_https",
        "discovery_role": "search, video, app, and measurement case discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "public_award_archives",
        "source_class": "industry_award_archive",
        "access_mode": "ordinary_public_https_only",
        "discovery_role": "creative and effectiveness mechanism discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "company_newsroom_and_ir",
        "source_class": "first_party_company",
        "access_mode": "ordinary_public_https",
        "discovery_role": "dated launch, resource, and business-result corroboration",
        "candidate_credit": 0,
        "independent_corroboration_required": False,
    },
    {
        "source_family_id": "independent_trade_press",
        "source_class": "independent_editorial",
        "access_mode": "ordinary_public_https_only",
        "discovery_role": "independent episode and outcome corroboration",
        "candidate_credit": 0,
        "independent_corroboration_required": False,
    },
    {
        "source_family_id": "public_social_and_video_pages",
        "source_class": "public_platform_page",
        "access_mode": "ordinary_public_https_or_official_api",
        "discovery_role": "creative, comment, CTA, timing, and follow-up evidence",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "public_podcast_and_rss_archives",
        "source_class": "public_owned_or_editorial",
        "access_mode": "ordinary_public_https_or_rss",
        "discovery_role": "founder narrative, timeline, constraints, and failure discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "public_launch_directories",
        "source_class": "public_community_directory",
        "access_mode": "ordinary_public_https",
        "discovery_role": "launch episode and public reaction discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "targeted_public_case_pages",
        "source_class": "public_vendor_or_platform_case_page",
        "access_mode": "ordinary_public_https_only",
        "discovery_role": "close explicit subvertical source gaps with directly reviewable public case pages",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "gorilla76_industrial_case_directory",
        "source_class": "industrial_marketing_vendor_case_directory",
        "access_mode": "ordinary_public_https",
        "discovery_role": "industrial equipment, manufacturing, and engineering/construction case discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
    {
        "source_family_id": "athena_manufacturing_case_directory",
        "source_class": "manufacturing_sales_vendor_case_directory",
        "access_mode": "ordinary_public_https",
        "discovery_role": "manufacturing and industrial-equipment case discovery",
        "candidate_credit": 0,
        "independent_corroboration_required": True,
    },
)


SUBVERTICAL_TERMS: Mapping[str, tuple[str, ...]] = {
    "b2b.industrial_climate.manufacturing": ("manufacturing", "manufacturer", "factory", "materials", "components"),
    "b2b.industrial_climate.industrial_equipment": ("industrial equipment", "machinery", "robotics", "instrumentation", "industrial hardware"),
    "b2b.industrial_climate.engineering_construction": ("engineering", "construction", "architecture", "infrastructure", "contractor"),
    "b2b.industrial_climate.commercial_real_estate": ("commercial real estate", "property", "brokerage", "leasing", "workplace"),
    "b2b.professional_services.consulting": ("consulting", "professional services", "advisory", "agency", "implementation partner"),
    "b2c.consumer_ai_mobile_apps.creative_apps": ("consumer AI creative app", "AI photo app", "AI video app", "mobile creator app", "generative design app"),
    "b2c.health_wellness.fitness": ("fitness", "workout", "gym", "running", "training app"),
    "b2c.beauty_fashion.beauty": ("beauty", "skincare", "cosmetics", "makeup", "haircare"),
    "b2c.food_beverage.consumer_packaged_goods": ("consumer packaged goods", "food brand", "beverage brand", "snack", "grocery product"),
    "b2c.travel_hospitality.destinations": ("destination marketing", "tourism", "travel", "visitor bureau", "city campaign"),
}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme.casefold() != "https" or not parts.hostname or parts.username or parts.password:
        raise GTMGoldCaseDiscoveryError("case discovery accepts only credential-free HTTPS URLs")
    hostname = parts.hostname.casefold()
    port = f":{parts.port}" if parts.port and parts.port != 443 else ""
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit(("https", hostname + port, path, "", ""))


def _tokens(*values: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", " ".join(values).casefold()))


class _HubSpotDirectoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, Any]] = []
        self._card: dict[str, Any] | None = None
        self._card_li_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "li" and self._card is not None:
            self._card_li_depth += 1
        elif tag == "li" and "csl-directory-cards__card" in classes:
            self._card = {
                "industry": attributes.get("data-industry", "").strip(),
                "company_size": attributes.get("data-size", "").strip(),
                "products": attributes.get("data-products", "").strip("[]"),
                "use_cases": attributes.get("data-usecases", "").strip("[]"),
                "sort_tags": attributes.get("data-sort", "").strip("[]"),
                "title": "",
                "company": "",
                "source_url": "",
            }
            self._card_li_depth = 1
        if self._card is None:
            return
        if tag == "h3" and "csl-card-title" in classes:
            self._in_title = True
            self._title_parts = []
        if tag == "img" and not self._card["company"]:
            self._card["company"] = attributes.get("alt", "").strip()
        if tag == "a" and "/case-studies/" in attributes.get("href", ""):
            self._card["source_url"] = attributes["href"].strip()

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "h3" and self._in_title:
            self._card["title"] = re.sub(r"\s+", " ", " ".join(self._title_parts)).strip()
            self._in_title = False
        if tag == "li":
            self._card_li_depth -= 1
            if self._card_li_depth == 0:
                if self._card["source_url"] and self._card["title"]:
                    self.cards.append(self._card)
                self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._in_title:
            text = " ".join(data.split())
            if text:
                self._title_parts.append(text)


def extract_hubspot_directory_cards(html_text: str) -> list[dict[str, Any]]:
    parser = _HubSpotDirectoryParser()
    parser.feed(html_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in parser.cards:
        url = _canonical_url(str(card["source_url"]))
        path = urlsplit(url).path
        if path in {"/case-studies/directory", "/case-studies/all"} or "/directory/" in path:
            continue
        if url in seen:
            continue
        seen.add(url)
        records.append({**card, "source_url": url})
    return records


class _TikTokDirectoryParser(HTMLParser):
    def __init__(self, directory_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.directory_url = directory_url
        self.cards: list[dict[str, Any]] = []
        self._card: dict[str, Any] | None = None
        self._div_depth = 0
        self._capture_field = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "div" and self._card is not None:
            self._div_depth += 1
        elif tag == "div" and "tt4b-aggregator-card-container" in classes:
            self._card = {
                "industry": "",
                "company_size": "",
                "products": "",
                "use_cases": "",
                "sort_tags": "Newest",
                "title": "",
                "company": "",
                "source_url": "",
                "source_excerpt": "",
                "published_label": "",
            }
            self._div_depth = 1
        if self._card is None:
            return
        if attributes.get("data-click_for") == "case_study" and attributes.get("data-url"):
            self._card["source_url"] = urljoin(self.directory_url, attributes["data-url"])
        if tag == "span" and "razz" in classes:
            self._capture_field = "industry"
            self._parts = []
        elif tag == "h3" and "card-title" in classes:
            self._capture_field = "company"
            self._parts = []
            if attributes.get("title"):
                self._card["company"] = attributes["title"].strip()
        elif tag == "p" and "card-excerpt" in classes:
            self._capture_field = "source_excerpt"
            self._parts = []
        elif tag == "div" and "card-time-text" in classes:
            self._capture_field = "published_label"
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if self._capture_field and tag in {"span", "h3", "p", "div"}:
            value = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            if value:
                self._card[self._capture_field] = value
                if self._capture_field == "source_excerpt":
                    self._card["title"] = value
            self._capture_field = ""
            self._parts = []
        if tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                if self._card["source_url"] and (self._card["company"] or self._card["title"]):
                    self.cards.append(self._card)
                self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._capture_field:
            text = " ".join(data.split())
            if text:
                self._parts.append(text)


def extract_tiktok_directory_cards(html_text: str, directory_url: str) -> list[dict[str, Any]]:
    parser = _TikTokDirectoryParser(directory_url)
    parser.feed(html_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in parser.cards:
        url = _canonical_url(str(card["source_url"]))
        if url in seen:
            continue
        seen.add(url)
        records.append({**card, "source_url": url})
    return records


class _IndustrialCaseDirectoryParser(HTMLParser):
    def __init__(self, directory_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.directory_url = directory_url
        self.cards: list[dict[str, Any]] = []
        self._card: dict[str, Any] | None = None
        self._div_depth = 0
        self._capture_field = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "div" and self._card is not None:
            self._div_depth += 1
        elif tag == "div" and "case-study__entry" in classes:
            self._card = {
                "industry": "industrial_b2b",
                "company_size": "",
                "products": "",
                "use_cases": "",
                "sort_tags": "",
                "title": "",
                "company": "",
                "source_url": "",
                "source_excerpt": "",
                "published_label": "",
                "provisional_subvertical_ids": [],
                "disable_generic_keyword_routes": True,
            }
            self._div_depth = 1
        if self._card is None:
            return
        if tag == "a" and "case-study__entry-title-link" in classes:
            self._card["source_url"] = urljoin(self.directory_url, attributes.get("href", ""))
            self._capture_field = "title"
            self._parts = []
        elif tag == "p" and "case-study__entry-description" in classes:
            self._capture_field = "source_excerpt"
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if self._capture_field and tag in {"a", "p"}:
            value = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            if value:
                self._card[self._capture_field] = value
            self._capture_field = ""
            self._parts = []
        if tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                if self._card["source_url"] and self._card["title"]:
                    self.cards.append(self._card)
                self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._capture_field:
            text = " ".join(data.split())
            if text:
                self._parts.append(text)


def extract_industrial_case_directory_cards(html_text: str, directory_url: str) -> list[dict[str, Any]]:
    parser = _IndustrialCaseDirectoryParser(directory_url)
    parser.feed(html_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    equipment_terms = {"equipment", "machinery", "oven", "generator", "engine", "bandsaw", "automation"}
    manufacturing_terms = {
        "manufacturer", "manufacturing", "processor", "material", "bioplastics", "coatings", "cable", "steel", "pipe"
    }
    construction_terms = {"construction", "contractor", "builder", "flooring", "geotechnical", "painter"}
    for card in parser.cards:
        url = _canonical_url(str(card["source_url"]))
        if url in seen:
            continue
        seen.add(url)
        tokens = _tokens(str(card.get("title", "")), str(card.get("source_excerpt", "")))
        routes: set[str] = set()
        if tokens & equipment_terms:
            routes.add("b2b.industrial_climate.industrial_equipment")
        if tokens & manufacturing_terms:
            routes.add("b2b.industrial_climate.manufacturing")
        if tokens & construction_terms:
            routes.add("b2b.industrial_climate.engineering_construction")
        records.append({**card, "source_url": url, "provisional_subvertical_ids": sorted(routes)})
    return records


class _CaseStudyAnchorParser(HTMLParser):
    def __init__(self, directory_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.directory_url = directory_url
        self.links: list[dict[str, str]] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attributes = {key: value or "" for key, value in attrs}
        href = attributes.get("href", "")
        absolute = urljoin(self.directory_url, href)
        path = urlsplit(absolute).path.rstrip("/")
        if "/case-studies/" not in path or path.endswith("/case-studies"):
            return
        self._href = absolute
        self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            self.links.append({"source_url": self._href, "title": text})
            self._href = ""
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            text = " ".join(data.split())
            if text:
                self._parts.append(text)


def extract_athena_manufacturing_case_cards(html_text: str, directory_url: str) -> list[dict[str, Any]]:
    parser = _CaseStudyAnchorParser(directory_url)
    parser.feed(html_text)
    titles_by_url: dict[str, str] = {}
    for link in parser.links:
        try:
            url = _canonical_url(link["source_url"])
        except GTMGoldCaseDiscoveryError:
            continue
        parts = urlsplit(url)
        if parts.hostname == "athenaswc.com":
            url = urlunsplit((parts.scheme, "www.athenaswc.com", parts.path, "", ""))
        title = link["title"].strip()
        if len(title) > len(titles_by_url.get(url, "")):
            titles_by_url[url] = title
    manufacturing_terms = {
        "manufacturer", "manufacturing", "machining", "metal", "plastic", "packaging", "hardware", "electronics",
        "tooling", "mfg", "fabricator", "fabrication", "corrugated", "label", "extrusion", "molder", "stamping", "plastics",
        "thermal", "precision", "box", "container", "cdmo",
    }
    equipment_terms = {"equipment", "machinery", "machine", "tooling", "device", "automation"}
    records: list[dict[str, Any]] = []
    for url, anchor_title in sorted(titles_by_url.items()):
        slug_text = urlsplit(url).path.replace("-", " ").replace("_", " ")
        tokens = _tokens(anchor_title, slug_text)
        routes: set[str] = set()
        if tokens & manufacturing_terms:
            routes.add("b2b.industrial_climate.manufacturing")
        if tokens & equipment_terms:
            routes.add("b2b.industrial_climate.industrial_equipment")
        if not anchor_title:
            anchor_title = urlsplit(url).path.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ")
        records.append({
            "industry": "industrial_case_directory",
            "company_size": "",
            "products": "",
            "use_cases": "",
            "sort_tags": "",
            "title": anchor_title,
            "company": "",
            "source_url": url,
            "source_excerpt": "",
            "published_label": "",
            "provisional_subvertical_ids": sorted(routes),
            "disable_generic_keyword_routes": True,
        })
    return records


def _route_card(card: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    industry = str(card.get("industry", "")).casefold()
    title = str(card.get("title", ""))
    company = str(card.get("company", ""))
    text = " ".join((
        industry, title, company, str(card.get("use_cases", "")), str(card.get("source_excerpt", ""))
    )).casefold()
    token_set = _tokens(text)
    routes: set[str] = set()
    reasons: list[str] = []

    explicit_routes = set(str(value) for value in card.get("provisional_subvertical_ids", ()))
    if not explicit_routes.issubset(GOLD_SUBVERTICALS):
        raise GTMGoldCaseDiscoveryError("parser emitted a non-gold provisional route")
    if explicit_routes:
        routes.update(explicit_routes)
        reasons.append("directory-specific industrial taxonomy route; final classification unresolved")

    exact_industry = {
        "manufacturing": "b2b.industrial_climate.manufacturing",
        "construction": "b2b.industrial_climate.engineering_construction",
        "architecture & planning": "b2b.industrial_climate.engineering_construction",
        "real estate": "b2b.industrial_climate.commercial_real_estate",
        "professional services": "b2b.professional_services.consulting",
        "sports & fitness": "b2c.health_wellness.fitness",
        "travel & leisure": "b2c.travel_hospitality.destinations",
    }
    if industry in exact_industry:
        routes.add(exact_industry[industry])
        reasons.append(f"exact directory industry: {card.get('industry')}")

    keyword_routes = {
        "b2b.industrial_climate.industrial_equipment": {"equipment", "machinery", "robotics", "instrumentation"},
        "b2c.consumer_ai_mobile_apps.creative_apps": {"generative", "creator", "creative", "photo", "video", "design", "image"},
        "b2c.beauty_fashion.beauty": {"beauty", "skincare", "cosmetic", "cosmetics", "makeup", "haircare"},
        "b2c.food_beverage.consumer_packaged_goods": {"food", "beverage", "snack", "drink", "grocery"},
        "b2c.travel_hospitality.destinations": {"tourism", "destination", "travel", "visitor"},
    }
    if not card.get("disable_generic_keyword_routes"):
        for subvertical_id, keywords in keyword_routes.items():
            matched = sorted(token_set & keywords)
            if matched:
                routes.add(subvertical_id)
                reasons.append(f"title/company/use-case keywords for {subvertical_id}: {', '.join(matched)}")

    if industry == "consumer goods" and not routes.intersection({
        "b2c.beauty_fashion.beauty", "b2c.food_beverage.consumer_packaged_goods"
    }):
        routes.update(("b2c.beauty_fashion.beauty", "b2c.food_beverage.consumer_packaged_goods"))
        reasons.append("broad Consumer Goods directory tag; manual disambiguation required")
    if industry == "food & hospitality" and "b2c.food_beverage.consumer_packaged_goods" not in routes:
        routes.update(("b2c.food_beverage.consumer_packaged_goods", "b2c.travel_hospitality.destinations"))
        reasons.append("broad Food & Hospitality directory tag; manual disambiguation required")
    if industry == "software & technology" and token_set.intersection({"app", "mobile", "creator", "creative"}):
        routes.add("b2c.consumer_ai_mobile_apps.creative_apps")
        reasons.append("software/app and creative keyword intersection; consumer/AI status unresolved")

    if industry in {"makeup & beauty", "beauty"}:
        routes.add("b2c.beauty_fashion.beauty")
        reasons.append(f"exact platform category: {card.get('industry')}")
    if industry in {"fitness", "sports & fitness"}:
        routes.add("b2c.health_wellness.fitness")
        reasons.append(f"exact platform category: {card.get('industry')}")
    if industry in {"food & beverage", "food and beverage"}:
        routes.add("b2c.food_beverage.consumer_packaged_goods")
        reasons.append(f"exact platform category: {card.get('industry')}")
    if industry in {"travel", "travel & leisure"}:
        routes.add("b2c.travel_hospitality.destinations")
        reasons.append(f"exact platform category: {card.get('industry')}")
    if industry == "professional services":
        routes.add("b2b.professional_services.consulting")
        reasons.append("platform category is Professional services; consulting status remains provisional")

    return sorted(routes), reasons


def build_query_matrix() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for subvertical_id in GOLD_SUBVERTICALS:
        terms = SUBVERTICAL_TERMS[subvertical_id]
        for market in MARKETS:
            for outcome_intent in OUTCOME_INTENTS:
                for query_mode in QUERY_MODES:
                    query_id = f"{subvertical_id}:{market}:{outcome_intent}:{query_mode}"
                    query = " ".join((terms[0], market.replace("_", " "), outcome_intent.replace("_", " "), query_mode.replace("_", " "), "case study"))
                    records.append({
                        "query_id": query_id,
                        "subvertical_id": subvertical_id,
                        "quota_market": market,
                        "outcome_intent": outcome_intent,
                        "query_mode": query_mode,
                        "query": query,
                        "status": "prepared_not_executed",
                        "quota_credit": 0,
                    })
    return records


def compile_gold_case_discovery(
    snapshots: Sequence[Mapping[str, Any]],
    *,
    research_cutoff: str,
    targeted_leads: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    leads_by_url: dict[str, dict[str, Any]] = {}
    snapshot_receipts: list[dict[str, Any]] = []
    for snapshot in snapshots:
        source_family_id = str(snapshot.get("source_family_id") or "")
        source_url = _canonical_url(str(snapshot.get("source_url") or ""))
        html_text = str(snapshot.get("html_text") or "")
        body_sha256 = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
        supplied_sha256 = str(snapshot.get("content_sha256") or body_sha256)
        if supplied_sha256 != body_sha256:
            raise GTMGoldCaseDiscoveryError("snapshot content hash does not match supplied HTML")
        if source_family_id == "hubspot_case_directory":
            cards = extract_hubspot_directory_cards(html_text)
        elif source_family_id == "tiktok_business_success_stories":
            cards = extract_tiktok_directory_cards(html_text, source_url)
        elif source_family_id == "gorilla76_industrial_case_directory":
            cards = extract_industrial_case_directory_cards(html_text, source_url)
        elif source_family_id == "athena_manufacturing_case_directory":
            cards = extract_athena_manufacturing_case_cards(html_text, source_url)
        else:
            raise GTMGoldCaseDiscoveryError(f"unsupported snapshot parser: {source_family_id}")
        snapshot_receipts.append({
            "source_family_id": source_family_id,
            "source_url": source_url,
            "captured_at": str(snapshot.get("captured_at") or ""),
            "content_sha256": body_sha256,
            "response_byte_count": len(html_text.encode("utf-8")),
            "extracted_card_count": len(cards),
            "raw_page_retained_in_artifact": False,
            "authentication_used": False,
            "captcha_bypass_used": False,
            "paywall_bypass_used": False,
            "quota_credit": 0,
        })
        for card in cards:
            routes, reasons = _route_card(card)
            url = card["source_url"]
            existing = leads_by_url.get(url)
            if existing is None:
                lead_id = "gold-lead-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
                existing = {
                    "lead_id": lead_id,
                    "source_url": url,
                    "source_family_ids": [],
                    "source_directory_urls": [],
                    "source_snapshot_sha256s": [],
                    "company": card.get("company", ""),
                    "title": card.get("title", ""),
                    "directory_industry": card.get("industry", ""),
                    "directory_company_size": card.get("company_size", ""),
                    "directory_products": card.get("products", ""),
                    "directory_use_cases": card.get("use_cases", ""),
                    "directory_sort_tags": card.get("sort_tags", ""),
                    "source_excerpt": card.get("source_excerpt", ""),
                    "source_published_label": card.get("published_label", ""),
                    "provisional_subvertical_ids": [],
                    "routing_reasons": [],
                    "status": "discovery_lead_only",
                    "company_scale_status": "unresolved",
                    "episode_identity_status": "unresolved",
                    "budget_status": "unresolved",
                    "market_status": "unresolved",
                    "observed_period_status": "unresolved",
                    "outcome_verification_status": "unresolved",
                    "independent_corroboration_status": "unresolved",
                    "automatic_promotion_allowed": False,
                    "quota_credit": 0,
                }
                leads_by_url[url] = existing
            existing["source_family_ids"] = sorted(set(existing["source_family_ids"]) | {source_family_id})
            existing["source_directory_urls"] = sorted(set(existing["source_directory_urls"]) | {source_url})
            existing["source_snapshot_sha256s"] = sorted(set(existing["source_snapshot_sha256s"]) | {body_sha256})
            existing["provisional_subvertical_ids"] = sorted(set(existing["provisional_subvertical_ids"]) | set(routes))
            existing["routing_reasons"] = sorted(set(existing["routing_reasons"]) | set(reasons))

    source_family_ids = {row["source_family_id"] for row in SOURCE_FAMILIES}
    targeted_receipts: list[dict[str, Any]] = []
    for raw_lead in targeted_leads:
        source_family_id = str(raw_lead.get("source_family_id") or "")
        if source_family_id not in source_family_ids:
            raise GTMGoldCaseDiscoveryError("targeted lead has an unsupported source family")
        url = _canonical_url(str(raw_lead.get("source_url") or ""))
        routes = sorted(set(str(value) for value in raw_lead.get("provisional_subvertical_ids", ())))
        if not routes or not set(routes).issubset(GOLD_SUBVERTICALS):
            raise GTMGoldCaseDiscoveryError("targeted lead routes must be non-empty gold subvertical IDs")
        company = str(raw_lead.get("company") or "").strip()
        title = str(raw_lead.get("title") or "").strip()
        if not company or not title:
            raise GTMGoldCaseDiscoveryError("targeted lead requires company and title")
        discovery_method = str(
            raw_lead.get("discovery_method") or "operator_reviewed_public_search_result"
        )
        if discovery_method not in TARGETED_DISCOVERY_METHODS:
            raise GTMGoldCaseDiscoveryError("targeted lead discovery method is invalid")
        receipt_basis = {
            "source_url": url,
            "source_family_id": source_family_id,
            "company": company,
            "title": title,
            "provisional_subvertical_ids": routes,
            "discovery_method": discovery_method,
        }
        receipt_sha256 = _digest(receipt_basis)
        targeted_receipts.append({**receipt_basis, "receipt_sha256": receipt_sha256, "quota_credit": 0})
        existing = leads_by_url.get(url)
        if existing is None:
            existing = {
                "lead_id": "gold-lead-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
                "source_url": url,
                "source_family_ids": [],
                "source_directory_urls": [],
                "source_snapshot_sha256s": [],
                "source_targeted_discovery_sha256s": [],
                "company": company,
                "title": title,
                "directory_industry": str(raw_lead.get("directory_industry") or ""),
                "directory_company_size": "",
                "directory_products": "",
                "directory_use_cases": "",
                "directory_sort_tags": "",
                "source_excerpt": str(raw_lead.get("source_excerpt") or ""),
                "source_published_label": str(raw_lead.get("source_published_label") or ""),
                "provisional_subvertical_ids": [],
                "routing_reasons": [],
                "status": "discovery_lead_only",
                "company_scale_status": "unresolved",
                "episode_identity_status": "unresolved",
                "budget_status": "unresolved",
                "market_status": "unresolved",
                "observed_period_status": "unresolved",
                "outcome_verification_status": "unresolved",
                "independent_corroboration_status": "unresolved",
                "automatic_promotion_allowed": False,
                "quota_credit": 0,
            }
            leads_by_url[url] = existing
        existing.setdefault("source_targeted_discovery_sha256s", [])
        existing["source_family_ids"] = sorted(set(existing["source_family_ids"]) | {source_family_id})
        existing["source_targeted_discovery_sha256s"] = sorted(
            set(existing["source_targeted_discovery_sha256s"]) | {receipt_sha256}
        )
        existing["provisional_subvertical_ids"] = sorted(
            set(existing["provisional_subvertical_ids"]) | set(routes)
        )
        existing["routing_reasons"] = sorted(
            set(existing["routing_reasons"]) | {"operator-reviewed direct public case-page route; final classification unresolved"}
        )

    leads = sorted(leads_by_url.values(), key=lambda row: row["source_url"])
    query_matrix = build_query_matrix()
    routing_counts = {
        subvertical_id: sum(subvertical_id in row["provisional_subvertical_ids"] for row in leads)
        for subvertical_id in GOLD_SUBVERTICALS
    }
    source_class_counts = Counter(row["directory_industry"] or "unclassified" for row in leads)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "research_cutoff": research_cutoff,
        "gold_subvertical_ids": list(GOLD_SUBVERTICALS),
        "source_families": [dict(row) for row in SOURCE_FAMILIES],
        "source_family_count": len(SOURCE_FAMILIES),
        "query_matrix_count": len(query_matrix),
        "query_matrix": query_matrix,
        "snapshot_count": len(snapshot_receipts),
        "snapshot_receipts": snapshot_receipts,
        "targeted_lead_count": len(targeted_receipts),
        "targeted_lead_receipts": sorted(targeted_receipts, key=lambda row: row["source_url"]),
        "unique_discovery_lead_count": len(leads),
        "provisionally_routed_lead_count": sum(bool(row["provisional_subvertical_ids"]) for row in leads),
        "unrouted_lead_count": sum(not row["provisional_subvertical_ids"] for row in leads),
        "routing_counts": routing_counts,
        "directory_industry_counts": dict(sorted(source_class_counts.items())),
        "records": leads,
        "promotion_policy": {
            "directory_membership_grants_candidate_credit": False,
            "title_or_keyword_routing_is_final_classification": False,
            "unknown_budget_may_be_inferred": False,
            "vendor_case_alone_proves_outcome_or_causality": False,
            "entity_resolution_cross_platform_dedup_and_human_case_review_required": True,
        },
        "truth_boundary": (
            "This artifact proves public directory discovery and conservative provisional routing only. Every lead has zero "
            "candidate quota credit until episode identity, budget, market, period, outcome, independent corroboration, and "
            "cross-platform deduplication are resolved under CaseCandidateV2."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def extend_gold_case_discovery(
    existing_payload: Mapping[str, Any],
    targeted_leads: Sequence[Mapping[str, Any]],
    *,
    research_cutoff: str | None = None,
) -> dict[str, Any]:
    """Append zero-credit public search leads without discarding sealed directory lineage."""

    verify_gold_case_discovery(existing_payload)
    payload = copy.deepcopy(dict(existing_payload))
    payload.pop("content_sha256", None)
    source_family_ids = {row["source_family_id"] for row in payload["source_families"]}
    records_by_url = {row["source_url"]: row for row in payload["records"]}
    receipts = list(payload["targeted_lead_receipts"])
    receipt_ids = {row["receipt_sha256"] for row in receipts}

    for raw_lead in targeted_leads:
        source_family_id = str(raw_lead.get("source_family_id") or "")
        if source_family_id not in source_family_ids:
            raise GTMGoldCaseDiscoveryError("targeted lead has an unsupported source family")
        discovery_method = str(raw_lead.get("discovery_method") or "model_assisted_public_search_result")
        if discovery_method not in TARGETED_DISCOVERY_METHODS:
            raise GTMGoldCaseDiscoveryError("targeted lead discovery method is invalid")
        url = _canonical_url(str(raw_lead.get("source_url") or ""))
        routes = sorted(set(str(value) for value in raw_lead.get("provisional_subvertical_ids", ())))
        if not routes or not set(routes).issubset(GOLD_SUBVERTICALS):
            raise GTMGoldCaseDiscoveryError("targeted lead routes must be non-empty gold subvertical IDs")
        company = str(raw_lead.get("company") or "").strip()
        title = str(raw_lead.get("title") or "").strip()
        if not company or not title:
            raise GTMGoldCaseDiscoveryError("targeted lead requires company and title")
        receipt_basis = {
            "source_url": url,
            "source_family_id": source_family_id,
            "company": company,
            "title": title,
            "provisional_subvertical_ids": routes,
            "discovery_method": discovery_method,
        }
        receipt_sha256 = _digest(receipt_basis)
        if receipt_sha256 not in receipt_ids:
            receipts.append({**receipt_basis, "receipt_sha256": receipt_sha256, "quota_credit": 0})
            receipt_ids.add(receipt_sha256)

        record = records_by_url.get(url)
        if record is None:
            record = {
                "lead_id": "gold-lead-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
                "source_url": url,
                "source_family_ids": [],
                "source_directory_urls": [],
                "source_snapshot_sha256s": [],
                "source_targeted_discovery_sha256s": [],
                "company": company,
                "title": title,
                "directory_industry": str(raw_lead.get("directory_industry") or ""),
                "directory_company_size": "",
                "directory_products": "",
                "directory_use_cases": "",
                "directory_sort_tags": "",
                "source_excerpt": str(raw_lead.get("source_excerpt") or ""),
                "source_published_label": str(raw_lead.get("source_published_label") or ""),
                "provisional_subvertical_ids": [],
                "routing_reasons": [],
                "status": "discovery_lead_only",
                "company_scale_status": "unresolved",
                "episode_identity_status": "unresolved",
                "budget_status": "unresolved",
                "market_status": "unresolved",
                "observed_period_status": "unresolved",
                "outcome_verification_status": "unresolved",
                "independent_corroboration_status": "unresolved",
                "automatic_promotion_allowed": False,
                "quota_credit": 0,
            }
            records_by_url[url] = record
        record.setdefault("source_targeted_discovery_sha256s", [])
        record["source_family_ids"] = sorted(set(record["source_family_ids"]) | {source_family_id})
        record["source_targeted_discovery_sha256s"] = sorted(
            set(record["source_targeted_discovery_sha256s"]) | {receipt_sha256}
        )
        record["provisional_subvertical_ids"] = sorted(
            set(record["provisional_subvertical_ids"]) | set(routes)
        )
        reason = (
            "model-assisted direct public case-page lead; named human classification unresolved"
            if discovery_method == "model_assisted_public_search_result"
            else "operator-reviewed direct public case-page route; final classification unresolved"
        )
        record["routing_reasons"] = sorted(set(record["routing_reasons"]) | {reason})

    records = sorted(records_by_url.values(), key=lambda row: row["source_url"])
    payload["research_cutoff"] = research_cutoff or payload["research_cutoff"]
    payload["targeted_lead_receipts"] = sorted(receipts, key=lambda row: (row["source_url"], row["receipt_sha256"]))
    payload["targeted_lead_count"] = len(receipts)
    payload["unique_discovery_lead_count"] = len(records)
    payload["provisionally_routed_lead_count"] = sum(bool(row["provisional_subvertical_ids"]) for row in records)
    payload["unrouted_lead_count"] = sum(not row["provisional_subvertical_ids"] for row in records)
    payload["routing_counts"] = {
        subvertical_id: sum(subvertical_id in row["provisional_subvertical_ids"] for row in records)
        for subvertical_id in GOLD_SUBVERTICALS
    }
    payload["directory_industry_counts"] = dict(sorted(Counter(
        row["directory_industry"] or "unclassified" for row in records
    ).items()))
    payload["records"] = records
    payload["content_sha256"] = _digest(payload)
    verify_gold_case_discovery(payload)
    return payload


def verify_gold_case_discovery(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMGoldCaseDiscoveryError("gold case discovery seal is invalid")
    if tuple(payload.get("gold_subvertical_ids", ())) != GOLD_SUBVERTICALS:
        raise GTMGoldCaseDiscoveryError("gold subvertical set drifted")
    source_families = payload.get("source_families")
    if not isinstance(source_families, list) or payload.get("source_family_count") != len(source_families):
        raise GTMGoldCaseDiscoveryError("source family aggregate drifted")
    if len({row.get("source_family_id") for row in source_families}) != len(source_families):
        raise GTMGoldCaseDiscoveryError("source family IDs are duplicated")
    if payload.get("query_matrix_count") != len(GOLD_SUBVERTICALS) * len(MARKETS) * len(OUTCOME_INTENTS) * len(QUERY_MODES):
        raise GTMGoldCaseDiscoveryError("query matrix cardinality drifted")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("unique_discovery_lead_count") != len(records):
        raise GTMGoldCaseDiscoveryError("discovery lead aggregate drifted")
    urls = [row.get("source_url") for row in records]
    if len(urls) != len(set(urls)):
        raise GTMGoldCaseDiscoveryError("cross-snapshot URL duplicates were not collapsed")
    if any(
        row.get("quota_credit") != 0
        or row.get("automatic_promotion_allowed") is not False
        or not set(row.get("provisional_subvertical_ids", ())).issubset(GOLD_SUBVERTICALS)
        for row in records
    ):
        raise GTMGoldCaseDiscoveryError("a lead escaped the provisional zero-credit boundary")
    expected_routed = sum(bool(row.get("provisional_subvertical_ids")) for row in records)
    if payload.get("provisionally_routed_lead_count") != expected_routed:
        raise GTMGoldCaseDiscoveryError("routed lead aggregate drifted")
    if payload.get("unrouted_lead_count") != len(records) - expected_routed:
        raise GTMGoldCaseDiscoveryError("unrouted lead aggregate drifted")
    expected_routing = {
        subvertical_id: sum(subvertical_id in row.get("provisional_subvertical_ids", ()) for row in records)
        for subvertical_id in GOLD_SUBVERTICALS
    }
    if payload.get("routing_counts") != expected_routing:
        raise GTMGoldCaseDiscoveryError("subvertical routing aggregate drifted")
    expected_industries = dict(sorted(Counter(
        row.get("directory_industry") or "unclassified" for row in records
    ).items()))
    if payload.get("directory_industry_counts") != expected_industries:
        raise GTMGoldCaseDiscoveryError("directory industry aggregate drifted")
    if payload.get("snapshot_count") != len(payload.get("snapshot_receipts", [])):
        raise GTMGoldCaseDiscoveryError("snapshot receipt aggregate drifted")
    if any(
        receipt.get("raw_page_retained_in_artifact") is not False
        or receipt.get("authentication_used") is not False
        or receipt.get("captcha_bypass_used") is not False
        or receipt.get("paywall_bypass_used") is not False
        or receipt.get("quota_credit") != 0
        for receipt in payload.get("snapshot_receipts", [])
    ):
        raise GTMGoldCaseDiscoveryError("a source snapshot escaped the access or retention boundary")
    targeted_receipts = payload.get("targeted_lead_receipts")
    if not isinstance(targeted_receipts, list) or payload.get("targeted_lead_count") != len(targeted_receipts):
        raise GTMGoldCaseDiscoveryError("targeted lead receipt aggregate drifted")
    if any(
        row.get("quota_credit") != 0
        or row.get("discovery_method") not in TARGETED_DISCOVERY_METHODS
        or not set(row.get("provisional_subvertical_ids", ())).issubset(GOLD_SUBVERTICALS)
        or row.get("receipt_sha256") != _digest({key: value for key, value in row.items() if key not in {"receipt_sha256", "quota_credit"}})
        for row in targeted_receipts
    ):
        raise GTMGoldCaseDiscoveryError("a targeted lead receipt escaped the zero-credit discovery boundary")


__all__ = [
    "GOLD_SUBVERTICALS",
    "GTMGoldCaseDiscoveryError",
    "build_query_matrix",
    "compile_gold_case_discovery",
    "extract_athena_manufacturing_case_cards",
    "extract_hubspot_directory_cards",
    "extract_industrial_case_directory_cards",
    "extract_tiktok_directory_cards",
    "extend_gold_case_discovery",
    "verify_gold_case_discovery",
]
