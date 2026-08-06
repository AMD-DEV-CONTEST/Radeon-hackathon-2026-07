from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping, Sequence


SCHEMA = "ProofLaunchGTMBreakoutQualityTeamSeedV1"
ALLOWED_STATUSES = {"mechanism_distillation_ready", "outcome_seed_only"}
ALLOWED_BUDGET_TIERS = {
    "cold_start_zero_paid",
    "cold_start_low_budget",
    "capital_efficient",
    "mixed_budget",
    "mature_scaled",
    "undisclosed",
}


class GTMBreakoutQualityTeamSeedError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_breakout_quality_team_seed(cases: Sequence[Mapping[str, Any]], *, captured_at: str) -> dict[str, Any]:
    if not captured_at or not cases:
        raise GTMBreakoutQualityTeamSeedError("captured_at and cases are required")
    normalized = []
    seen = set()
    for raw in cases:
        case = dict(raw)
        team_id = str(case.get("team_id", ""))
        if not team_id or team_id in seen:
            raise GTMBreakoutQualityTeamSeedError(f"missing or duplicate team id: {team_id}")
        seen.add(team_id)
        if case.get("promotion_status") not in ALLOWED_STATUSES:
            raise GTMBreakoutQualityTeamSeedError(f"invalid promotion status: {team_id}")
        case.setdefault("cold_start_budget_tier", "undisclosed")
        case.setdefault("cold_start_budget_window", "not_yet_evidenced")
        case.setdefault("reported_zero_paid_media", False)
        case.setdefault("transferable_mechanism_tags", [])
        if case["cold_start_budget_tier"] not in ALLOWED_BUDGET_TIERS:
            raise GTMBreakoutQualityTeamSeedError(f"invalid cold-start budget tier: {team_id}")
        if not case.get("sources") or any(not source.get("url", "").startswith("https://") for source in case["sources"]):
            raise GTMBreakoutQualityTeamSeedError(f"official source provenance is incomplete: {team_id}")
        dimensions = case.get("evidence_dimensions", {})
        required_dimensions = {
            "hard_outcome",
            "current_operation",
            "recent_three_to_six_month_breakout",
            "channel_mechanism",
            "retention_or_repeatability",
            "paid_organic_resource_scope",
        }
        if set(dimensions) != required_dimensions:
            raise GTMBreakoutQualityTeamSeedError(f"evidence dimensions drifted: {team_id}")
        case["complete_evidence_dimension_count"] = sum(value == "verified" for value in dimensions.values())
        case["zero_budget_proof"] = False
        case["copy_training_eligible"] = False
        case["breakout_team_fully_promoted"] = False
        normalized.append(case)
    normalized.sort(
        key=lambda item: (
            0 if item["promotion_status"] == "mechanism_distillation_ready" else 1,
            -item["complete_evidence_dimension_count"],
            item["team_name"].casefold(),
        )
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "captured_at": captured_at,
        "team_count": len(normalized),
        "promotion_status_counts": dict(sorted(Counter(case["promotion_status"] for case in normalized).items())),
        "cold_start_budget_tier_counts": dict(
            sorted(Counter(case["cold_start_budget_tier"] for case in normalized).items())
        ),
        "mechanism_tag_counts": dict(
            sorted(Counter(tag for case in normalized for tag in case["transferable_mechanism_tags"]).items())
        ),
        "sector_focus_counts": dict(
            sorted(Counter(case["sector_focus"] for case in normalized if case.get("sector_focus")).items())
        ),
        "teams": normalized,
        "selection_policy": {
            "accelerator_membership_weight": 0,
            "funding_weight": 0,
            "valuation_weight": 0,
            "zero_budget_required": False,
            "cold_start_resource_window_months": [6, 12],
            "accepted_resource_tiers": list(sorted(ALLOWED_BUDGET_TIERS)),
            "resource_efficiency_rule": (
                "Zero paid media, low budget, or demonstrably capital-efficient mixed spend can all qualify. The team must expose "
                "resource scope and connect spend or effort to activation, retention, and monetization during a comparable 6-12 month stage."
            ),
            "required_for_full_promotion": [
                "hard_business_or_user_outcome",
                "current_operation",
                "recent_relative_breakout",
                "observable_channel_mechanism",
                "retention_or_repeatability",
                "paid_organic_and_resource_scope",
                "independent_or_audited_corroboration",
                "human_review",
            ],
            "mechanism_distillation_rule": (
                "A team may enter bounded mechanism distillation when its outcome, recent operation, channel mechanism, and "
                "retention or repeatability are inspectable. This does not make it a zero-budget precedent or authorize copy reuse."
            ),
            "priority_nonsoftware_b2b_rule": (
                "Manufacturing, engineering and construction, real estate, professional services, industrial distribution, and "
                "other non-software B2B examples must preserve their own buying committee, specification, quote, partner, "
                "fulfillment, and repeat-order mechanics; they may not inherit SaaS activation logic by analogy alone."
            ),
        },
        "truth_boundary": (
            "This is a small high-signal seed, not a global ranking. Most metrics are company or vendor self-reports and remain "
            "explicitly labeled. No listed team is fully promoted, no source creative or copy is training-eligible, and none proves "
            "zero budget. Zero budget is not a mandatory standard; disclosed cold-start capital efficiency is. Accelerator pedigree "
            "and financing are ignored as quality signals."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_breakout_quality_team_seed(payload: Mapping[str, Any]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise GTMBreakoutQualityTeamSeedError("quality seed digest or schema is invalid")
    if payload.get("team_count") != len(payload.get("teams", [])):
        raise GTMBreakoutQualityTeamSeedError("quality seed count drifted")
    if any(team.get("breakout_team_fully_promoted") is not False for team in payload.get("teams", [])):
        raise GTMBreakoutQualityTeamSeedError("a team bypassed full promotion")
    if any(team.get("zero_budget_proof") is not False for team in payload.get("teams", [])):
        raise GTMBreakoutQualityTeamSeedError("a team was mislabeled as zero-budget proof")
