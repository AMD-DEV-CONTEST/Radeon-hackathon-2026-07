from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_gold_case_discovery_v2 import verify_gold_case_discovery


SCHEMA = "ProofLaunchGTMCaseClaimSurfaceV2"
FRAGMENT_LIMIT_PER_CATEGORY = 2
FRAGMENT_CHARACTER_LIMIT = 120
CATEGORIES = ("outcome", "time_window", "cost_resource", "mechanism")


class GTMCaseClaimSurfaceError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


class _BlockParser(HTMLParser):
    BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "td", "dt", "dd"}
    SUPPRESSED_TAGS = {"script", "style", "svg", "noscript", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.blocks: list[dict[str, Any]] = []
        self._suppressed = 0
        self._tag = ""
        self._parts: list[str] = []
        self._block_index = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        lowered = tag.casefold()
        if lowered in self.SUPPRESSED_TAGS:
            self._suppressed += 1
            return
        if self._suppressed:
            return
        if lowered == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").casefold()
            if key in {"og:title", "twitter:title"} and not self.title:
                self.title = attributes.get("content", "").strip()
            if key in {"description", "og:description"} and not self.description:
                self.description = attributes.get("content", "").strip()
        if lowered in self.BLOCK_TAGS and not self._tag:
            self._tag = lowered
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in self.SUPPRESSED_TAGS:
            if self._suppressed:
                self._suppressed -= 1
            return
        if self._suppressed:
            return
        if self._tag and lowered == self._tag:
            text = re.sub(r"\s+", " ", " ".join(self._parts)).strip()
            if 12 <= len(text) <= 1_500:
                self.blocks.append({"block_index": self._block_index, "tag": self._tag, "text": text})
                self._block_index += 1
            self._tag = ""
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._suppressed or not self._tag:
            return
        text = " ".join(data.split())
        if text:
            self._parts.append(text)


PATTERNS: Mapping[str, tuple[re.Pattern[str], ...]] = {
    "outcome": (
        re.compile(r"(?:\d[\d,.]*\s?%|\$\s?\d|\b\d+(?:\.\d+)?x\b)", re.I),
        re.compile(r"\b(?:revenue|sales|pipeline|leads?|customers?|bookings?|traffic|conversion|roi|retention|orders?|profit)\b", re.I),
    ),
    "time_window": (
        re.compile(r"\b(?:20\d{2}|\d+\s+(?:days?|weeks?|months?|years?)|within\s+\d+|since\s+20\d{2})\b", re.I),
    ),
    "cost_resource": (
        re.compile(r"\b(?:budget|ad spend|paid ads?|media spend|costs?|team of|employees?|agency|creator|production|headcount|no paid)\b", re.I),
    ),
    "mechanism": (
        re.compile(r"\b(?:strategy|campaign|launched|implemented|integrated|automated|content|email|social|sales process|marketing|workflow|crm|approach)\b", re.I),
    ),
}


def _categorize(text: str) -> list[str]:
    categories = []
    for category, patterns in PATTERNS.items():
        if all(pattern.search(text) for pattern in patterns):
            categories.append(category)
    return categories


def extract_claim_surfaces(html_text: str) -> dict[str, Any]:
    parser = _BlockParser()
    parser.feed(html_text)
    fragments: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORIES}
    seen_text: set[str] = set()
    for block in parser.blocks:
        normalized = re.sub(r"\s+", " ", block["text"]).strip()
        signature = normalized.casefold()
        if signature in seen_text:
            continue
        categories = _categorize(normalized)
        if not categories:
            continue
        seen_text.add(signature)
        excerpt = normalized[:FRAGMENT_CHARACTER_LIMIT]
        row = {
            "locator": f"{block['tag']}:{block['block_index']}",
            "bounded_exact_excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "full_block_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        }
        for category in categories:
            if len(fragments[category]) < FRAGMENT_LIMIT_PER_CATEGORY:
                fragments[category].append(dict(row))
    return {
        "page_title": parser.title[:300],
        "page_description": parser.description[:500],
        "parsed_block_count": len(parser.blocks),
        "fragments": fragments,
        "fragment_counts": {category: len(fragments[category]) for category in CATEGORIES},
        "bounded_excerpt_word_count": sum(
            len(row["bounded_exact_excerpt"].split())
            for rows in fragments.values()
            for row in rows
        ),
    }


def compile_case_claim_surfaces(
    discovery: Mapping[str, Any],
    captures: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    verify_gold_case_discovery(discovery)
    leads = {row["source_url"]: row for row in discovery["records"]}
    records: list[dict[str, Any]] = []
    for capture in captures:
        source_url = str(capture.get("source_url") or "")
        lead = leads.get(source_url)
        if lead is None:
            raise GTMCaseClaimSurfaceError("claim surface capture is not bound to a discovered lead")
        html_text = str(capture.get("html_text") or "")
        content_sha256 = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
        if content_sha256 != capture.get("content_sha256"):
            raise GTMCaseClaimSurfaceError("claim surface input hash mismatch")
        extracted = extract_claim_surfaces(html_text)
        counts = extracted["fragment_counts"]
        missing = [category for category in CATEGORIES if counts[category] == 0]
        records.append({
            "lead_id": lead["lead_id"],
            "source_url": source_url,
            "source_content_sha256": content_sha256,
            "captured_at": str(capture.get("captured_at") or ""),
            "provisional_subvertical_ids": lead["provisional_subvertical_ids"],
            **extracted,
            "surface_completeness": "four_surface_signal" if not missing else "claim_surface_gap",
            "missing_surface_categories": missing,
            "human_claim_binding_required": True,
            "independent_corroboration_required": True,
            "candidate_promotion_allowed": False,
            "quota_credit": 0,
        })
    completeness = Counter(row["surface_completeness"] for row in records)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source_discovery_sha256": discovery["content_sha256"],
        "record_count": len(records),
        "capture_attempt_count": len(records) + len(failures),
        "capture_failure_count": len(failures),
        "capture_failures": [dict(row) for row in failures],
        "status_counts": dict(sorted(completeness.items())),
        "four_surface_signal_count": completeness.get("four_surface_signal", 0),
        "records": sorted(records, key=lambda row: row["source_url"]),
        "promotion_policy": {
            "keyword_surface_detection_is_claim_verification": False,
            "four_surface_signal_grants_candidate_credit": False,
            "human_exact_claim_binding_required": True,
            "two_independent_outcome_surfaces_required_for_outcome_promotion": True,
        },
        "truth_boundary": (
            "Short, bounded source fragments accelerate review but do not verify meaning, time scope, budget completeness, "
            "outcomes, or causality. Raw HTML is processed in memory and excluded from this artifact."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_case_claim_surfaces(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMCaseClaimSurfaceError("case claim surface seal is invalid")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("record_count") != len(records):
        raise GTMCaseClaimSurfaceError("case claim surface count drifted")
    if len({row.get("source_url") for row in records}) != len(records):
        raise GTMCaseClaimSurfaceError("case claim surface URLs are duplicated")
    failures = payload.get("capture_failures")
    if not isinstance(failures, list) or payload.get("capture_attempt_count") != len(records) + len(failures):
        raise GTMCaseClaimSurfaceError("claim-surface capture attempt aggregate drifted")
    if payload.get("capture_failure_count") != len(failures) or any(row.get("quota_credit") != 0 for row in failures):
        raise GTMCaseClaimSurfaceError("claim-surface capture failures escaped zero-credit accounting")
    if any(
        row.get("quota_credit") != 0
        or row.get("candidate_promotion_allowed") is not False
        or row.get("bounded_excerpt_word_count", 0) > 200
        for row in records
    ):
        raise GTMCaseClaimSurfaceError("case claim surface escaped bounded zero-credit review")
    observed = sum(row.get("surface_completeness") == "four_surface_signal" for row in records)
    if payload.get("four_surface_signal_count") != observed:
        raise GTMCaseClaimSurfaceError("four-surface aggregate drifted")


__all__ = [
    "GTMCaseClaimSurfaceError",
    "compile_case_claim_surfaces",
    "extract_claim_surfaces",
    "verify_case_claim_surfaces",
]
