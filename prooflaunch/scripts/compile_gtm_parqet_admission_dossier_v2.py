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
OUTPUT = ROOT / "evidence/v10/gtm-parqet-admission-dossier-v2.json"
SOURCES = (
    ("founder_interview_2024", "https://www.indiehackers.com/post/bootstrapping-a-fintech-product-to-108k-mrr-by-limiting-it-to-a-small-market-sQoTemyW9t7ZAOurFhZk", False),
    ("founder_ama_2021", "https://www.indiehackers.com/post/i-bootstrapped-a-side-project-to-15k-mrr-in-1-year-in-1-market-ama-d01e2e5628", False),
    ("independent_source_accountability", "https://startupfounderstories.com/stories/sumit-kumar-parqet-15k-mrr", True),
    ("independent_media_syndication", "https://de.finance.yahoo.com/nachrichten/hamburger-schmei%C3%9Ft-300-000-euro-060000327.html", True),
    ("independent_founder_podcast", "https://saas.group/podcasts/saas-unbound-interview-sumit-kumar-parqet/", True),
    ("official_pricing", "https://parqet.com/en/pricing", False),
    ("official_legal_identity", "https://parqet.com/de/legal", False),
)
TARGET_MARKERS = {
    "founder_interview_2024": ("$108k MRR", "close to €100k", "$100/per month", "first five months", "employee #5", "€20k MRR", "first two years", "paid ads", "revenue cut", "no following"),
    "founder_ama_2021": ("haven't spent a single ad-dollar", "17k+ MRR", "100k registered users", "about 10 people", "7am to 9am", "8pm to midnight", "grew it with its revenue"),
    "independent_source_accountability": ("$108K MRR", "Not independently audited", "$100", "Word of Mouth", "bootstrapped and profitable"),
    "independent_media_syndication": ("38.000 Euro", "drei Millionen Pageviews", "100.000 Kunden", "zehn Leute", "300.000 Euro"),
    "independent_founder_podcast": ("bootstrapped from day 1", "influencer ecosystem", "organic growth", "paid advertising", "hyper-niching"),
    "official_pricing": ("0€ / month", "11,99€ / month", "29,99€ / month", "40+ Currencies", "native apps for iOS and Android"),
    "official_legal_identity": ("Parqet Fintech GmbH", "HRB 164995", "Sumit Kumar", "Affiliate-Provision"),
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
        excerpt = text[max(0, index - 90):min(len(text), index + len(marker) + 190)].strip()
        rows.append({
            "marker": marker,
            "bounded_exact_excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        })
    return rows


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _fetch_with_bounded_retry(url: str, attempts: int = 3):
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return default_fetch(url, timeout=30.0)
        except Exception as error:
            last_error = error
    assert last_error is not None
    raise last_error


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
    primary_hash = by_role.get("founder_interview_2024", {}).get("source_content_sha256", "")
    ama_hash = by_role.get("founder_ama_2021", {}).get("source_content_sha256", "")
    legal_hash = by_role.get("official_legal_identity", {}).get("source_content_sha256", "")
    cost_components = {
        "paid_media": {"status": "unknown_complete_episode_later_paid_ads_disclosed", "amount_usd": None, "source_content_sha256": primary_hash},
        "personnel": {"status": "unknown_founder_intensive_labor_and_team_disclosed", "amount_usd": None, "source_content_sha256": primary_hash},
        "tools": {"status": "bounded_first_five_months_operating_spend", "amount_usd": 500, "source_content_sha256": primary_hash},
        "creators": {"status": "unknown_influencer_revenue_share_and_internal_content_labor", "amount_usd": None, "source_content_sha256": primary_hash},
        "channel_fees": {"status": "unknown_affiliate_and_payment_fees", "amount_usd": None, "source_content_sha256": legal_hash or primary_hash},
        "production": {"status": "unknown_founder_evening_weekend_and_livestream_labor", "amount_usd": None, "source_content_sha256": ama_hash or primary_hash},
    }
    ledger = json.loads((ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json").read_text())
    matches = [row for row in ledger["records"] if row.get("company") == "Parqet"]
    hashes = [row["source_content_sha256"] for row in captured]
    duplicate_screen = {
        "source_unified_review_ledger_sha256": ledger["content_sha256"],
        "company_match_count": len(matches),
        "company_match_review_packet_ids": [row["review_packet_id"] for row in matches],
        "exact_content_mirror_detected": len(hashes) != len(set(hashes)),
        "additional_case_episode_collision_detected": len(matches) > 1,
    }
    primary_markers = {row["marker"] for row in by_role.get("founder_interview_2024", {}).get("targeted_claim_windows", [])}
    ama_markers = {row["marker"] for row in by_role.get("founder_ama_2021", {}).get("targeted_claim_windows", [])}
    resource_bound = {"$100/per month", "first five months"}.issubset(primary_markers)
    outcome_bound = "$108k MRR" in primary_markers or "close to €100k" in primary_markers
    gates = {
        "named_company_product_motion_audience": "evidence_ready",
        "exact_subvertical_classification": "evidence_ready",
        "observed_period_and_recency": "evidence_ready_historical_mechanism",
        "market_scale_and_lifecycle": "evidence_ready",
        "source_bound_budget_tier": "evidence_ready_low_budget_initial_tools_bounded_labor_and_later_paid_unknown" if resource_bound else "blocked",
        "six_cost_components": "evidence_ready_all_six_recorded_without_free_labor_or_zero_paid_assumption",
        "result_claim_binding": "evidence_ready_founder_stated_not_audited" if outcome_bound else "blocked",
        "independent_outcome_surface": "evidence_ready_two_independent_reproductions_not_audit" if len(independent) >= 2 else "blocked",
        "entity_and_episode_resolution": "evidence_ready_legal_entity_founder_product_binding" if {"founder_interview_2024", "official_legal_identity"}.issubset(by_role) else "blocked",
        "cross_platform_duplicate_review": "evidence_ready_machine_screen" if not duplicate_screen["exact_content_mirror_detected"] and not duplicate_screen["additional_case_episode_collision_detected"] else "pending_named_review",
        "named_human_exact_binding": "pending_named_review",
    }
    ready = sum(str(value).startswith("evidence_ready") for value in gates.values())
    payload = {
        "schema": "ProofLaunchGTMParqetAdmissionDossierV2",
        "company": "Parqet",
        "legal_entity_hint": "Parqet Fintech GmbH",
        "founder_identity": "Sumit Kumar",
        "entity_key": "entity-" + hashlib.sha256(b"parqet fintech gmbh|parqet|sumit kumar").hexdigest()[:20],
        "episode_key": "episode-" + hashlib.sha256(b"parqet|dach product-led organic growth|2019-12-01|2024-08-02").hexdigest()[:20],
        "provisional_subvertical_id": "b2c.personal_finance.investing",
        "episode_definition": "December 2019 to August 2024 bootstrapped DACH portfolio-tracking growth from a self-use MVP to founder-stated approximately €100K MRR, with an initially organic product-sharing loop and later mixed acquisition.",
        "source_count": len(records),
        "captured_source_count": len(captured),
        "independent_captured_source_count": len(independent),
        "early_zero_paid_statement_present": "haven't spent a single ad-dollar" in ama_markers,
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
        "truth_boundary": "The approximately €100K MRR outcome is founder-stated and not audited. The founder bounds the first five months at about $100/month and reports the first two years as organic, but later paid ads, affiliate revenue share, team labor, data, tools and production remain incomplete; the full episode is low-budget, never zero-cost.",
    }
    payload["content_sha256"] = _digest(payload)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "captured_source_count": len(captured), "independent_captured_source_count": len(independent), "ready_gates": ready, "blocking_gates": len(gates) - ready, "content_sha256": payload["content_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
