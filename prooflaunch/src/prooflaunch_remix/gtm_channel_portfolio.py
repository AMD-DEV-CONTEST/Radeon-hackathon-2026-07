from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from .gtm_strategy import (
    BudgetTier,
    CampaignStrategyInput,
    Channel,
    GTMStrategy,
    score_channel_opportunities,
)


class ChannelPortfolioError(ValueError):
    """Raised when a channel portfolio violates its strategy or budget contract."""


class ActivationState(str, Enum):
    FOCUS = "focus"
    TEST = "test"
    OBSERVE = "observe"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class ChannelProfile:
    minimum_viable_asset: str
    measurement_metric: str
    organic_mechanic: str


_PROFILES: dict[Channel, ChannelProfile] = {
    Channel.COMMUNITY_LISTENING: ChannelProfile(
        "one moderated problem-language prompt",
        "qualified_problem_signal_rate",
        "turn recurring audience language into an evidence-led response backlog",
    ),
    Channel.CREATOR_COMMUNITY: ChannelProfile(
        "one rights-cleared creator collaboration brief",
        "qualified_creator_response_rate",
        "invite creators to challenge the proof instead of copying an existing execution",
    ),
    Channel.CUSTOMER_EVIDENCE: ChannelProfile(
        "one source-bound evidence card",
        "evidence_detail_view_rate",
        "make first-party proof independently inspectable and easy to reference",
    ),
    Channel.CUSTOMER_EMAIL: ChannelProfile(
        "one consented plain-text customer note",
        "qualified_reply_rate",
        "re-engage an owned audience with one verifiable decision question",
    ),
    Channel.FOUNDER_CONVERSATIONS: ChannelProfile(
        "one founder interview guide",
        "qualified_learning_per_conversation",
        "convert high-context conversations into objections and proof requirements",
    ),
    Channel.LINKEDIN_ORGANIC: ChannelProfile(
        "one evidence-led decision post",
        "qualified_profile_or_demo_action_rate",
        "earn professional distribution through a useful, source-bound point of view",
    ),
    Channel.OWNED_SOCIAL: ChannelProfile(
        "one evidence carousel or thread",
        "qualified_save_or_click_rate",
        "compound an owned narrative through reusable proof modules",
    ),
    Channel.PARTNER_COMMUNITIES: ChannelProfile(
        "one partner-ready peer discussion prompt",
        "qualified_partner_conversation_rate",
        "borrow trust only through explicit partner participation and source visibility",
    ),
    Channel.SEARCH_EDUCATION: ChannelProfile(
        "one answer-first evidence explainer",
        "qualified_search_action_rate",
        "compound demand by answering a durable decision question better than a sales page",
    ),
    Channel.SHORT_VIDEO_ORGANIC: ChannelProfile(
        "one vertical proof-before-promise script",
        "qualified_completion_or_click_rate",
        "create a participatory proof question that viewers can inspect and respond to",
    ),
    Channel.PAID_SEARCH: ChannelProfile(
        "one inactive search experiment draft",
        "qualified_action_per_spend_unit",
        "not organic; activate only after a controlled human budget decision",
    ),
    Channel.PAID_SOCIAL: ChannelProfile(
        "one inactive feed experiment draft",
        "qualified_action_per_spend_unit",
        "not organic; activate only after a controlled human budget decision",
    ),
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def compile_channel_portfolio(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    signal_platform_counts: Mapping[str, int] | None = None,
) -> dict[str, object]:
    """Rank every governed channel without turning breadth into automatic activation.

    The portfolio is deliberately a deterministic L2 decision surface. It makes
    channel focus inspectable, keeps zero-budget exclusions mechanical, and
    allocates only two bounded test slots beyond the primary/secondary focus.
    """

    if strategy.primary_channel is strategy.secondary_channel:
        raise ChannelPortfolioError("strategy focus channels must differ")
    if request.budget is BudgetTier.ZERO and (
        strategy.primary_channel.paid or strategy.secondary_channel.paid
    ):
        raise ChannelPortfolioError("zero-budget strategy cannot focus a paid channel")

    normalized_signal_counts = {
        str(platform).strip().casefold(): int(count)
        for platform, count in (signal_platform_counts or {}).items()
        if str(platform).strip() and type(count) is int and count > 0
    }
    opportunity_scores = score_channel_opportunities(
        request,
        signal_platform_counts=normalized_signal_counts,
    )
    scored: list[tuple[Channel, int, tuple[str, ...], bool]] = [
        (
            channel,
            opportunity_scores[channel][0],
            opportunity_scores[channel][1],
            request.budget is BudgetTier.ZERO and channel.paid,
        )
        for channel in Channel
    ]
    eligible_ranked = sorted(
        (item for item in scored if not item[3]),
        key=lambda item: (-item[1], item[0].value),
    )
    expected_focus = tuple(item[0] for item in eligible_ranked[:2])
    if expected_focus != (strategy.primary_channel, strategy.secondary_channel):
        raise ChannelPortfolioError(
            "strategy focus does not match the distribution opportunity frontier"
        )
    eligible_expansion = sorted(
        (
            item
            for item in scored
            if item[0] not in {strategy.primary_channel, strategy.secondary_channel}
            and not item[3]
        ),
        key=lambda item: (-item[1], item[0].value),
    )
    test_channels = {item[0] for item in eligible_expansion[:2]}
    focus_margin = max(0, eligible_ranked[1][1] - eligible_ranked[2][1])
    decision_confidence = (
        "high" if focus_margin >= 10 else "medium" if focus_margin >= 4 else "low"
    )

    ranked = sorted(scored, key=lambda item: (item[3], -item[1], item[0].value))
    entries: list[dict[str, object]] = []
    for rank, (channel, score, reasons, excluded) in enumerate(ranked, start=1):
        if excluded:
            activation = ActivationState.EXCLUDED
        elif channel in {strategy.primary_channel, strategy.secondary_channel}:
            activation = ActivationState.FOCUS
        elif channel in test_channels:
            activation = ActivationState.TEST
        else:
            activation = ActivationState.OBSERVE
        profile = _PROFILES[channel]
        entries.append(
            {
                "rank": rank,
                "channel": channel.value,
                "score": score,
                "activation_state": activation.value,
                "paid_channel": channel.paid,
                "reason_codes": list(reasons),
                "minimum_viable_asset": profile.minimum_viable_asset,
                "measurement_metric": profile.measurement_metric,
                "distribution_mechanic": profile.organic_mechanic,
                "release_mode": "human_review_then_manual_activation",
                "scheduled_in_current_seven_day_plan": channel in {
                    strategy.primary_channel,
                    strategy.secondary_channel,
                },
                "external_activation_executed": False,
                "automatic_budget_allocation_allowed": False,
            }
        )

    source_strategy_sha256 = _digest(asdict(strategy))
    opportunity_frontier = [
        {
            "rank": index,
            "channel": channel.value,
            "score": score,
            "activation_state": (
                ActivationState.FOCUS.value
                if channel in {strategy.primary_channel, strategy.secondary_channel}
                else ActivationState.TEST.value
                if channel in test_channels
                else ActivationState.OBSERVE.value
            ),
            "reason_codes": list(reasons),
        }
        for index, (channel, score, reasons, _excluded) in enumerate(
            eligible_ranked[:4], start=1
        )
    ]
    core: dict[str, object] = {
        "schema": "ProofLaunchChannelPortfolioV1",
        "algorithm": {
            "name": "distribution_advantage_frontier_v2",
            "autonomy_level": "L2_deterministic_workflow",
            "objective": (
                "maximize evidence-qualified learning per unit cost while preserving "
                "brand, rights, release and budget constraints"
            ),
            "features": [
                "business_lifecycle_prior",
                "company_scale",
                "brand_reach",
                "owned_audience_strength",
                "community_access",
                "partner_access",
                "content_capacity",
                "sales_motion",
                "authorized_platform_signal_fit",
                "budget_hard_constraint",
            ],
            "hard_constraints": [
                "zero_budget_excludes_every_paid_channel",
                "exactly_two_strategy_focus_channels",
                "at_most_two_unscheduled_test_channels",
                "all_activation_requires_named_human_review",
                "automatic_budget_allocation_is_disabled",
            ],
            "tie_breaker": "descending_score_then_channel_id",
        },
        "campaign_id": request.campaign_id,
        "strategy_id": strategy.strategy_id,
        "source_strategy_sha256": source_strategy_sha256,
        "business_model": request.audience.business_model.value,
        "lifecycle": request.lifecycle.value,
        "budget": request.budget.value,
        "decision_context": {
            "company_scale": request.company_scale.value,
            "brand_reach": request.brand_reach.value,
            "owned_audience_strength": request.owned_audience_strength.value,
            "community_access": request.community_access.value,
            "partner_access": request.partner_access.value,
            "content_capacity": request.content_capacity.value,
            "sales_motion": request.sales_motion.value,
        },
        "authorized_platform_signal_counts": dict(
            sorted(normalized_signal_counts.items())
        ),
        "authorized_platform_signal_input_used": bool(normalized_signal_counts),
        "focus_channels": [
            strategy.primary_channel.value,
            strategy.secondary_channel.value,
        ],
        "test_channels": [
            item["channel"]
            for item in entries
            if item["activation_state"] == ActivationState.TEST.value
        ],
        "opportunity_frontier": opportunity_frontier,
        "focus_margin_points": focus_margin,
        "decision_confidence": decision_confidence,
        "reallocation_policy": {
            "mode": "named_human_review_next_run_only",
            "prerequisites": [
                "preregistered_measurement_window_complete",
                "minimum_sample_met",
                "rights_and_policy_gates_pass",
                "named_human_decision_recorded",
            ],
            "automatic_reallocation_allowed": False,
            "current_run_strategy_mutation_allowed": False,
        },
        "portfolio": entries,
        "external_activation_executed": False,
        "automatic_strategy_mutation_executed": False,
        "automatic_reallocation_executed": False,
        "truth_boundary": (
            "The portfolio is a deterministic prioritization and experiment plan. "
            "It does not prove channel access, publication, reach, lift, virality or revenue."
        ),
    }
    core["content_sha256"] = _digest(core)
    verify_channel_portfolio(core)
    return core


def verify_channel_portfolio(portfolio: Mapping[str, object]) -> None:
    if portfolio.get("schema") != "ProofLaunchChannelPortfolioV1":
        raise ChannelPortfolioError("channel portfolio schema is unsupported")
    supplied = portfolio.get("content_sha256")
    payload = dict(portfolio)
    payload.pop("content_sha256", None)
    if supplied != _digest(payload):
        raise ChannelPortfolioError("channel portfolio digest mismatch")
    entries = portfolio.get("portfolio")
    if not isinstance(entries, list) or len(entries) != len(Channel):
        raise ChannelPortfolioError("channel portfolio must cover every governed channel")
    channels = [item.get("channel") for item in entries if isinstance(item, Mapping)]
    if len(channels) != len(entries) or set(channels) != {item.value for item in Channel}:
        raise ChannelPortfolioError("channel portfolio coverage is duplicated or incomplete")
    focus = [
        item for item in entries
        if isinstance(item, Mapping) and item.get("activation_state") == "focus"
    ]
    tests = [
        item for item in entries
        if isinstance(item, Mapping) and item.get("activation_state") == "test"
    ]
    if len(focus) != 2 or len(tests) > 2:
        raise ChannelPortfolioError("channel portfolio focus/test capacity is invalid")
    if portfolio.get("budget") == BudgetTier.ZERO.value and any(
        item.get("paid_channel") is True and item.get("activation_state") != "excluded"
        for item in entries
        if isinstance(item, Mapping)
    ):
        raise ChannelPortfolioError("zero-budget portfolio admitted a paid channel")
    if portfolio.get("external_activation_executed") is not False or portfolio.get(
        "automatic_strategy_mutation_executed"
    ) is not False:
        raise ChannelPortfolioError("portfolio cannot activate or mutate strategy")
    if portfolio.get("automatic_reallocation_executed") is not False:
        raise ChannelPortfolioError("portfolio cannot reallocate automatically")
    algorithm = portfolio.get("algorithm")
    if not isinstance(algorithm, Mapping) or algorithm.get("name") != (
        "distribution_advantage_frontier_v2"
    ):
        raise ChannelPortfolioError("channel portfolio algorithm is unsupported")
    decision_context = portfolio.get("decision_context")
    if not isinstance(decision_context, Mapping) or set(decision_context) != {
        "company_scale",
        "brand_reach",
        "owned_audience_strength",
        "community_access",
        "partner_access",
        "content_capacity",
        "sales_motion",
    }:
        raise ChannelPortfolioError("channel portfolio decision context is incomplete")
    frontier = portfolio.get("opportunity_frontier")
    if not isinstance(frontier, list) or len(frontier) != 4:
        raise ChannelPortfolioError("channel portfolio opportunity frontier is incomplete")
    if [item.get("rank") for item in frontier if isinstance(item, Mapping)] != [1, 2, 3, 4]:
        raise ChannelPortfolioError("channel portfolio opportunity frontier ranks are invalid")
    if portfolio.get("decision_confidence") not in {"low", "medium", "high"}:
        raise ChannelPortfolioError("channel portfolio decision confidence is invalid")
    margin = portfolio.get("focus_margin_points")
    if type(margin) is not int or margin < 0:
        raise ChannelPortfolioError("channel portfolio focus margin is invalid")
    reallocation = portfolio.get("reallocation_policy")
    if not isinstance(reallocation, Mapping) or (
        reallocation.get("automatic_reallocation_allowed") is not False
        or reallocation.get("current_run_strategy_mutation_allowed") is not False
    ):
        raise ChannelPortfolioError("channel portfolio reallocation boundary is invalid")
    if any(
        item.get("release_mode") != "human_review_then_manual_activation"
        or item.get("external_activation_executed") is not False
        or item.get("automatic_budget_allocation_allowed") is not False
        or not isinstance(item.get("reason_codes"), list)
        or not item.get("reason_codes")
        for item in entries
        if isinstance(item, Mapping)
    ):
        raise ChannelPortfolioError("channel item bypasses the human activation boundary")
