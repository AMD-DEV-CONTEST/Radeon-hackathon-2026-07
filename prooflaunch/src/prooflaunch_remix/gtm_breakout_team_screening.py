from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMBreakoutTeamScreenV1"
INDUSTRIES = (
    "Artificial intelligence",
    "Software & services",
    "Life Sciences",
    "Fintech",
    "Energy & sustainability technology",
    "Digital content/media/entertainment",
    "Hardware & semiconductors (including electronic devices)",
    "Communications/networking",
    "Technology, Media & Telecom",
)


class GTMBreakoutTeamScreeningError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _normalize_name(name: str) -> str:
    value = name.casefold().replace("&", " and ")
    value = re.sub(r"\b(incorporated|inc|llc|ltd|limited|corp|corporation|holdings?)\b", " ", value)
    return re.sub(r"[^a-z0-9]+", "", value)


def parse_deloitte_fast500_text(text: str) -> list[dict[str, Any]]:
    chunks: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^\d+\s+", stripped):
            if current:
                chunks.append(current)
            current = stripped
        elif current and stripped and not stripped.startswith("2025 Technology") and not stripped.startswith("Rank Company"):
            current += " " + stripped
    if current:
        chunks.append(current)
    industry_pattern = "|".join(re.escape(industry) for industry in INDUSTRIES)
    pattern = re.compile(
        rf"^(\d+)\s+(.+?)\s+({industry_pattern})\s+(\d+)%\s+(.+?)\s+([A-Z]{{2}})\s+(.+)$"
    )
    rows = []
    seen_rows = set()
    for chunk in chunks:
        match = pattern.match(chunk)
        if not match:
            continue
        rank, company, industry, growth, city, state, _ceo = match.groups()
        normalized = re.sub(r"[^a-z0-9]+", "", company.casefold())
        row_key = (int(rank), normalized)
        if not normalized or row_key in seen_rows:
            raise GTMBreakoutTeamScreeningError(f"duplicate Fast 500 row: {rank} {company}")
        seen_rows.add(row_key)
        rows.append(
            {
                "rank": int(rank),
                "company_name": " ".join(company.split()),
                "primary_industry": industry,
                "revenue_growth_percent": int(growth),
                "city": " ".join(city.split()),
                "state_or_province": state,
            }
        )
    rows.sort(key=lambda item: (item["rank"], item["company_name"].casefold()))
    if len(rows) < 500 or rows[0]["rank"] != 1 or rows[-1]["rank"] != 500:
        raise GTMBreakoutTeamScreeningError("Fast 500 table extraction is incomplete")
    return rows


def compile_breakout_team_screen(
    fast500_rows: Sequence[Mapping[str, Any]],
    startup_landscape: Mapping[str, Any],
    *,
    source_url: str,
    source_pdf_sha256: str,
) -> dict[str, Any]:
    if len(fast500_rows) < 500 or not source_url.startswith("https://") or not re.fullmatch(r"[0-9a-f]{64}", source_pdf_sha256):
        raise GTMBreakoutTeamScreeningError("Fast 500 provenance is incomplete")
    yc_by_name: dict[str, list[Mapping[str, Any]]] = {}
    for record in startup_landscape.get("records", []):
        yc_by_name.setdefault(_normalize_name(record["name"]), []).append(record)
    fast_name_counts = Counter(_normalize_name(str(row["company_name"])) for row in fast500_rows)
    candidates = []
    match_count = 0
    model_counts: Counter[str] = Counter()
    industry_counts: Counter[str] = Counter()
    maximum_rank = max(int(row["rank"]) for row in fast500_rows)
    for row in fast500_rows:
        company_name = str(row["company_name"])
        normalized_company_name = _normalize_name(company_name)
        yc_matches = yc_by_name.get(normalized_company_name, [])
        yc = yc_matches[0] if len(yc_matches) == 1 and fast_name_counts[normalized_company_name] == 1 else None
        if yc:
            match_count += 1
        business_model = yc["business_model"] if yc else "unresolved"
        model_counts[business_model] += 1
        industry_counts[str(row["primary_industry"])] += 1
        growth = int(row["revenue_growth_percent"])
        rank = int(row["rank"])

        # The official revenue-growth rank is the only input to outcome priority.
        # Directory membership, accelerator pedigree, funding and directory status
        # are identity evidence only and must never make a team look more successful.
        outcome_screen_score = round(100 - (rank - 1) * 40 / max(1, maximum_rank - 1))
        outcome_priority_band = "p0" if rank <= 50 else "p1" if rank <= 150 else "p2"
        identity_evidence_completion_score = 0
        if yc:
            identity_evidence_completion_score += 30
            if yc["directory_status"] == "Active":
                identity_evidence_completion_score += 10
        candidates.append(
            {
                "candidate_id": f"fast500-2025-{rank:03d}-{re.sub(r'[^a-z0-9]+', '-', company_name.casefold()).strip('-')}",
                "company_name": company_name,
                "rank": rank,
                "primary_industry": row["primary_industry"],
                "revenue_growth_percent_2021_2024": growth,
                "city": row["city"],
                "state_or_province": row["state_or_province"],
                "yc_company_id": yc["company_id"] if yc else None,
                "yc_directory_url": yc["official_directory_url"] if yc else None,
                "business_model": business_model,
                "yc_directory_status": yc["directory_status"] if yc else None,
                "startup_identity_crosscheck": (
                    "unique_normalized_name_match"
                    if yc
                    else "ambiguous_name_requires_domain_review"
                    if len(yc_matches) > 1 or fast_name_counts[normalized_company_name] > 1
                    else "not_crossmatched"
                ),
                "official_revenue_growth_evidence": True,
                "current_2026_operating_status": "not_yet_verified",
                "recent_relative_breakout_signal": "not_yet_verified",
                "gtm_channel_mechanism": "not_yet_audited",
                "retention_or_repeatability": "not_yet_audited",
                "spend_and_resource_scope": "not_yet_audited",
                "breakout_team_eligible": False,
                "promotion_blockers": [
                    "current_2026_operating_status",
                    "recent_three_to_six_month_relative_breakout",
                    "observable_gtm_channel_mechanism",
                    "retention_or_repeatability",
                    "organic_paid_and_resource_scope",
                    "human_quality_review",
                ],
                "outcome_screen_score": outcome_screen_score,
                "outcome_priority_band": outcome_priority_band,
                "identity_evidence_completion_score": identity_evidence_completion_score,
                "yc_identity_contributes_to_outcome_score": False,
            }
        )
    candidates.sort(key=lambda item: (item["rank"], -item["revenue_growth_percent_2021_2024"], item["company_name"].casefold()))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "source": {
            "publisher": "Deloitte",
            "program": "2025 North America Technology Fast 500",
            "url": source_url,
            "pdf_sha256": source_pdf_sha256,
            "measurement_window": "2021-2024 fiscal-year revenue growth",
            "eligibility_floor": {
                "base_year_operating_revenue_usd": 50000,
                "current_year_operating_revenue_usd": 5000000,
                "minimum_years_in_business": 4,
                "proprietary_technology_revenue_requirement": True,
            },
        },
        "candidate_count": len(candidates),
        "yc_exact_crossmatch_count": match_count,
        "business_model_counts": dict(sorted(model_counts.items())),
        "primary_industry_counts": dict(sorted(industry_counts.items())),
        "outcome_priority_band_counts": dict(
            sorted(Counter(item["outcome_priority_band"] for item in candidates).items())
        ),
        "quality_screening_policy": {
            "quality_signal": "official_ranked_revenue_growth_only_at_candidate_stage",
            "yc_membership_quality_weight": 0,
            "accelerator_membership_quality_weight": 0,
            "funding_quality_weight": 0,
            "directory_status_quality_weight": 0,
            "p0_definition": "official revenue-growth ranks 1-50",
            "p1_definition": "official revenue-growth ranks 51-150",
            "p2_definition": "official revenue-growth ranks 151-500",
        },
        "candidates": candidates,
        "promotion_gate": {
            "official_revenue_growth_required": True,
            "current_operating_status_required": True,
            "recent_three_to_six_month_relative_breakout_required": True,
            "observable_gtm_channel_mechanism_required": True,
            "retention_or_repeatability_evidence_required": True,
            "spend_and_resource_scope_required": True,
            "organic_or_efficient_growth_separation_required": True,
            "survivorship_and_current_viability_review_required": True,
            "human_quality_review_required": True,
            "automatic_promotion_allowed": False,
        },
        "business_model_quality_gates": {
            "b2b": {
                "hard_outcome": "windowed ARR/revenue or qualified-pipeline-to-revenue evidence",
                "retention": "renewal, gross retention, NRR, expansion, or equivalent cohort evidence",
                "efficient_distribution": "organic/inbound/referral share or CAC and payback with paid-spend scope",
                "repeatability": "the mechanism recurs across at least three cohorts, cycles, segments, or customers",
                "last_mile_quality": "inspectable platform-native assets connected to qualified activation and revenue",
            },
            "b2c": {
                "hard_outcome": "windowed active-user, paid-customer, revenue, or repeat-purchase evidence",
                "retention": "D30/D90 retention, repeat purchase, subscription renewal, or equivalent cohort evidence",
                "efficient_distribution": "organic/referral contribution separated from paid installs, creators, affiliates, and owned media",
                "repeatability": "the mechanism recurs across at least three cohorts, content cycles, products, or markets",
                "last_mile_quality": "inspectable platform-native creative connected to activation, retention, and monetization",
            },
            "automatic_rejections": [
                "accelerator_or_funding_pedigree_without_outcome_evidence",
                "followers_views_or_awards_without_activation_or_business_bridge",
                "single_viral_post_without_repeatability",
                "paid_growth_presented_as_organic",
                "founder_claim_without_source_and_measurement_window",
                "inactive_or_unverified_current_operation",
            ],
        },
        "truth_boundary": (
            "Fast 500 revenue growth is a hard outcome screen, not proof of a viral campaign or GTM cause. YC membership is a "
            "startup identity crosscheck with zero quality weight, not a quality label. Funding, accelerator pedigree, awards, reach, "
            "and paid acquisition alone cannot promote a team. No team is promoted until current operation, recent relative breakout, "
            "channel mechanism, repeatability, retention, and resource scope are separately evidenced."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_breakout_team_screen(screen: Mapping[str, Any]) -> None:
    unsigned = dict(screen)
    supplied = unsigned.pop("content_sha256", None)
    if screen.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMBreakoutTeamScreeningError("breakout team screen digest or schema is invalid")
    if screen.get("candidate_count") != len(screen.get("candidates", [])):
        raise GTMBreakoutTeamScreeningError("breakout team candidate count drifted")
    if any(candidate.get("breakout_team_eligible") is not False for candidate in screen.get("candidates", [])):
        raise GTMBreakoutTeamScreeningError("a candidate bypassed the breakout promotion gate")
    if any(candidate.get("yc_identity_contributes_to_outcome_score") is not False for candidate in screen.get("candidates", [])):
        raise GTMBreakoutTeamScreeningError("YC identity contaminated the outcome score")
