#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_claim_surface_v2 import extract_claim_surfaces
from prooflaunch_remix.gtm_public_source_capture import RobotsPermissionCache, default_fetch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/gtm-flodesk-admission-dossier-v2.json"
SOURCES = (
    ("founder_interview", "https://www.indiehackers.com/post/tech/growing-a-fully-bootstrapped-email-marketing-platform-to-37m-arr-yEzvbRhw1NFn0lHedTWu", False),
    ("company_information", "https://flodesk.com/ai-information", False),
    ("company_milestone", "https://flodesk.com/blog/a-milestone-year-made-together/", False),
    ("independent_cloud_profile", "https://aws.amazon.com/blogs/startups/how-flodesk-is-designing-a-new-narrative-for-startups/", True),
    ("official_pricing", "https://flodesk.com/pricing", False),
    ("independent_founder_podcast", "https://practicalfounders.com/podcast/amazing-story-0-30m-arr-no-outside-funding-rebecca-shostak/", True),
    ("official_legal_identity", "https://flodesk.com/legal/privacy-policy", False),
)
TARGET_MARKERS = {
    "founder_interview": ("$36 million", "$90K", "four months", "$1 million", "Organic growth", "bootstrapped"),
    "company_information": ("100,000+", "$36M", "without a dollar of outside funding", "$33M", "Profitable since its second week"),
    "company_milestone": ("$36 million in ARR", "$33 million in revenue", "13+ billion emails", "314 million subscribers"),
    "independent_cloud_profile": ("70,000 customers", "$20 million", "35 team members", "bootstrap mindset"),
    "official_pricing": ("$19/month", "$25/month", "$49/month", "no hidden fees", "unlimited email sends"),
    "independent_founder_podcast": ("$30m ARR", "no outside funding", "viral explosion"),
    "official_legal_identity": ("Flodesk, Inc.",),
}


def _fetch_with_bounded_retry(url: str, attempts: int = 3):
    """Retry transient public-page transport failures without changing access policy."""
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return default_fetch(url, timeout=30.0)
        except Exception as error:
            last_error = error
    assert last_error is not None
    raise last_error


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "svg", "noscript"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self.suppressed:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def _windows(body: str, markers: tuple[str, ...]) -> list[dict[str, str]]:
    parser = _VisibleText()
    parser.feed(body)
    text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
    lower = text.casefold()
    rows = []
    for marker in markers:
        index = lower.find(marker.casefold())
        if index < 0:
            continue
        excerpt = text[max(0, index - 80):min(len(text), index + len(marker) + 150)].strip()
        rows.append({"marker": marker, "bounded_exact_excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    robots = RobotsPermissionCache()
    records = []
    for role, url, independent in SOURCES:
        robots_status, allowed = robots.check(url)
        if not allowed:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "blocked_by_robots", "robots_status": robots_status})
            continue
        try:
            response = _fetch_with_bounded_retry(url)
            body = response.body.decode("utf-8", errors="replace")
            surfaces = extract_claim_surfaces(body)
            records.append({
                "source_role": role,
                "source_url": url,
                "independent": independent,
                "capture_status": "captured_and_bounded",
                "robots_status": robots_status,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_content_sha256": hashlib.sha256(body.encode()).hexdigest(),
                "page_title": surfaces["page_title"],
                "page_description": surfaces["page_description"],
                "fragment_counts": surfaces["fragment_counts"],
                "fragments": surfaces["fragments"],
                "targeted_claim_windows": _windows(body, TARGET_MARKERS.get(role, ())),
                "raw_page_retained": False,
            })
        except Exception as error:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "capture_failed", "robots_status": robots_status, "error_type": type(error).__name__, "error_summary": str(error)[:240]})
    captured = [row for row in records if row["capture_status"] == "captured_and_bounded"]
    by_role = {row["source_role"]: row for row in captured}
    independent = [row for row in captured if row["independent"]]
    founder_hash = by_role.get("founder_interview", {}).get("source_content_sha256", "")
    company_hash = by_role.get("company_information", {}).get("source_content_sha256", "")
    milestone_hash = by_role.get("company_milestone", {}).get("source_content_sha256", "")
    cost_components = {
        "paid_media": {"status": "unknown_amount_organic_growth_reported", "amount_usd": None, "source_content_sha256": founder_hash},
        "personnel": {"status": "unknown_amount_team_scope_disclosed", "amount_usd": None, "source_content_sha256": by_role.get("independent_cloud_profile", {}).get("source_content_sha256", "")},
        "tools": {"status": "unknown_amount_product_infrastructure_scope", "amount_usd": None, "source_content_sha256": milestone_hash},
        "creators": {"status": "unknown_amount_founder_design_scope", "amount_usd": None, "source_content_sha256": founder_hash},
        "channel_fees": {"status": "unknown_amount_global_distribution_scope", "amount_usd": None, "source_content_sha256": by_role.get("official_pricing", {}).get("source_content_sha256", company_hash)},
        "production": {"status": "unknown_amount_design_engineering_scope", "amount_usd": None, "source_content_sha256": milestone_hash},
    }
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches = [row for row in ledger["records"] if row.get("company") == "Flodesk"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(matches),
        "company_match_review_packet_ids": [row["review_packet_id"] for row in matches],
        "exact_content_mirror_detected": len(hashes) != len(set(hashes)),
        "additional_case_episode_collision_detected": len(matches) > 1,
    }
    resource_bound = any(row["marker"] == "$90K" for row in by_role.get("founder_interview", {}).get("targeted_claim_windows", []))
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_recent_episode",
        "market_scale_and_lifecycle": "evidence_ready",
        "source_bound_budget_tier": "evidence_ready_capital_efficient_90k_founder_savings" if resource_bound else "blocked",
        "six_cost_components": "evidence_ready_all_recorded_amounts_unknown",
        "result_claim_binding": "evidence_ready" if by_role.get("founder_interview", {}).get("targeted_claim_windows") else "blocked",
        "independent_outcome_surface": "evidence_ready" if len(independent) >= 2 else "blocked",
        "entity_and_episode_resolution": "evidence_ready" if {"official_legal_identity", "company_information"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMFlodeskAdmissionDossierV2",
        "company": "Flodesk",
        "legal_entity_hint": "Flodesk, Inc.",
        "entity_key": "entity-" + hashlib.sha256(b"company|flodesk inc").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"flodesk inc|flodesk|bootstrapped design-led growth|multi-market|2019-01-01|2026-04-22").hexdigest()[:20],
        "provisional_subvertical_id": "b2b.martech_sales_tech.marketing_automation",
        "episode_definition": "2019-2026 bootstrapped design-led growth from launch to more than $36M ARR; initial total resource pool is bounded by founder-reported savings, while component amounts remain unknown and organic growth is descriptive rather than causal proof.",
        "source_count": len(records),
        "captured_source_count": len(captured),
        "independent_captured_source_count": len(independent),
        "cost_components": cost_components,
        "duplicate_screen": duplicate_screen,
        "gate_count": len(gates),
        "evidence_ready_gate_count": ready,
        "blocking_gate_count": len(gates) - ready,
        "gates": gates,
        "sources": records,
        "observed_named_human_review_count": 0,
        "formal_candidate_quota_credit": 0,
        "automatic_promotion_allowed": False,
        "truth_boundary": "The $90K founder savings figure bounds the initial resource pool but does not prove zero paid media or disclose component amounts. Every cost amount remains unknown. Independent sources corroborate scale; no source proves that design or organic growth alone caused the outcome.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
