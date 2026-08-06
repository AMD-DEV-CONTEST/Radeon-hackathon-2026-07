from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any, Mapping, Sequence


class GTMBreakoutCampaignError(ValueError):
    """A campaign escaped the creative, native-format, or authority contract."""


SCHEMA = "ProofLaunchGTMBreakoutCampaignPortfolioV1"
CANDIDATE_SCHEMA = "ProofLaunchGTMBreakoutCampaignCandidateV1"

SOCIAL_SURFACES = (
    "linkedin",
    "tiktok",
    "instagram",
    "reddit",
    "x",
    "facebook",
    "pinterest",
    "bluesky",
    "mastodon",
)
CONVERSION_SURFACES = ("seo", "geo", "email", "landing_page")
REQUIRED_SURFACES = SOCIAL_SURFACES + CONVERSION_SURFACES
REQUIRED_CREW_ROLES = (
    "gtm_strategist",
    "cultural_researcher",
    "brand_planner",
    "creative_director",
    "copy_chief",
    "platform_editor",
    "short_form_director",
    "visual_director",
    "community_operator",
    "distribution_architect",
    "measurement_scientist",
    "conversion_architect",
)
REQUIRED_STRATEGY_FIELDS = (
    "human_tension",
    "category_convention",
    "strategic_wedge",
    "creative_platform",
    "ownable_phrase",
    "earned_distribution_thesis",
    "conversion_path",
    "why_now",
    "noncopying_transform",
)
REQUIRED_LANGUAGE_FIELDS = (
    "segment",
    "buyer_or_user",
    "decision_tension",
    "proof_language",
    "native_voice",
    "forbidden_shortcut",
)
REQUIRED_ASSET_FIELDS = (
    "surface_id",
    "job",
    "audience_state",
    "native_format",
    "hook",
    "publishable_copy",
    "media_direction",
    "native_mechanic",
    "earned_distribution_mechanism",
    "cta",
    "proof_unit",
    "metric",
    "kill_rule",
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
_PLACEHOLDER = re.compile(
    r"\b(?:tbd|todo|lorem ipsum|insert (?:link|copy|name)|example\.com|coming soon)\b",
    re.IGNORECASE,
)
_GENERIC_CTA = re.compile(
    r"^(?:learn more|get started|click here|sign up|book a demo|contact us)[.!]?$",
    re.IGNORECASE,
)
_ABUSE = re.compile(
    r"(?:fake scarcity|fake review|fake account|bot farm|engagement pod|mass unsolicited|"
    r"credential stuffing|captcha bypass|rate.?limit evasion|impersonat|astroturf|"
    r"coordinated inauthentic|buy followers|scrape private)",
    re.IGNORECASE,
)
_DEFENSIVE_PHRASES = re.compile(
    r"(?:synthetic capability reference|no (?:market )?effect|not (?:a )?claim|"
    r"does not (?:prove|establish)|human review pending|draft pending)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-z0-9][a-z0-9'-]+", re.IGNORECASE)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, field: str, minimum: int = 12) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise GTMBreakoutCampaignError(f"{field} is missing or too thin")
    text = value.strip()
    if _PLACEHOLDER.search(text):
        raise GTMBreakoutCampaignError(f"{field} contains a placeholder")
    if _ABUSE.search(text):
        raise GTMBreakoutCampaignError(f"{field} contains a prohibited manipulation tactic")
    return text


def _strings(value: Any, field: str, count: int, minimum: int = 8) -> list[str]:
    if not isinstance(value, list) or len(value) < count:
        raise GTMBreakoutCampaignError(f"{field} is incomplete")
    return [_text(item, f"{field}[{index}]", minimum) for index, item in enumerate(value)]


def _words(value: str) -> set[str]:
    return {match.group(0).casefold() for match in _WORD.finditer(value) if len(match.group(0)) > 2}


def _jaccard(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _verify_native_shape(asset: Mapping[str, Any]) -> None:
    surface = str(asset["surface_id"])
    copy = str(asset["publishable_copy"])
    native = str(asset["native_format"]).casefold()
    if surface == "linkedin" and ("\n\n" not in copy or len(copy) < 420):
        raise GTMBreakoutCampaignError("LinkedIn copy must carry a developed point of view")
    if surface == "x" and not re.search(r"(?:^|\n)1/", copy):
        raise GTMBreakoutCampaignError("X asset must be a native numbered thread")
    if surface == "reddit" and not re.search(r"(?:title|discussion|postmortem|counterexample)", native):
        raise GTMBreakoutCampaignError("Reddit asset must declare a discussion-native format")
    if surface == "tiktok" and not re.search(r"\[(?:0:)?0[0-9]", copy):
        raise GTMBreakoutCampaignError("TikTok asset must contain timed shot language")
    if surface == "instagram" and not re.search(r"(?:carousel|reel|card)", native):
        raise GTMBreakoutCampaignError("Instagram asset must be visual-format native")
    if surface == "pinterest" and not re.search(r"(?:pin|checklist|template|search)", native):
        raise GTMBreakoutCampaignError("Pinterest asset must carry durable search/save utility")
    if surface == "bluesky" and len(copy) > 1200:
        raise GTMBreakoutCampaignError("Bluesky copy is not feed-native")
    if surface == "mastodon" and not re.search(r"(?:alt|content warning|thread|federated)", native):
        raise GTMBreakoutCampaignError("Mastodon asset must declare an accessibility/federation shape")
    if surface == "seo" and not re.search(r"(?:page|guide|template)", native):
        raise GTMBreakoutCampaignError("SEO asset must be a durable answer page")
    if surface == "geo" and not re.search(r"(?:direct answer|answer object|citation)", native):
        raise GTMBreakoutCampaignError("GEO asset must expose a direct answer contract")
    if surface == "email" and not re.search(r"(?:requested|triggered|reply|sequence)", native):
        raise GTMBreakoutCampaignError("Email asset must declare a consent-bound lifecycle trigger")
    if surface == "landing_page" and not re.search(r"(?:hero|interactive|conversion)", native):
        raise GTMBreakoutCampaignError("Landing asset must declare a conversion experience")


def verify_breakout_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    unsigned = dict(candidate)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise GTMBreakoutCampaignError("candidate digest is invalid")
    if candidate.get("schema") != CANDIDATE_SCHEMA:
        raise GTMBreakoutCampaignError("candidate schema is unsupported")

    selector = candidate.get("selector")
    brief = candidate.get("brief")
    strategy = candidate.get("strategic_thesis")
    if not all(isinstance(item, Mapping) for item in (selector, brief, strategy)):
        raise GTMBreakoutCampaignError("selector, brief and strategic thesis are required")
    if selector.get("business_model") not in {"b2b", "b2c"}:
        raise GTMBreakoutCampaignError("business model must be b2b or b2c")
    if selector.get("budget") != "zero":
        raise GTMBreakoutCampaignError("breakout release candidates must prove a zero-budget route")
    for field in ("industry", "lifecycle", "market", "primary_goal"):
        _text(selector.get(field), f"selector.{field}", 3)
    for field in ("brand_name", "product_name", "audience", "audience_moment", "job_to_be_done", "voice"):
        _text(brief.get(field), f"brief.{field}", 8)
    _strings(brief.get("product_truths"), "brief.product_truths", 2, 18)
    _strings(brief.get("proof_assets"), "brief.proof_assets", 2, 12)
    _strings(brief.get("prohibited_claims"), "brief.prohibited_claims", 3, 12)
    for field in REQUIRED_STRATEGY_FIELDS:
        _text(strategy.get(field), f"strategic_thesis.{field}", 18)
    if strategy.get("source_phrase_reuse_allowed") is not False:
        raise GTMBreakoutCampaignError("source phrase reuse must remain disabled")
    if not isinstance(strategy.get("maximum_reference_copy_overlap"), (int, float)) or not 0 <= float(strategy["maximum_reference_copy_overlap"]) <= 0.15:
        raise GTMBreakoutCampaignError("reference copy overlap ceiling must be <= 0.15")

    evidence = candidate.get("evidence_application")
    if not isinstance(evidence, Mapping):
        raise GTMBreakoutCampaignError("evidence application is required")
    if not _SHA.fullmatch(str(evidence.get("evidence_ledger_sha256", ""))):
        raise GTMBreakoutCampaignError("evidence ledger digest is invalid")
    mechanism_ids = _strings(evidence.get("mechanism_ids"), "evidence_application.mechanism_ids", 3, 4)
    case_ids = _strings(evidence.get("case_ids"), "evidence_application.case_ids", 6, 4)
    if len(set(mechanism_ids)) != len(mechanism_ids) or len(set(case_ids)) != len(case_ids):
        raise GTMBreakoutCampaignError("evidence application contains duplicate references")
    for field in ("application_rationale", "failure_boundary", "attention_to_revenue_bridge"):
        _text(evidence.get(field), f"evidence_application.{field}", 40)
    if evidence.get("claims_zero_paid_media_precedent") is not False:
        raise GTMBreakoutCampaignError("candidate overstates a zero-paid-media precedent")

    language = candidate.get("industry_language_contract")
    if not isinstance(language, Mapping):
        raise GTMBreakoutCampaignError("industry language contract is required")
    for field in REQUIRED_LANGUAGE_FIELDS:
        _text(language.get(field), f"industry_language_contract.{field}", 8)
    if language.get("generic_cross_industry_copy_allowed") is not False:
        raise GTMBreakoutCampaignError("generic cross-industry copy must remain disabled")

    crew = candidate.get("crew")
    if not isinstance(crew, list) or {row.get("role_id") for row in crew if isinstance(row, Mapping)} != set(REQUIRED_CREW_ROLES):
        raise GTMBreakoutCampaignError("the complete GTM crew decision system is required")
    for index, role in enumerate(crew):
        if not isinstance(role, Mapping):
            raise GTMBreakoutCampaignError("crew row is invalid")
        for field in ("decision_right", "deliverable", "quality_bar", "kpi"):
            _text(role.get(field), f"crew[{index}].{field}", 12)

    assets = candidate.get("assets")
    if not isinstance(assets, list) or len(assets) != len(REQUIRED_SURFACES):
        raise GTMBreakoutCampaignError("exactly thirteen release surfaces are required")
    by_surface: dict[str, Mapping[str, Any]] = {}
    hooks: list[str] = []
    social_copy: list[str] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, Mapping):
            raise GTMBreakoutCampaignError("asset row is invalid")
        for field in REQUIRED_ASSET_FIELDS:
            minimum = 1 if field == "surface_id" else (24 if field in {"publishable_copy", "media_direction", "earned_distribution_mechanism", "proof_unit", "kill_rule"} else 8)
            _text(asset.get(field), f"assets[{index}].{field}", minimum)
        surface = str(asset["surface_id"])
        if surface in by_surface or surface not in REQUIRED_SURFACES:
            raise GTMBreakoutCampaignError("asset surface coverage is invalid")
        if _GENERIC_CTA.fullmatch(str(asset["cta"]).strip()):
            raise GTMBreakoutCampaignError(f"{surface} uses a generic CTA")
        _verify_native_shape(asset)
        by_surface[surface] = asset
        hooks.append(str(asset["hook"]).casefold())
        if surface in SOCIAL_SURFACES:
            social_copy.append(str(asset["publishable_copy"]))
    if set(by_surface) != set(REQUIRED_SURFACES) or len(set(hooks)) != len(hooks):
        raise GTMBreakoutCampaignError("surface coverage or hook uniqueness failed")
    for left_index, left in enumerate(social_copy):
        for right in social_copy[left_index + 1 :]:
            if _jaccard(left, right) > 0.58:
                raise GTMBreakoutCampaignError("social assets are cross-platform rewrites")
    social_words = sum(max(1, len(_words(copy))) for copy in social_copy)
    defensive_hits = sum(len(_DEFENSIVE_PHRASES.findall(copy)) for copy in social_copy)
    if defensive_hits / social_words > 0.012:
        raise GTMBreakoutCampaignError("defensive boilerplate dominates campaign copy")

    flight = candidate.get("seven_day_flight")
    if not isinstance(flight, list) or len(flight) != 7:
        raise GTMBreakoutCampaignError("seven-day flight must contain exactly seven decisions")
    for index, day in enumerate(flight, start=1):
        if not isinstance(day, Mapping) or day.get("day") != index:
            raise GTMBreakoutCampaignError("seven-day flight order is invalid")
        for field in ("objective", "release", "community_move", "observation", "decision_rule"):
            _text(day.get(field), f"seven_day_flight[{index}].{field}", 12)

    loops = candidate.get("self_evolution")
    if not isinstance(loops, Mapping):
        raise GTMBreakoutCampaignError("self-evolution contract is required")
    for field in ("observe", "diagnose", "propose", "human_gate", "memory_write"):
        _text(loops.get(field), f"self_evolution.{field}", 16)
    if loops.get("automatic_strategy_mutation") is not False or loops.get("learn_only_from_human_approved_results") is not True:
        raise GTMBreakoutCampaignError("self-evolution authority escaped")

    permissions = candidate.get("permissions")
    if not isinstance(permissions, Mapping) or any(
        permissions.get(field) is not False
        for field in ("automatic_publish", "automatic_spend", "automatic_outreach", "fabricated_engagement")
    ):
        raise GTMBreakoutCampaignError("external action permissions escaped")

    return {
        "candidate_id": candidate.get("candidate_id"),
        "business_model": selector["business_model"],
        "surface_count": len(assets),
        "crew_role_count": len(crew),
        "hook_count": len(set(hooks)),
        "evidence_mechanism_count": len(mechanism_ids),
        "evidence_case_count": len(case_ids),
        "maximum_social_copy_jaccard": round(
            max(
                (_jaccard(left, right) for i, left in enumerate(social_copy) for right in social_copy[i + 1 :]),
                default=0.0,
            ),
            4,
        ),
        "defensive_boilerplate_hits": defensive_hits,
        "mechanical_ready": True,
    }


def compile_breakout_portfolio(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(candidates) < 2:
        raise GTMBreakoutCampaignError("portfolio requires at least one B2B and one B2C candidate")
    audits = [verify_breakout_candidate(candidate) for candidate in candidates]
    if Counter(audit["business_model"] for audit in audits) != Counter({"b2b": 1, "b2c": 1}):
        raise GTMBreakoutCampaignError("release portfolio must contain exactly one B2B and one B2C candidate")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "mechanically_ready_pending_named_human_review_and_market_observation",
        "candidate_count": len(candidates),
        "surface_count": sum(audit["surface_count"] for audit in audits),
        "crew_role_count_per_candidate": len(REQUIRED_CREW_ROLES),
        "audits": audits,
        "candidates": [dict(candidate) for candidate in candidates],
        "named_product_pk_completed_count": 0,
        "human_review_completed_count": 0,
        "production_effect_observed_count": 0,
        "truth_boundary": (
            "These clean-room candidates prove a stricter cross-industry generation and mechanical-quality contract. "
            "They do not prove human preference, publication, organic breakout, conversion, revenue, 4A parity or named-product superiority."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def seal_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(candidate)
    sealed.pop("content_sha256", None)
    sealed["content_sha256"] = _digest(sealed)
    return sealed


def verify_breakout_portfolio(portfolio: Mapping[str, Any]) -> None:
    unsigned = dict(portfolio)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned) or portfolio.get("schema") != SCHEMA:
        raise GTMBreakoutCampaignError("portfolio digest or schema is invalid")
    candidates = portfolio.get("candidates")
    if not isinstance(candidates, list):
        raise GTMBreakoutCampaignError("portfolio candidates are missing")
    rebuilt = compile_breakout_portfolio(candidates)
    if rebuilt != portfolio:
        raise GTMBreakoutCampaignError("portfolio aggregates drifted")
