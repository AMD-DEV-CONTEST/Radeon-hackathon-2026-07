from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .gtm_channel_portfolio import verify_channel_portfolio
from .gtm_strategy import BudgetTier, CampaignStrategyInput, Channel, GTMStrategy


class ContentCalendarError(ValueError):
    """Raised when a calendar is not executable under its scheduling contract."""


_WINDOWS: dict[Channel, tuple[time, bool]] = {
    Channel.COMMUNITY_LISTENING: (time(12, 0), False),
    Channel.CREATOR_COMMUNITY: (time(13, 0), False),
    Channel.CUSTOMER_EVIDENCE: (time(10, 0), True),
    Channel.CUSTOMER_EMAIL: (time(10, 30), True),
    Channel.FOUNDER_CONVERSATIONS: (time(11, 0), True),
    Channel.LINKEDIN_ORGANIC: (time(9, 0), True),
    Channel.OWNED_SOCIAL: (time(17, 30), False),
    Channel.PARTNER_COMMUNITIES: (time(12, 30), True),
    Channel.SEARCH_EDUCATION: (time(8, 30), True),
    Channel.SHORT_VIDEO_ORGANIC: (time(18, 30), False),
    Channel.PAID_SEARCH: (time(9, 30), True),
    Channel.PAID_SOCIAL: (time(14, 0), False),
}


def _canonical(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, Mapping):
            return {str(key): normalize(value) for key, value in item.items()}
        if isinstance(item, (tuple, list)):
            return [normalize(value) for value in item]
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ContentCalendarError(f"{field_name} must be a bounded ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContentCalendarError(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContentCalendarError(f"{field_name} must include a timezone")
    return parsed


def _zone(value: str) -> ZoneInfo:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise ContentCalendarError("schedule_timezone must be a bounded IANA timezone")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ContentCalendarError("schedule_timezone is not an installed IANA timezone") from error


def _next_eligible_date(candidate: date, *, weekdays_only: bool) -> date:
    current = candidate
    while weekdays_only and current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def compile_content_calendar(
    request: CampaignStrategyInput,
    strategy: GTMStrategy,
    channel_portfolio: Mapping[str, object],
    *,
    source_draft_ids: Mapping[Channel, str],
    compiled_at: str,
    schedule_timezone: str,
) -> dict[str, object]:
    """Compile seven reviewable slots without performing external activation."""

    verify_channel_portfolio(channel_portfolio)
    compiled = _parse_timestamp(compiled_at, field_name="compiled_at")
    zone = _zone(schedule_timezone)
    focus = {strategy.primary_channel, strategy.secondary_channel}
    if set(source_draft_ids) != focus or any(
        not isinstance(value, str) or not value.strip() for value in source_draft_ids.values()
    ):
        raise ContentCalendarError("calendar requires one source draft for each focus channel")
    if request.budget is BudgetTier.ZERO and any(channel.paid for channel in focus):
        raise ContentCalendarError("zero-budget calendar cannot schedule a paid channel")

    local_compiled = compiled.astimezone(zone)
    cursor = local_compiled.date() + timedelta(days=2)
    slots: list[dict[str, object]] = []
    previous_utc: datetime | None = None
    for sequence, theme in enumerate(strategy.seven_day_content, start=1):
        if theme.channel not in focus:
            raise ContentCalendarError("strategy schedule escaped the focus portfolio")
        local_time, weekdays_only = _WINDOWS[theme.channel]
        scheduled_date = _next_eligible_date(cursor, weekdays_only=weekdays_only)
        scheduled_local = datetime.combine(scheduled_date, local_time, tzinfo=zone)
        scheduled_utc = scheduled_local.astimezone(timezone.utc)
        if previous_utc is not None and scheduled_utc - previous_utc < timedelta(hours=18):
            scheduled_date = _next_eligible_date(
                scheduled_date + timedelta(days=1),
                weekdays_only=weekdays_only,
            )
            scheduled_local = datetime.combine(scheduled_date, local_time, tzinfo=zone)
            scheduled_utc = scheduled_local.astimezone(timezone.utc)
        review_due = scheduled_utc - timedelta(hours=24)
        if review_due <= compiled.astimezone(timezone.utc):
            raise ContentCalendarError("calendar does not preserve the 24-hour review window")
        source_draft_id = source_draft_ids[theme.channel]
        slots.append(
            {
                "slot_id": f"slot-{sequence:02d}-{theme.channel.value}",
                "sequence": sequence,
                "strategy_day": theme.day,
                "channel": theme.channel.value,
                "theme": theme.theme,
                "intended_learning": theme.intended_learning,
                "source_draft_id": source_draft_id,
                "scheduled_local": scheduled_local.isoformat(),
                "scheduled_at_utc": scheduled_utc.isoformat().replace("+00:00", "Z"),
                "review_due_at_utc": review_due.isoformat().replace("+00:00", "Z"),
                "timezone": schedule_timezone,
                "weekdays_only": weekdays_only,
                "status": "draft_pending_human_review",
                "dependencies": [
                    f"claim:{strategy.proof_claim_id}",
                    f"draft:{source_draft_id}",
                    "approval:content_bound_human_release",
                ],
                "release_mode": "human_review_then_manual_activation",
                "external_activation_executed": False,
            }
        )
        previous_utc = scheduled_utc
        cursor = scheduled_date + timedelta(days=1)

    counts = Counter(slot["channel"] for slot in slots)
    core: dict[str, object] = {
        "schema": "ProofLaunchContentCalendarV1",
        "algorithm": {
            "name": "constraint_scheduled_human_release_calendar_v1",
            "autonomy_level": "L2_deterministic_workflow",
            "constraints": [
                "timezone_aware_absolute_instants",
                "minimum_24_hour_review_window",
                "minimum_18_hour_inter_slot_gap",
                "maximum_one_activation_per_local_date",
                "maximum_four_slots_per_channel_per_window",
                "professional_routes_skip_local_weekends",
                "zero_budget_excludes_paid_routes",
                "every_slot_requires_content_bound_human_release",
            ],
        },
        "campaign_id": request.campaign_id,
        "strategy_id": strategy.strategy_id,
        "channel_portfolio_sha256": channel_portfolio["content_sha256"],
        "compiled_at": compiled.isoformat(),
        "timezone": schedule_timezone,
        "slot_count": len(slots),
        "window_start_utc": slots[0]["scheduled_at_utc"],
        "window_end_utc": slots[-1]["scheduled_at_utc"],
        "channel_slot_counts": dict(sorted(counts.items())),
        "frequency_cap": {
            "maximum_slots_per_channel": 4,
            "maximum_slots_per_local_date": 1,
            "minimum_inter_slot_hours": 18,
        },
        "slots": slots,
        "approval_queue": [
            {
                "slot_id": slot["slot_id"],
                "decision": "pending",
                "review_due_at_utc": slot["review_due_at_utc"],
                "required_actor": "named_human_release_owner",
            }
            for slot in slots
        ],
        "external_activation_executed": False,
        "automatic_rescheduling_enabled": False,
        "automatic_publish_enabled": False,
        "truth_boundary": (
            "This calendar proves deterministic scheduling mechanics and approval boundaries. "
            "It does not prove a post was published, reached an audience or produced an outcome."
        ),
    }
    core["content_sha256"] = _digest(core)
    verify_content_calendar(core, compiled_at=compiled_at)
    return core


def verify_content_calendar(
    calendar: Mapping[str, object],
    *,
    compiled_at: str | None = None,
) -> None:
    if calendar.get("schema") != "ProofLaunchContentCalendarV1":
        raise ContentCalendarError("content calendar schema is unsupported")
    payload = dict(calendar)
    supplied = payload.pop("content_sha256", None)
    if supplied != _digest(payload):
        raise ContentCalendarError("content calendar digest mismatch")
    zone = _zone(str(calendar.get("timezone", "")))
    slots = calendar.get("slots")
    if not isinstance(slots, list) or len(slots) != 7:
        raise ContentCalendarError("content calendar requires exactly seven slots")
    if calendar.get("slot_count") != 7:
        raise ContentCalendarError("content calendar slot count is inconsistent")
    scheduled: list[datetime] = []
    local_dates: set[date] = set()
    counts: Counter[str] = Counter()
    compiled = _parse_timestamp(
        compiled_at or str(calendar.get("compiled_at")),
        field_name="compiled_at",
    ).astimezone(timezone.utc)
    for expected_sequence, slot in enumerate(slots, start=1):
        if not isinstance(slot, Mapping) or slot.get("sequence") != expected_sequence:
            raise ContentCalendarError("content calendar sequence is invalid")
        scheduled_utc = _parse_timestamp(
            str(slot.get("scheduled_at_utc")), field_name="scheduled_at_utc"
        ).astimezone(timezone.utc)
        local = _parse_timestamp(
            str(slot.get("scheduled_local")), field_name="scheduled_local"
        )
        if scheduled_utc.astimezone(zone).replace(fold=local.fold) != local:
            raise ContentCalendarError("scheduled local and UTC instants disagree")
        review_due = _parse_timestamp(
            str(slot.get("review_due_at_utc")), field_name="review_due_at_utc"
        ).astimezone(timezone.utc)
        if scheduled_utc - review_due != timedelta(hours=24) or review_due <= compiled:
            raise ContentCalendarError("slot review window is invalid")
        if local.date() in local_dates:
            raise ContentCalendarError("more than one slot occupies a local date")
        local_dates.add(local.date())
        if slot.get("status") != "draft_pending_human_review" or slot.get(
            "release_mode"
        ) != "human_review_then_manual_activation":
            raise ContentCalendarError("slot bypasses human review")
        if slot.get("external_activation_executed") is not False:
            raise ContentCalendarError("slot claims an external activation")
        dependencies = slot.get("dependencies")
        if not isinstance(dependencies, list) or len(dependencies) < 3:
            raise ContentCalendarError("slot dependencies are incomplete")
        channel = str(slot.get("channel"))
        if channel not in {item.value for item in Channel}:
            raise ContentCalendarError("slot channel is unknown")
        counts[channel] += 1
        scheduled.append(scheduled_utc)
    if any(later - earlier < timedelta(hours=18) for earlier, later in zip(scheduled, scheduled[1:])):
        raise ContentCalendarError("calendar violates the inter-slot frequency cap")
    if max(counts.values()) > 4:
        raise ContentCalendarError("calendar exceeds the per-channel frequency cap")
    if calendar.get("external_activation_executed") is not False or calendar.get(
        "automatic_rescheduling_enabled"
    ) is not False or calendar.get("automatic_publish_enabled") is not False:
        raise ContentCalendarError("calendar enabled an external or automatic effect")
