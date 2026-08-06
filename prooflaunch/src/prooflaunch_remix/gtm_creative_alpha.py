from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from statistics import median
from typing import Any, Mapping, Sequence

from .gtm_market_language import (
    B2B_CATEGORY_IDS,
    B2C_CATEGORY_IDS,
    compile_market_language_contract,
    verify_market_language_contract,
)
from .gtm_generative_execution_kernel import AXES as GENERATIVE_AXES, CAPABILITY_LANES
from .gtm_team_capability_os import (
    compile_gtm_team_capability_contract,
    verify_gtm_team_capability_contract,
)
from .gtm_strategy import (
    BusinessModel,
    CampaignStrategyInput,
    Channel,
    ContentCapacity,
    IndustryRisk,
    LifecycleStage,
    GTMStrategy,
)


class CreativeAlphaError(ValueError):
    """A creative-alpha input or plan violated the bounded research contract."""


PLAN_SCHEMA = "ProofLaunchCreativeAlphaPlanV1"
RADAR_SCHEMA = "ProofLaunchGrowthCaseRadarV1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_WINDOWS = (28, 90, 180)
_MINIMUM_CELL_CASES = 10
_MAXIMUM_SNAPSHOT_AGE_DAYS = 7
_RIGHTS = frozenset({"public_measurement", "account_authorized", "owned"})
_RAW_CREATIVE_FIELDS = frozenset(
    {
        "caption",
        "script",
        "transcript",
        "creative_text",
        "raw_text",
        "media_url",
        "download_url",
        "username",
        "user_id",
    }
)
_RATE_FIELDS = (
    "active_audience_growth_rate",
    "qualified_engagement_rate",
    "conversion_signal_rate",
    "content_supply_growth_rate",
)
_FACTOR_WEIGHTS = {
    "audience_growth_residual_90d": 0.24,
    "growth_acceleration_28_vs_90": 0.18,
    "engagement_quality_residual_90d": 0.20,
    "conversion_signal_residual_90d": 0.14,
    "persistence_floor_90_180": 0.14,
    "content_supply_saturation": -0.20,
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: object, field: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CreativeAlphaError(f"{field} must be a nonblank bounded string")
    if "\x00" in value:
        raise CreativeAlphaError(f"{field} contains a NUL byte")
    return value.strip()


def _time(value: object, field: str) -> datetime:
    text = _text(value, field, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise CreativeAlphaError(f"{field} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CreativeAlphaError(f"{field} must include a timezone")
    return parsed


def _rate(value: object, field: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise CreativeAlphaError(f"{field} must be finite")
    number = float(value)
    if not -1.0 <= number <= 10.0:
        raise CreativeAlphaError(f"{field} must be a rate in [-1, 10]")
    return number


def _window_metrics(value: object, field: str, *, require_sample: bool) -> dict[str, float | int]:
    if not isinstance(value, Mapping):
        raise CreativeAlphaError(f"{field} must be an object")
    required = set(_RATE_FIELDS) | ({"sample_size"} if require_sample else set())
    if set(value) != required:
        raise CreativeAlphaError(f"{field} fields do not match the closed contract")
    metrics: dict[str, float | int] = {
        name: _rate(value.get(name), f"{field}.{name}") for name in _RATE_FIELDS
    }
    if require_sample:
        sample = value.get("sample_size")
        if type(sample) is not int or not 1 <= sample <= 1_000_000_000:
            raise CreativeAlphaError(f"{field}.sample_size must be a positive integer")
        metrics["sample_size"] = sample
    return metrics


def _robust_z(values: Sequence[float]) -> list[float]:
    center = median(values)
    deviations = [abs(value - center) for value in values]
    mad = median(deviations)
    if mad == 0:
        return [0.0 for _ in values]
    scale = 1.4826 * mad
    return [max(-3.0, min(3.0, (value - center) / scale)) for value in values]


def _validate_radar(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != RADAR_SCHEMA:
        raise CreativeAlphaError("growth-case radar schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or supplied != _digest(unsigned):
        raise CreativeAlphaError("growth-case radar digest is invalid")
    if payload.get("automatic_strategy_mutation_executed") is not False:
        raise CreativeAlphaError("growth-case radar enabled automatic strategy mutation")
    if payload.get("copied_creative_retained") is not False:
        raise CreativeAlphaError("growth-case radar retained copied creative")


def compile_growth_case_radar(
    cases: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Rank point-in-time aggregate growth cases without retaining source creative.

    Cases are compared only inside the same category/platform/market cell. The
    score is a research-priority signal, not a causal attribution or forecast.
    """

    cutoff = _time(as_of, "as_of")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        raise CreativeAlphaError("growth cases must be a sequence")
    if not 1 <= len(cases) <= 500:
        raise CreativeAlphaError("growth cases must contain between 1 and 500 rows")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(cases):
        if not isinstance(row, Mapping):
            raise CreativeAlphaError(f"growth_cases[{index}] must be an object")
        forbidden = _RAW_CREATIVE_FIELDS & set(row)
        if forbidden:
            raise CreativeAlphaError(
                "growth cases cannot retain raw creative fields: "
                + ", ".join(sorted(forbidden))
            )
        case_id = _text(row.get("case_id"), f"growth_cases[{index}].case_id", 128)
        if case_id in seen:
            raise CreativeAlphaError("growth case IDs must be unique")
        seen.add(case_id)
        observed_at = _time(row.get("observed_at"), "observed_at")
        if observed_at > cutoff:
            raise CreativeAlphaError("growth case contains future information")
        if (cutoff - observed_at).total_seconds() > _MAXIMUM_SNAPSHOT_AGE_DAYS * 86_400:
            raise CreativeAlphaError("growth case snapshot is too stale for short-cycle research")
        rights = _text(row.get("rights"), "rights", 64)
        if rights not in _RIGHTS:
            raise CreativeAlphaError("growth case rights are unsupported")
        source_sha256 = _text(row.get("source_uri_sha256"), "source_uri_sha256", 64)
        if not _SHA256.fullmatch(source_sha256):
            raise CreativeAlphaError("growth case source digest is invalid")
        raw_windows = row.get("windows")
        raw_benchmarks = row.get("category_benchmarks")
        if not isinstance(raw_windows, Mapping) or not isinstance(raw_benchmarks, Mapping):
            raise CreativeAlphaError("growth case requires windows and category benchmarks")
        if {int(key) for key in raw_windows} != set(_WINDOWS) or {
            int(key) for key in raw_benchmarks
        } != set(_WINDOWS):
            raise CreativeAlphaError("growth case requires exact 28/90/180-day windows")
        windows = {
            window: _window_metrics(
                raw_windows.get(str(window), raw_windows.get(window)),
                f"windows.{window}",
                require_sample=True,
            )
            for window in _WINDOWS
        }
        benchmarks = {
            window: _window_metrics(
                raw_benchmarks.get(str(window), raw_benchmarks.get(window)),
                f"category_benchmarks.{window}",
                require_sample=False,
            )
            for window in _WINDOWS
        }
        features = {
            "audience_growth_residual_90d": (
                float(windows[90]["active_audience_growth_rate"])
                - float(benchmarks[90]["active_audience_growth_rate"])
            ),
            "growth_acceleration_28_vs_90": (
                float(windows[28]["active_audience_growth_rate"])
                - float(windows[90]["active_audience_growth_rate"])
            ),
            "engagement_quality_residual_90d": (
                float(windows[90]["qualified_engagement_rate"])
                - float(benchmarks[90]["qualified_engagement_rate"])
            ),
            "conversion_signal_residual_90d": (
                float(windows[90]["conversion_signal_rate"])
                - float(benchmarks[90]["conversion_signal_rate"])
            ),
            "persistence_floor_90_180": min(
                float(windows[90]["active_audience_growth_rate"])
                - float(benchmarks[90]["active_audience_growth_rate"]),
                float(windows[180]["active_audience_growth_rate"])
                - float(benchmarks[180]["active_audience_growth_rate"]),
            ),
            "content_supply_saturation": max(
                0.0,
                float(windows[90]["content_supply_growth_rate"])
                - float(windows[90]["active_audience_growth_rate"]),
            ),
        }
        normalized.append(
            {
                "case_id": case_id,
                "category": _text(row.get("category"), "category", 160),
                "platform": _text(row.get("platform"), "platform", 120),
                "market": _text(row.get("market"), "market", 120),
                "observed_at": observed_at.isoformat(),
                "source_uri_sha256": source_sha256,
                "rights": rights,
                "minimum_window_sample_size": min(
                    int(windows[window]["sample_size"]) for window in _WINDOWS
                ),
                "features": features,
            }
        )

    cells: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in normalized:
        key = (row["category"], row["platform"], row["market"])
        cells.setdefault(key, []).append(row)

    ranked_cells: list[dict[str, Any]] = []
    eligible_case_count = 0
    for key, rows in sorted(cells.items()):
        if len(rows) < _MINIMUM_CELL_CASES:
            ranked_cells.append(
                {
                    "category": key[0],
                    "platform": key[1],
                    "market": key[2],
                    "case_count": len(rows),
                    "status": "insufficient_comparable_cases",
                    "ranked_candidates": [],
                }
            )
            continue
        factor_z = {
            factor: _robust_z([float(row["features"][factor]) for row in rows])
            for factor in _FACTOR_WEIGHTS
        }
        candidates: list[dict[str, Any]] = []
        for row_index, row in enumerate(rows):
            z_scores = {factor: factor_z[factor][row_index] for factor in _FACTOR_WEIGHTS}
            raw_score = sum(
                _FACTOR_WEIGHTS[factor] * z_scores[factor]
                for factor in _FACTOR_WEIGHTS
            )
            sample = int(row["minimum_window_sample_size"])
            shrinkage = sample / (sample + 1_000)
            candidates.append(
                {
                    "case_id": row["case_id"],
                    "source_uri_sha256": row["source_uri_sha256"],
                    "observed_at": row["observed_at"],
                    "minimum_window_sample_size": sample,
                    "sample_shrinkage": round(shrinkage, 6),
                    "factor_values": {
                        factor: round(float(value), 8)
                        for factor, value in row["features"].items()
                    },
                    "robust_factor_z": {
                        factor: round(value, 6) for factor, value in z_scores.items()
                    },
                    "research_priority_score": round(raw_score * shrinkage, 6),
                    "status": "hypothesis_candidate_not_growth_claim",
                }
            )
        candidates.sort(
            key=lambda item: (-item["research_priority_score"], item["case_id"])
        )
        for rank, candidate in enumerate(candidates, start=1):
            candidate["within_cell_rank"] = rank
        eligible_case_count += len(candidates)
        ranked_cells.append(
            {
                "category": key[0],
                "platform": key[1],
                "market": key[2],
                "case_count": len(rows),
                "status": "hypothesis_ranking_ready",
                "ranked_candidates": candidates,
            }
        )

    payload: dict[str, Any] = {
        "schema": RADAR_SCHEMA,
        "as_of": cutoff.isoformat(),
        "window_days": list(_WINDOWS),
        "minimum_comparable_cases_per_cell": _MINIMUM_CELL_CASES,
        "maximum_snapshot_age_days": _MAXIMUM_SNAPSHOT_AGE_DAYS,
        "factor_weights": dict(_FACTOR_WEIGHTS),
        "case_count": len(normalized),
        "eligible_case_count": eligible_case_count,
        "cells": ranked_cells,
        "point_in_time_and_no_future_leakage_gate_passed": True,
        "copied_creative_retained": False,
        "automatic_strategy_mutation_executed": False,
        "human_analyst_review_required": True,
        "truth_boundary": (
            "Scores prioritize comparable public or account-authorized aggregate cases for "
            "research. They do not identify a causal growth driver, predict virality, authorize "
            "creative copying, or prove that a case will transfer to the current brand."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    _validate_radar(payload)
    return payload


_PLATFORM_GRAMMARS: dict[str, dict[str, Any]] = {
    Channel.SHORT_VIDEO_ORGANIC.value: {
        "audience_contract": "earn the next second, then sustain satisfaction rather than optimizing empty views",
        "opening_contract": "resolve title or first-frame expectation immediately; no generic logo reveal",
        "body_contract": "one visible tension, escalating proof, a useful payoff and a platform-native participation cue",
        "measurement_signals": ["view_choice", "first_seconds_retention", "completion", "rewatch_or_share", "satisfaction_proxy"],
        "anti_patterns": ["delayed_value", "trend_without_brand_fit", "identical_cross_platform_cut"],
        "official_sources": [
            "https://support.google.com/youtube/answer/16559650?hl=en",
            "https://ads.tiktok.com/help/article/creative-center?lang=en",
        ],
    },
    Channel.LINKEDIN_ORGANIC.value: {
        "audience_contract": "give a decision-maker one original, defensible insight worth carrying into work",
        "opening_contract": "state a sharp operating tension or observed contradiction before brand context",
        "body_contract": "show the decision logic, evidence boundary and practical consequence; invite expert disagreement",
        "measurement_signals": ["qualified_dwell", "saves", "expert_comments", "profile_or_document_actions", "qualified_conversation"],
        "anti_patterns": ["generic_thought_leadership", "manufactured_vulnerability", "engagement_bait"],
        "official_sources": [
            "https://business.linkedin.com/content/dam/me/business/en-us/marketing-solutions/resources/pdfs/5-key-principles-for-marketing-on-linkedIn-95273.pdf"
        ],
    },
    Channel.SEARCH_EDUCATION.value: {
        "audience_contract": "finish the user's decision job with original, first-hand and source-clear value",
        "opening_contract": "answer the query intent directly before expanding the reasoning",
        "body_contract": "add evidence, lived expertise, limitations and a next-step decision aid beyond source summaries",
        "measurement_signals": ["qualified_search_visit", "task_completion", "return_to_search", "citation_or_save", "qualified_action"],
        "anti_patterns": ["search_engine_first_copy", "mass_topic_generation", "summary_without_added_value"],
        "official_sources": [
            "https://developers.google.com/search/docs/fundamentals/creating-helpful-content"
        ],
    },
    Channel.COMMUNITY_LISTENING.value: {
        "audience_contract": "listen first, respect local norms and contribute value before asking for attention",
        "opening_contract": "begin with the community's unresolved problem in its own context, not a campaign line",
        "body_contract": "offer a useful object people can improve, debate or adapt; preserve moderator and community rules",
        "measurement_signals": ["substantive_replies", "problem_language_density", "voluntary_remix", "moderator_acceptance", "qualified_follow_up"],
        "anti_patterns": ["brand_billboard", "cross_community_copy_paste", "comment_extraction_without_context"],
        "official_sources": [
            "https://www.business.reddit.com/blog/how-to-reddit-strategies-from-cannes-marketers"
        ],
    },
}

_GENERIC_GRAMMAR = {
    "audience_contract": "deliver useful audience value before the commercial ask",
    "opening_contract": "open on a context-specific unresolved decision rather than a generic product claim",
    "body_contract": "bind one approved proof to one useful action and one honest limitation",
    "measurement_signals": ["qualified_attention", "useful_participation", "save_or_relay", "qualified_action"],
    "anti_patterns": ["cross_platform_copy_paste", "unsupported_claim", "empty_engagement_bait"],
    "official_sources": [],
}

_DISTRIBUTION_PLATFORM_OVERLAYS: dict[str, dict[str, Any]] = {
    "tiktok": {
        "language_shape": "spoken, immediate, visually demonstrable and participation-ready",
        "opening": "make the use tension or payoff legible in the first beat",
        "content_bias": ["short_video", "reply_or_remix_prompt", "creator_native_demonstration"],
        "quality_signals": ["first_seconds_retention", "completion", "rewatch", "share", "qualified_action"],
        "anti_patterns": ["trend_attachment_without_fit", "ad_voice", "delayed_payoff"],
        "official_sources": ["https://ads.tiktok.com/help/article/creative-center?lang=en"],
    },
    "instagram": {
        "language_shape": "visually led, identity-aware, concise and save-or-share useful",
        "opening": "let the first frame carry one ownable visual and audience tension",
        "content_bias": ["reel", "carousel", "story_sequence"],
        "quality_signals": ["non_follower_reach", "saves", "shares", "qualified_profile_action", "qualified_action"],
        "anti_patterns": ["generic_stock_aesthetic", "caption_as_transcript", "cross_platform_watermark"],
        "official_sources": ["https://www.facebook.com/help/instagram/788388387972460"],
    },
    "youtube": {
        "language_shape": "promise-matched, explanatory and retention-sustaining",
        "opening": "fulfil the title and thumbnail expectation immediately",
        "content_bias": ["short", "demonstration_video", "evidence_led_explainer"],
        "quality_signals": ["appeal", "first_seconds_retention", "watch_time", "satisfaction", "returning_viewer"],
        "anti_patterns": ["title_content_mismatch", "universal_length_rule", "logo_intro_before_value"],
        "official_sources": [
            "https://support.google.com/youtube/answer/16559650?hl=en",
            "https://support.google.com/youtube/answer/9314416?hl=en",
        ],
    },
    "linkedin": {
        "language_shape": "operator-specific, defensible and useful inside a real work decision",
        "opening": "state a sharp operating contradiction before brand context",
        "content_bias": ["text_post", "document_or_carousel", "expert_video"],
        "quality_signals": ["qualified_dwell", "saves", "expert_comments", "qualified_conversation"],
        "anti_patterns": ["generic_thought_leadership", "engagement_bait", "manufactured_vulnerability"],
        "official_sources": [
            "https://business.linkedin.com/content/dam/me/business/en-us/marketing-solutions/resources/pdfs/5-key-principles-for-marketing-on-linkedIn-95273.pdf"
        ],
    },
    "reddit": {
        "language_shape": "community-contextual, candid and useful before any brand ask",
        "opening": "enter through the unresolved community problem and local norms",
        "content_bias": ["discussion", "useful_resource", "evidence_or_method_breakdown"],
        "quality_signals": ["substantive_replies", "moderator_acceptance", "voluntary_relay", "qualified_follow_up"],
        "anti_patterns": ["brand_billboard", "cross_subreddit_copy_paste", "comment_extraction"],
        "official_sources": [
            "https://www.business.reddit.com/blog/how-to-reddit-strategies-from-cannes-marketers"
        ],
    },
    "x": {
        "language_shape": "compressed, timely, conversational and point-of-view led",
        "opening": "state one falsifiable observation or useful contradiction without a thread preamble",
        "content_bias": ["single_post", "bounded_thread", "reply_with_evidence"],
        "quality_signals": ["qualified_replies", "bookmarks", "reposts_with_comment", "qualified_click"],
        "anti_patterns": ["empty_hot_take", "thread_padding", "contextless_newsjack"],
        "official_sources": [],
    },
}

_GENERIC_DISTRIBUTION_OVERLAY = {
    "language_shape": "native to the owner-declared platform and one audience decision",
    "opening": "open with context-specific value before brand explanation",
    "content_bias": ["platform_native_primary_format"],
    "quality_signals": ["qualified_attention", "save_or_relay", "qualified_action"],
    "anti_patterns": ["cross_platform_copy_paste", "generic_brand_voice"],
    "official_sources": [],
}

_STYLE_SYSTEMS: dict[str, dict[str, Any]] = {
    "documentary_proof": {"mode": "traditional_depth", "mechanism": "reconstruct the evidence and its limit as a compact documentary"},
    "expert_teardown": {"mode": "traditional_depth", "mechanism": "diagnose the category's hidden failure mode with practitioner specificity"},
    "operator_memo": {"mode": "traditional_depth", "mechanism": "show the decision tree an accountable operator would actually use"},
    "deadpan_truth": {"mode": "humor", "mechanism": "use restrained irony to expose a familiar category absurdity without mocking the audience"},
    "category_inversion": {"mode": "creative_inversion", "mechanism": "reverse the category's default sequence and let proof arrive before promise"},
    "participatory_ritual": {"mode": "creative_participation", "mechanism": "give the audience a repeatable action that creates useful voluntary evidence"},
    "founder_candor": {"mode": "human_voice", "mechanism": "name what the team still does not know and recruit a precise falsification"},
    "useful_tool": {"mode": "utility", "mechanism": "turn expertise into a reusable calculator, checklist, prompt or diagnostic"},
    "visual_metaphor": {"mode": "art_direction", "mechanism": "make the decision tension visible through one ownable visual rule"},
    "case_reconstruction": {"mode": "investigation", "mechanism": "rebuild a growth case from aggregate signals while separating observation from inference"},
}

_SURFACE_DEMONSTRATION: dict[str, dict[str, str]] = {
    "web_app": {
        "proof_object": "one visible workflow from input to reviewed outcome",
        "anti_demo": "feature-tour montage without a decision or result",
    },
    "mobile_app": {
        "proof_object": "one first-session use moment on a real device-sized flow",
        "anti_demo": "store-badge montage without core experience",
    },
    "web_agent": {
        "proof_object": "one delegated job with plan, tool boundary, evidence and human checkpoint visible",
        "anti_demo": "chat transcript that hides execution, uncertainty or control",
    },
    "desktop_app": {
        "proof_object": "one native multi-step task with latency and control surfaces visible",
        "anti_demo": "static interface tour without task completion",
    },
    "api": {
        "proof_object": "one reproducible request, response, failure boundary and integration consequence",
        "anti_demo": "benchmark claim without reproducible conditions",
    },
    "physical_product": {
        "proof_object": "one real use moment showing material behavior and limitation",
        "anti_demo": "beauty shot without use evidence",
    },
    "service": {
        "proof_object": "one before-during-after decision artifact with owner-visible method",
        "anti_demo": "testimonial-led promise without inspectable delivery",
    },
    "hybrid": {
        "proof_object": "one connected digital-to-physical or software-to-service journey with handoffs visible",
        "anti_demo": "disconnected feature montage across surfaces",
    },
}

_OSS_SHADOW_ADAPTERS = [
    {
        "id": "dspy",
        "repo": "stanfordnlp/dspy",
        "revision": "c69136b29aca4c00ca6da7667f7b80783188980e",
        "license": "MIT",
        "role": "frozen-split strategy and copy program optimization shadow",
    },
    {
        "id": "river",
        "repo": "online-ml/river",
        "revision": "f5a1db99765b8660d86a3f424acc68409d8f3e45",
        "license": "BSD-3-Clause",
        "role": "online drift detection and progressive validation shadow",
    },
    {
        "id": "ruptures",
        "repo": "deepcharles/ruptures",
        "revision": "ee1c8ff8a548d54c641b2bb471562165931f31c7",
        "license": "BSD-2-Clause",
        "role": "offline change-point and regime-boundary shadow",
    },
    {
        "id": "statsforecast",
        "repo": "Nixtla/statsforecast",
        "revision": "78ea6d4261d9a4d04d1f286ffa2c82afdf8665e5",
        "license": "Apache-2.0",
        "role": "seasonal naive and statistical forecast benchmark shadow",
    },
    {
        "id": "posthog",
        "repo": "PostHog/posthog",
        "revision": "726b71430eaf3ce6db738078624efb29f86645e5",
        "license": "component_audit_required",
        "role": "identity-safe event and content cohort adapter shadow",
    },
    {
        "id": "growthbook",
        "repo": "growthbook/growthbook",
        "revision": "4ad7fe7c5c587ff979a9408d566013d32a2a4fb2",
        "license": "open_core_component_audit_required",
        "role": "preregistered holdout and experiment decision adapter shadow",
    },
    {
        "id": "vowpal_wabbit",
        "repo": "VowpalWabbit/vowpal_wabbit",
        "revision": "5801d8203d646b989180665753744ccc72d24065",
        "license": "component_audit_required",
        "role": "capped contextual-bandit offline replay shadow",
    },
    {
        "id": "causalml",
        "repo": "uber/causalml",
        "revision": "18c92dc35e27c65605227c3fddc1648877027ce0",
        "license": "component_audit_required",
        "role": "heterogeneous treatment-effect and uplift shadow",
    },
]

_SKILL_PATTERN_REFERENCES = [
    {
        "id": "anthropic_skills",
        "repo": "anthropics/skills",
        "revision": "b29e7cf65e5cb78a5ac33d582270551bc74a14eb",
        "use": "progressive disclosure and scoped skill-package reference",
    },
    {
        "id": "openai_skills",
        "repo": "openai/skills",
        "revision": "49f948faa9258a0c61caceaf225e179651397431",
        "use": "acceptance-fixture and reusable skill-spec reference",
    },
]


def _distribution_floor(request: CampaignStrategyInput) -> str:
    order = {"none": 0, "emerging": 1, "established": 2, "strong": 3}
    values = (
        request.brand_reach.value,
        request.owned_audience_strength.value,
        request.community_access.value,
        request.partner_access.value,
    )
    return min(values, key=order.__getitem__)


def _style_portfolio(request: CampaignStrategyInput) -> list[dict[str, Any]]:
    if request.audience.business_model is BusinessModel.B2B:
        preferred = ["expert_teardown", "operator_memo", "useful_tool", "case_reconstruction", "founder_candor", "category_inversion"]
    else:
        preferred = ["participatory_ritual", "visual_metaphor", "deadpan_truth", "category_inversion", "documentary_proof", "useful_tool"]
    if request.lifecycle is LifecycleStage.PRE_PMF:
        preferred = ["founder_candor", "useful_tool", *preferred]
    elif request.lifecycle is LifecycleStage.MATURE:
        preferred = ["category_inversion", "case_reconstruction", *preferred]
    if request.industry_risk is IndustryRisk.HIGH_REGULATION:
        preferred = [item for item in preferred if item != "deadpan_truth"]
        preferred = ["documentary_proof", "expert_teardown", "operator_memo", *preferred]
    deduped = list(dict.fromkeys(preferred))
    production_capacity = {
        ContentCapacity.LEAN: 2,
        ContentCapacity.STANDARD: 3,
        ContentCapacity.STUDIO: 4,
    }[request.content_capacity]
    exploration_count = max(3, production_capacity)
    return [
        {"style_id": style_id, **_STYLE_SYSTEMS[style_id]}
        for style_id in deduped[:exploration_count]
    ]


def compile_creative_alpha_plan(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    signal_intelligence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    signals = signal_intelligence if isinstance(signal_intelligence, Mapping) else {}
    radar = signals.get("growth_case_radar")
    if isinstance(radar, Mapping) and radar.get("status") != "not_supplied":
        _validate_radar(radar)
        radar_status = (
            "growth_case_hypotheses_ready"
            if radar.get("eligible_case_count", 0) > 0
            else "insufficient_comparable_growth_cases"
        )
        research_candidates = [
            {
                "cell": {
                    "category": cell["category"],
                    "platform": cell["platform"],
                    "market": cell["market"],
                },
                "case_id": candidate["case_id"],
                "research_priority_score": candidate["research_priority_score"],
                "source_uri_sha256": candidate["source_uri_sha256"],
            }
            for cell in radar.get("cells", [])
            if cell.get("status") == "hypothesis_ranking_ready"
            for candidate in cell.get("ranked_candidates", [])[:3]
        ]
    else:
        radar_status = "growth_case_research_required"
        research_candidates = []

    abstract_patterns = [
        str(item.get("feature"))
        for item in signals.get("top_abstract_format_patterns", [])[:5]
        if isinstance(item, Mapping) and item.get("feature")
    ]
    platform_grammars = {
        channel.value: {
            "channel": channel.value,
            **_PLATFORM_GRAMMARS.get(channel.value, _GENERIC_GRAMMAR),
            "source_review_required_before_release": True,
        }
        for channel in (strategy.primary_channel, strategy.secondary_channel)
    }
    context = {
        "industry": request.industry,
        "product_category": request.product_category,
        "product_surface": request.product_surface.value,
        "distribution_platform": request.distribution_platform,
        "business_model": request.audience.business_model.value,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "industry_risk": request.industry_risk.value,
        "company_scale": request.company_scale.value,
        "distribution_operating_floor": _distribution_floor(request),
        "content_capacity": request.content_capacity.value,
        "sales_motion": request.sales_motion.value,
        "audience_id": request.audience.audience_id,
        "audience_role": request.audience_role,
        "primary_channel": strategy.primary_channel.value,
        "secondary_channel": strategy.secondary_channel.value,
        "schedule_timezone": request.schedule_timezone,
    }
    styles = _style_portfolio(request)
    platform_key = request.distribution_platform.strip().casefold()
    distribution_overlay = {
        "platform": request.distribution_platform,
        **_DISTRIBUTION_PLATFORM_OVERLAYS.get(
            platform_key, _GENERIC_DISTRIBUTION_OVERLAY
        ),
        "source_review_required_before_release": True,
    }
    production_style_capacity = {
        ContentCapacity.LEAN: 2,
        ContentCapacity.STANDARD: 3,
        ContentCapacity.STUDIO: 4,
    }[request.content_capacity]
    market_language_contract = compile_market_language_contract(request)
    team_capability_contract = compile_gtm_team_capability_contract(request)
    payload: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "context": context,
        "growth_case_radar_status": radar_status,
        "growth_case_research_candidates": research_candidates,
        "abstract_signal_patterns": abstract_patterns,
        "market_operating_contract": {
            "business_model": request.audience.business_model.value,
            "owner_declared_industry": request.industry,
            "owner_declared_product_category": request.product_category,
            "product_surface": request.product_surface.value,
            "reference_family_registry": (
                list(B2B_CATEGORY_IDS)
                if request.audience.business_model is BusinessModel.B2B
                else list(B2C_CATEGORY_IDS)
            ),
            "reference_family_is_automatic_classification": False,
            "mobile_category_primary_sources": (
                [
                    "https://developer.apple.com/app-store/categories/",
                    "https://support.google.com/googleplay/android-developer/answer/9859673?hl=en-EN",
                ]
                if request.product_surface.value == "mobile_app"
                else []
            ),
            "category_must_match_core_experience": True,
        },
        "audience_decision_unit_contract": (
            {
                "mode": "b2b_buying_system",
                "primary_named_audience": request.audience.name,
                "primary_role": request.audience_role,
                "roles_to_model": [
                    "economic_buyer",
                    "functional_owner",
                    "technical_evaluator",
                    "internal_champion",
                    "end_user",
                    "risk_procurement_or_compliance",
                ],
                "single_asset_primary_role_count": 1,
                "committee_average_voice_forbidden": True,
                "language_jobs": [
                    "economic consequence",
                    "operator mechanism",
                    "technical inspectability",
                    "risk boundary",
                    "champion relay utility",
                ],
            }
            if request.audience.business_model is BusinessModel.B2B
            else {
                "mode": "b2c_use_moment_system",
                "primary_named_audience": request.audience.name,
                "primary_role": request.audience_role,
                "roles_to_model": [
                    "new_user",
                    "active_user",
                    "switcher",
                    "advocate",
                    "payer_or_household_influencer",
                ],
                "single_asset_primary_role_count": 1,
                "mass_market_average_voice_forbidden": True,
                "language_jobs": [
                    "recognizable use moment",
                    "identity relevance",
                    "friction removal",
                    "trust and proof",
                    "voluntary relay value",
                ],
            }
        ),
        "market_language_contract": market_language_contract,
        "gtm_team_capability_contract": team_capability_contract,
        "surface_demonstration_contract": {
            "surface": request.product_surface.value,
            **_SURFACE_DEMONSTRATION[request.product_surface.value],
        },
        "research_universe": {
            "required_windows_days": list(_WINDOWS),
            "minimum_comparable_cases_per_category_platform_market": _MINIMUM_CELL_CASES,
            "query_lattice": [
                "category + problem verb + audience role",
                "category + alternative or switch + buying trigger",
                "category + use moment + objection",
                "category + review or comparison + market",
                "category + fastest growing or emerging + platform + 90 days",
                "category + creator or community + platform + 180 days",
            ],
            "collection_contract": "authorized aggregate metrics and abstract format labels only",
            "raw_source_copy_or_media_retained": False,
        },
        "quant_research_contract": {
            "point_in_time_cutoff_required": True,
            "future_leakage_forbidden": True,
            "comparable_cell": ["category", "platform", "market"],
            "robust_scaler": "median_and_MAD_clipped_to_plus_or_minus_3",
            "sample_shrinkage": "n/(n+1000)",
            "factor_weights": dict(_FACTOR_WEIGHTS),
            "walk_forward_windows_days": [7, 28, 90, 180],
            "regime_states": ["emerging", "accelerating", "crowded", "decaying", "insufficient_data"],
            "score_is_forecast_or_causal_claim": False,
        },
        "platform_grammars": platform_grammars,
        "distribution_platform_overlay": distribution_overlay,
        "style_portfolio": styles,
        "creative_candidate_contract": {
            "challenger_candidate_count": 3,
            "exploration_style_count": len(styles),
            "production_style_capacity": production_style_capacity,
            "one_distinct_style_system_per_challenger": True,
            "same_proof_spine_across_candidates": True,
            "channel_copy_must_be_rewritten_not_reformatted": True,
            "minimum_context_dimensions_visible": 5,
            "source_identity_or_distinctive_expression_imitation_forbidden": True,
            "senior_editor_blind_review_required": True,
        },
        "generative_execution_kernel_contract": {
            "schema": "ProofLaunchGTMGenerativeExecutionKernelV1",
            "creative_genome_axis_count": len(GENERATIVE_AXES),
            "creative_genome_axis_ids": list(GENERATIVE_AXES),
            "blueprint_design_space": math.prod(len(options) for options in GENERATIVE_AXES.values()),
            "default_nonrepeating_blueprints_per_run": 24,
            "minimum_pairwise_axis_distance": 3,
            "capability_lane_count": len(CAPABILITY_LANES),
            "prior_genome_exclusion_required": True,
            "same_formula_across_industries_forbidden": True,
            "generated_content_count": 0,
            "automatic_winner_selection": False,
        },
        "rebalance_contract": {
            "detect_weekly": "change point, concept drift, fatigue and saturation candidate",
            "validate_28_day": "holdout against frozen control and qualified attention",
            "reassess_90_180_day": "case persistence, seasonality and transferability",
            "single_variable_revision_first": True,
            "automatic_strategy_mutation_executed": False,
        },
        "organic_distribution_contract": {
            "definition": "qualified organic attention that produces attributable useful participation or acquisition",
            "paid_impressions_count_as_organic_breakout": False,
            "primary_channel": strategy.primary_channel.value,
            "secondary_channel": strategy.secondary_channel.value,
            "content_form_selected_from_platform_grammar_and_observed_audience_behavior": True,
            "vanity_view_only_promotion_forbidden": True,
            "quality_signals": [
                "qualified_attention",
                "save_or_relay",
                "substantive_participation",
                "qualified_visit_or_conversation",
                "verified_downstream_action",
            ],
        },
        "publication_timing_contract": {
            "timezone": request.schedule_timezone,
            "universal_best_time_assumed": False,
            "audience_activity_input_required_when_available": True,
            "initial_two_slot_holdout_required": True,
            "compare_within_same_platform_format_and_audience_segment": True,
            "reestimate_window_days": 28,
            "official_sources": [
                "https://support.google.com/youtube/answer/9314416?hl=en",
                "https://www.facebook.com/help/instagram/788388387972460",
            ],
            "automatic_publish_enabled": False,
        },
        "originality_transfer_contract": {
            "allowed_transfer_units": [
                "audience tension",
                "proof sequence",
                "format mechanic",
                "participation mechanic",
                "distribution bridge",
                "measurement hypothesis",
            ],
            "forbidden_transfer_units": [
                "source wording",
                "distinctive character or mascot",
                "shot-for-shot sequence",
                "signature visual trade dress",
                "creator identity or voice imitation",
            ],
            "minimum_novel_recombination_dimensions": 3,
            "source_identity_hidden_from_generator": True,
            "semantic_and_expression_overlap_review_required": True,
        },
        "self_evolution_contract": {
            "unit": "next_run_policy_candidate_only",
            "feedback_horizons_days": [7, 28, 90, 180],
            "required_outcomes": [
                "qualified_attention",
                "brand_distinctiveness",
                "downstream_action",
                "negative_feedback_or_hide",
                "verified_conversion_or_revenue_when_available",
            ],
            "methods": [
                "time_decay",
                "change_point_reset",
                "concept_drift_detection",
                "holdout_or_counterfactual",
                "off_policy_replay_before_bandit_candidate",
            ],
            "current_run_mutation_allowed": False,
            "automatic_online_learning_enabled": False,
            "named_human_promotion_required": True,
        },
        "oss_shadow_adapters": list(_OSS_SHADOW_ADAPTERS),
        "skill_pattern_references": list(_SKILL_PATTERN_REFERENCES),
        "automatic_skill_script_execution_enabled": False,
        "automatic_install_or_adapter_promotion": False,
        "external_action_count": 0,
        "human_release_required": True,
        "truth_boundary": (
            "This plan formalizes point-in-time research, platform-native creative briefs and "
            "bounded iteration. It does not prove a brand is fastest-growing, predict a breakout, "
            "establish senior-agency blind-review preference, copy source expression, publish "
            "content or attribute revenue."
        ),
    }
    payload["content_sha256"] = _digest(payload)
    verify_creative_alpha_plan(payload)
    return payload


def verify_creative_alpha_plan(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != PLAN_SCHEMA:
        raise CreativeAlphaError("creative-alpha plan schema is invalid")
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if not isinstance(supplied, str) or supplied != _digest(unsigned):
        raise CreativeAlphaError("creative-alpha plan digest is invalid")
    context = payload.get("context")
    if not isinstance(context, Mapping) or len(context) < 10:
        raise CreativeAlphaError("creative-alpha context is incomplete")
    for field in (
        "industry",
        "product_category",
        "product_surface",
        "distribution_platform",
        "schedule_timezone",
        "audience_role",
    ):
        if not isinstance(context.get(field), str) or not context.get(field):
            raise CreativeAlphaError(f"creative-alpha {field} context is invalid")
    surface = context.get("product_surface")
    surface_contract = payload.get("surface_demonstration_contract")
    if surface not in _SURFACE_DEMONSTRATION or not isinstance(surface_contract, Mapping):
        raise CreativeAlphaError("creative-alpha product surface is unsupported")
    if surface_contract.get("surface") != surface:
        raise CreativeAlphaError("creative-alpha surface contract drifted")
    platform_overlay = payload.get("distribution_platform_overlay")
    if (
        not isinstance(platform_overlay, Mapping)
        or platform_overlay.get("platform") != context.get("distribution_platform")
        or platform_overlay.get("source_review_required_before_release") is not True
        or not platform_overlay.get("language_shape")
        or not platform_overlay.get("content_bias")
    ):
        raise CreativeAlphaError("creative-alpha distribution platform overlay drifted")
    market_contract = payload.get("market_operating_contract")
    audience_contract = payload.get("audience_decision_unit_contract")
    if not isinstance(market_contract, Mapping) or not isinstance(audience_contract, Mapping):
        raise CreativeAlphaError("creative-alpha market or audience contract is missing")
    expected_audience_mode = (
        "b2b_buying_system"
        if context.get("business_model") == "b2b"
        else "b2c_use_moment_system"
    )
    if audience_contract.get("mode") != expected_audience_mode:
        raise CreativeAlphaError("creative-alpha audience decision-unit mode drifted")
    if audience_contract.get("primary_role") != context.get("audience_role"):
        raise CreativeAlphaError("creative-alpha primary audience role drifted")
    language_contract = payload.get("market_language_contract")
    if not isinstance(language_contract, Mapping):
        raise CreativeAlphaError("creative-alpha market-language contract is missing")
    verify_market_language_contract(language_contract)
    language_context = language_contract.get("context", {})
    for plan_field, language_field in (
        ("business_model", "business_model"),
        ("product_category", "owner_declared_product_category"),
        ("product_surface", "product_surface"),
        ("distribution_platform", "distribution_platform"),
        ("audience_role", "owner_declared_audience_role"),
        ("lifecycle", "lifecycle"),
        ("budget", "budget"),
    ):
        if language_context.get(language_field) != context.get(plan_field):
            raise CreativeAlphaError(
                f"creative-alpha market-language {plan_field} binding drifted"
            )
    team_contract = payload.get("gtm_team_capability_contract")
    if not isinstance(team_contract, Mapping):
        raise CreativeAlphaError("creative-alpha GTM team capability contract is missing")
    verify_gtm_team_capability_contract(team_contract)
    team_context = team_contract.get("context", {})
    for plan_field, team_field in (
        ("business_model", "business_model"),
        ("product_category", "product_category"),
        ("product_surface", "product_surface"),
        ("distribution_platform", "distribution_platform"),
        ("audience_role", "primary_audience_role"),
        ("lifecycle", "lifecycle"),
        ("budget", "budget"),
    ):
        if team_context.get(team_field) != context.get(plan_field):
            raise CreativeAlphaError(
                f"creative-alpha GTM team {plan_field} binding drifted"
            )
    styles = payload.get("style_portfolio")
    if not isinstance(styles, list) or not 3 <= len(styles) <= 4:
        raise CreativeAlphaError("creative-alpha style portfolio is invalid")
    if len({row.get("style_id") for row in styles if isinstance(row, Mapping)}) != len(styles):
        raise CreativeAlphaError("creative-alpha style systems are not distinct")
    if context.get("industry_risk") == "high_regulation" and any(
        row.get("mode") == "humor" for row in styles if isinstance(row, Mapping)
    ):
        raise CreativeAlphaError("regulated creative-alpha plan enabled humor")
    candidate_contract = payload.get("creative_candidate_contract")
    if not isinstance(candidate_contract, Mapping):
        raise CreativeAlphaError("creative-alpha candidate contract is missing")
    if candidate_contract.get("challenger_candidate_count") != 3:
        raise CreativeAlphaError("creative-alpha challenger count drifted")
    if candidate_contract.get("exploration_style_count") != len(styles):
        raise CreativeAlphaError("creative-alpha exploration style count drifted")
    production_capacity = candidate_contract.get("production_style_capacity")
    if production_capacity not in {2, 3, 4} or production_capacity > len(styles):
        raise CreativeAlphaError("creative-alpha production style capacity is invalid")
    if candidate_contract.get("one_distinct_style_system_per_challenger") is not True:
        raise CreativeAlphaError("creative-alpha distinct challenger style gate was disabled")
    adapters = payload.get("oss_shadow_adapters")
    if not isinstance(adapters, list) or {row.get("id") for row in adapters} != {
        "dspy",
        "river",
        "ruptures",
        "statsforecast",
        "posthog",
        "growthbook",
        "vowpal_wabbit",
        "causalml",
    }:
        raise CreativeAlphaError("creative-alpha OSS adapter coverage drifted")
    if any(not _REVISION.fullmatch(str(row.get("revision", ""))) for row in adapters):
        raise CreativeAlphaError("creative-alpha OSS adapter is not revision-pinned")
    if payload.get("automatic_install_or_adapter_promotion") is not False:
        raise CreativeAlphaError("creative-alpha plan enabled automatic adapter promotion")
    skill_refs = payload.get("skill_pattern_references")
    if not isinstance(skill_refs, list) or {row.get("id") for row in skill_refs} != {
        "anthropic_skills",
        "openai_skills",
    }:
        raise CreativeAlphaError("creative-alpha skill reference coverage drifted")
    if any(not _REVISION.fullmatch(str(row.get("revision", ""))) for row in skill_refs):
        raise CreativeAlphaError("creative-alpha skill reference is not revision-pinned")
    if payload.get("automatic_skill_script_execution_enabled") is not False:
        raise CreativeAlphaError("creative-alpha enabled automatic skill script execution")
    timing = payload.get("publication_timing_contract")
    evolution = payload.get("self_evolution_contract")
    originality = payload.get("originality_transfer_contract")
    if (
        not isinstance(timing, Mapping)
        or timing.get("timezone") != context.get("schedule_timezone")
        or timing.get("universal_best_time_assumed") is not False
        or timing.get("automatic_publish_enabled") is not False
        or not isinstance(evolution, Mapping)
        or evolution.get("current_run_mutation_allowed") is not False
        or evolution.get("automatic_online_learning_enabled") is not False
        or evolution.get("named_human_promotion_required") is not True
        or not isinstance(originality, Mapping)
        or originality.get("minimum_novel_recombination_dimensions") != 3
        or originality.get("source_identity_hidden_from_generator") is not True
    ):
        raise CreativeAlphaError("creative-alpha timing, originality or evolution gate drifted")
    if payload.get("external_action_count") != 0 or payload.get("human_release_required") is not True:
        raise CreativeAlphaError("creative-alpha plan escaped the human release boundary")
