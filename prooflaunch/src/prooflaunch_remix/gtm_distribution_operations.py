from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .gtm_channel_portfolio import verify_channel_portfolio
from .gtm_content_calendar import verify_content_calendar
from .gtm_strategy import CampaignStrategyInput, GTMStrategy


SCHEMA = "ProofLaunchGTMDistributionOperationsV1"


class DistributionOperationsError(ValueError):
    """Distribution operations escaped the bounded human-release contract."""


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def compile_distribution_operations(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    *,
    channel_portfolio: Mapping[str, object],
    content_calendar: Mapping[str, object],
) -> dict[str, Any]:
    verify_channel_portfolio(channel_portfolio)
    verify_content_calendar(content_calendar)
    focus = channel_portfolio.get("focus_channels")
    if not isinstance(focus, list) or len(focus) != 2:
        raise DistributionOperationsError("one primary and one supporting focus channel are required")
    if focus != [strategy.primary_channel.value, strategy.secondary_channel.value]:
        raise DistributionOperationsError("distribution focus drifted from strategy")
    slots = content_calendar.get("slots")
    if not isinstance(slots, list) or len(slots) != 7:
        raise DistributionOperationsError("seven calendar slots are required")

    flight: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, Mapping):
            raise DistributionOperationsError("calendar slot is invalid")
        channel = str(slot["channel"])
        flight.append(
            {
                "day": slot["strategy_day"],
                "slot_id": slot["slot_id"],
                "channel": channel,
                "role": "primary" if channel == strategy.primary_channel.value else "supporting",
                "objective": slot["theme"],
                "content_type": "evidence_bound_native_draft",
                "interaction_action": (
                    "collect the strongest qualified objection and draft a source-bound response for human approval"
                ),
                "reuse_logic": (
                    "reuse only the evidence module and learned question; rewrite the expression for the next channel"
                ),
                "stop_condition": (
                    "stop if claim validity, rights, identity, platform policy or the pre-registered safety threshold fails"
                ),
                "intended_learning": slot["intended_learning"],
                "scheduled_local": slot["scheduled_local"],
                "release_mode": "human_review_then_manual_activation",
                "external_activation_executed": False,
            }
        )

    timing_hypotheses = [
        {
            "slot_id": slot["slot_id"],
            "channel": slot["channel"],
            "scheduled_local": slot["scheduled_local"],
            "factors": {
                "declared_timezone": request.schedule_timezone,
                "regional_market": "owner market is carried by the launch request and must be human-confirmed",
                "work_context": request.audience.buying_context,
                "platform_behavior": "channel-specific deterministic starting window",
                "account_history": "not_supplied",
            },
            "hypothesis_only": True,
            "universal_best_time_claimed": False,
            "account_history_required_before_optimization": True,
        }
        for slot in slots
    ]

    comment_operator = {
        "input_required": "one public or authorized comment plus its URL, time and platform policy context",
        "reply_blueprints": [
            {
                "mode": "clarify",
                "structure": "acknowledge the exact question → answer only what evidence supports → link the source only if useful",
            },
            {
                "mode": "advance",
                "structure": "surface the hidden decision trade-off → add one new source-bound detail → invite a specific counterexample",
            },
            {
                "mode": "correct",
                "structure": "state the correction calmly → show the evidence boundary → preserve the person's dignity",
            },
        ],
        "prohibited": ["persona impersonation", "argument bait", "fake consensus", "automated mass replies", "unapproved claim expansion"],
        "human_publish_required": True,
        "automatic_reply_enabled": False,
    }
    community_entry = {
        "sequence": [
            "read rules and recent norms",
            "contribute a complete standalone answer",
            "disclose relevant identity or affiliation",
            "include a link only when the answer remains useful without it",
            "stop if moderators or community members signal mismatch",
        ],
        "link_first_entry_allowed": False,
        "identity_disclosure_required": True,
        "automatic_posting_enabled": False,
    }
    partner_growth = {
        "ranking_dimensions": ["audience_overlap", "trust_transfer", "joint_asset_value", "operational_fit", "rights_and_reputation_risk"],
        "follower_count_primary_dimension": False,
        "minimum_joint_asset": "one co-owned useful artifact with explicit contribution, rights, measurement and exit terms",
        "named_human_partner_approval_required": True,
        "automatic_outreach_enabled": False,
    }
    experiment_cells = [
        {"cell_id": "control", "changed_variable": None, "value": "frozen approved control"},
        {"cell_id": "hook-variant", "changed_variable": "hook", "value": "one materially different hook family"},
        {"cell_id": "proof-variant", "changed_variable": "proof", "value": "one different approved proof ordering; claim text unchanged"},
        {"cell_id": "format-variant", "changed_variable": "format", "value": "one platform-native format change"},
        {"cell_id": "cta-variant", "changed_variable": "cta", "value": "one different qualified next action"},
        {"cell_id": "time-variant", "changed_variable": "publish_time", "value": "one pre-registered local-time change"},
    ]
    core: dict[str, Any] = {
        "schema": SCHEMA,
        "strategy_id": strategy.strategy_id,
        "campaign_id": request.campaign_id,
        "channel_portfolio_sha256": channel_portfolio["content_sha256"],
        "content_calendar_sha256": content_calendar["content_sha256"],
        "launch_focus": {
            "primary_platform": strategy.primary_channel.value,
            "supporting_platforms": [strategy.secondary_channel.value],
            "scheduled_platform_count": len(set(slot["channel"] for slot in slots)),
            "maximum_allowed_platform_count": 3,
            "cold_start_focus_gate_passed": len(set(slot["channel"] for slot in slots)) <= 3,
        },
        "timing_hypotheses": timing_hypotheses,
        "seven_day_flight": flight,
        "comment_operator": comment_operator,
        "community_entry_protocol": community_entry,
        "partner_growth_protocol": partner_growth,
        "single_variable_experiment_contract": {
            "control_is_frozen": True,
            "allowed_variables": ["hook", "proof", "format", "cta", "publish_time"],
            "cells": experiment_cells,
            "maximum_changed_variables_per_variant": 1,
            "causal_claim_allowed_before_qualified_result": False,
        },
        "external_activation_executed": False,
        "automatic_publish_enabled": False,
        "automatic_budget_allocation_enabled": False,
        "truth_boundary": (
            "This document is a reviewable distribution and experiment contract. Scheduled times are hypotheses, "
            "reply and partner outputs are blueprints, and no publication, outreach, lift or causal result is claimed."
        ),
    }
    core["content_sha256"] = _digest(core)
    return core


def verify_distribution_operations(payload: Mapping[str, object]) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if payload.get("schema") != SCHEMA or supplied != _digest(unsigned):
        raise DistributionOperationsError("distribution operations seal is invalid")
    focus = payload.get("launch_focus")
    if not isinstance(focus, Mapping) or focus.get("cold_start_focus_gate_passed") is not True:
        raise DistributionOperationsError("cold-start platform focus gate failed")
    flight = payload.get("seven_day_flight")
    if not isinstance(flight, list) or len(flight) != 7:
        raise DistributionOperationsError("distribution flight must contain seven days")
    if any(row.get("external_activation_executed") is not False for row in flight if isinstance(row, Mapping)):
        raise DistributionOperationsError("distribution flight claimed external activation")
    experiment = payload.get("single_variable_experiment_contract")
    if not isinstance(experiment, Mapping) or experiment.get("maximum_changed_variables_per_variant") != 1:
        raise DistributionOperationsError("single-variable experiment contract drifted")
    if payload.get("external_activation_executed") is not False or payload.get("automatic_publish_enabled") is not False:
        raise DistributionOperationsError("distribution operations enabled external action")
