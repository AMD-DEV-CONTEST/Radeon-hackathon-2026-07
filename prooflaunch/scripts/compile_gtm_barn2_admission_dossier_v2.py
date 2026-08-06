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
OUTPUT = ROOT / "evidence/v10/gtm-barn2-admission-dossier-v2.json"
SOURCES = (
    ("founder_interview_2026", "https://www.indiehackers.com/post/tech/diversifying-to-break-a-1-6m-yr-plateau-D8QDyPuDzSuOQS7ux9nR", False),
    ("official_transparency_2024", "https://barn2.com/blog/2024-year-in-review/", False),
    ("official_transparency_2021", "https://barn2.com/blog/2021-year-in-review/", False),
    ("official_about", "https://barn2.com/about/", False),
    ("independent_product_interview", "https://plugmatter.com/article/from-web-design-shop-to-wordpress-plugin-empire-katie-keiths-barn2-plugins-journey", True),
    ("independent_founder_profile", "https://www.kimp.io/katie-keith-barn2-plugins/", True),
    ("independent_revenue_profile", "https://www.starterstory.com/katie", True),
)
TARGET_MARKERS = {
    "founder_interview_2026": ("$1.6M/year", "$133K a month", "$10 million", "plateau", "SEO", "video", "Claude Code"),
    "official_transparency_2024": ("19.5 people", "Revenue increased by 12%", "profitability by 11%", "CMO-As-a-Service", "freelance writers", "Video Creator", "24,652 support tickets"),
    "official_transparency_2021": ("$21,155 paid", "486 affiliates", "22,000+ paying customers", "119 knowledge base articles", "77 blog posts", "monthly revenue is regularly achieving 6-figures"),
    "official_about": ("90000+", "700+", "200+", "100% owned", "five continents"),
    "independent_product_interview": ("marketing content", "outreach", "planning blog posts", "existing customers"),
    "independent_founder_profile": ("team of 17", "cross-promoting", "full-time"),
    "independent_revenue_profile": ("$150K/Month", "20 Apps", "$1M/year"),
}


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
        excerpt = text[max(0, index - 100):min(len(text), index + len(marker) + 220)].strip()
        rows.append({"marker": marker, "bounded_exact_excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest()})
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fetch(url: str):
    last: Exception | None = None
    for _ in range(3):
        try:
            return default_fetch(url, timeout=30.0)
        except Exception as error:
            last = error
    assert last is not None
    raise last


def main() -> int:
    robots = RobotsPermissionCache()
    records = []
    for role, url, independent in SOURCES:
        robots_status, allowed = robots.check(url)
        if not allowed:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "blocked_by_robots", "robots_status": robots_status})
            continue
        try:
            response = _fetch(url)
            body = response.body.decode("utf-8", errors="replace")
            surfaces = extract_claim_surfaces(body)
            records.append({
                "source_role": role, "source_url": url, "independent": independent,
                "capture_status": "captured_and_bounded", "robots_status": robots_status,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_content_sha256": hashlib.sha256(response.body).hexdigest(),
                "page_title": surfaces["page_title"], "page_description": surfaces["page_description"],
                "fragment_counts": surfaces["fragment_counts"], "fragments": surfaces["fragments"],
                "targeted_claim_windows": _windows(body, TARGET_MARKERS.get(role, ())), "raw_page_retained": False,
            })
        except Exception as error:
            records.append({"source_role": role, "source_url": url, "independent": independent, "capture_status": "capture_failed", "robots_status": robots_status, "error_type": type(error).__name__, "error_summary": str(error)[:240]})

    captured = [row for row in records if row["capture_status"] == "captured_and_bounded"]
    by_role = {row["source_role"]: row for row in captured}
    independent = [row for row in captured if row["independent"]]
    primary_hash = by_role.get("founder_interview_2026", {}).get("source_content_sha256", "")
    report_2024_hash = by_role.get("official_transparency_2024", {}).get("source_content_sha256", "")
    report_2021_hash = by_role.get("official_transparency_2021", {}).get("source_content_sha256", "")
    cost_components = {
        "paid_media": {"status": "unknown_no_complete_paid_media_ledger", "amount_usd": None, "source_content_sha256": primary_hash},
        "personnel": {"status": "unknown_19_5_people_agency_and_freelancers_disclosed", "amount_usd": None, "source_content_sha256": report_2024_hash},
        "tools": {"status": "unknown_software_and_ai_stack_disclosed_without_total", "amount_usd": None, "source_content_sha256": primary_hash},
        "creators": {"status": "unknown_video_creator_designer_and_writers_disclosed", "amount_usd": None, "source_content_sha256": report_2024_hash},
        "channel_fees": {"status": "bounded_2021_affiliate_payout", "amount_usd": 21155, "source_content_sha256": report_2021_hash},
        "production": {"status": "unknown_high_volume_docs_blog_video_and_product_production", "amount_usd": None, "source_content_sha256": report_2021_hash or report_2024_hash},
    }
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches = [row for row in ledger["records"] if row.get("company") == "Barn2"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(matches), "company_match_review_packet_ids": [row["review_packet_id"] for row in matches],
        "exact_content_mirror_detected": len(hashes) != len(set(hashes)), "additional_case_episode_collision_detected": len(matches) > 1,
    }
    primary_markers = {row["marker"] for row in by_role.get("founder_interview_2026", {}).get("targeted_claim_windows", [])}
    report_2024_markers = {row["marker"] for row in by_role.get("official_transparency_2024", {}).get("targeted_claim_windows", [])}
    report_2021_markers = {row["marker"] for row in by_role.get("official_transparency_2021", {}).get("targeted_claim_windows", [])}
    outcome_bound = "$1.6M/year" in primary_markers and "plateau" in primary_markers
    resource_bound = "19.5 people" in report_2024_markers and "$21,155 paid" in report_2021_markers
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_current_within_six_months",
        "market_scale_and_lifecycle": "evidence_ready_small_global_mature",
        "source_bound_budget_tier": "evidence_ready_capital_efficient_from_team_agency_creator_and_affiliate_inputs" if resource_bound else "blocked",
        "six_cost_components": "evidence_ready_all_six_recorded_without_free_labor_or_zero_paid_inference",
        "result_claim_binding": "evidence_ready_founder_stated_plateau_not_audited" if outcome_bound else "blocked",
        "independent_outcome_surface": "evidence_ready_three_independent_company_revenue_and_team_surfaces_not_audit" if len(independent) >= 3 else "blocked",
        "entity_and_episode_resolution": "evidence_ready_founder_company_product_and_timeline" if {"founder_interview_2026", "official_transparency_2024", "official_about"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMBarn2AdmissionDossierV2", "company": "Barn2", "legal_entity_hint": "Barn2 Media Ltd",
        "founder_identity": "Katie Keith", "entity_key": "entity-" + hashlib.sha256(b"barn2 media ltd|barn2|katie keith").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"barn2|global seo video diversification plateau|2016-01-01|2026-06-09").hexdigest()[:20],
        "provisional_subvertical_id": "b2b.developer_tools.application_development",
        "episode_definition": "2016 to June 2026 global product-portfolio growth through SEO, video, documentation, affiliates and cross-sell, ending in a disclosed roughly USD 1.6M annual-revenue plateau and diversification response.",
        "source_count": len(records), "captured_source_count": len(captured), "independent_captured_source_count": len(independent),
        "cost_components": cost_components, "duplicate_screen": duplicate_screen, "gate_count": len(gates),
        "evidence_ready_gate_count": ready, "blocking_gate_count": len(gates) - ready, "gates": gates, "sources": records,
        "observed_named_human_review_count": 0, "formal_candidate_quota_credit": 0, "automatic_promotion_allowed": False,
        "truth_boundary": "The approximately USD 1.6M annual revenue and plateau are founder-stated and unaudited. The capital-efficient classification is source-bound to a 19.5-person team, external CMO/content support, dedicated video/design roles and a disclosed USD 21,155 historical affiliate payout; complete media, people, tool, creator and production totals remain unknown. This is a failed-or-stalled learning episode, not proof that diversification will work.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
