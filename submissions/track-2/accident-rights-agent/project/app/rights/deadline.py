"""Deterministic, traceable deadline calculation using versioned rules."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.rules.repository import RuleRepository
from app.schemas.legal import LegalCitation
from app.schemas.rights import (
    DeadlineResult,
    DeadlineStatus,
    DeliveryDateResult,
    DeliveryDateStatus,
    LegalReviewStatus,
)


class WorkingDayCalendar:
    def __init__(
        self,
        path: Path | str = Path("config/rules/calendars/cn_2026.json"),
    ):
        self.path = Path(path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        expected = raw.pop("content_hash")
        actual = hashlib.sha256(
            json.dumps(
                raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        if actual != expected:
            raise ValueError(
                f"Working-day calendar hash mismatch: expected={expected} actual={actual}"
            )
        self.calendar_id = str(raw["calendar_id"])
        self.timezone = str(raw["timezone"])
        self.coverage_start = date.fromisoformat(raw["coverage_start"])
        self.coverage_end = date.fromisoformat(raw["coverage_end"])
        self.holidays = {date.fromisoformat(value) for value in raw["holidays"]}
        self.working_weekend_overrides = {
            date.fromisoformat(value) for value in raw["working_weekend_overrides"]
        }
        self.source_url = str(raw["source_url"])
        self.source_document = str(raw["source_document"])

    def covers(self, value: date) -> bool:
        return self.coverage_start <= value <= self.coverage_end

    def is_working_day(self, value: date) -> bool:
        if not self.covers(value):
            raise ValueError(f"Calendar does not cover {value.isoformat()}.")
        if value in self.working_weekend_overrides:
            return True
        return value.weekday() < 5 and value not in self.holidays

    def add_working_days(self, trigger: date, days: int) -> date:
        current = trigger
        added = 0
        while added < days:
            current += timedelta(days=1)
            if not self.covers(current):
                raise ValueError(f"Calendar does not cover {current.isoformat()}.")
            if self.is_working_day(current):
                added += 1
        return current


class DeadlineCalculator:
    def __init__(
        self,
        rules: RuleRepository | None = None,
        calendar: WorkingDayCalendar | None = None,
    ):
        self.rules = rules or RuleRepository()
        self.calendar = calendar or WorkingDayCalendar()

    def calculate(
        self,
        *,
        delivery: DeliveryDateResult,
        matter_type: str,
        rule_id: str,
        jurisdiction: str = "CN",
        timezone: str = "Asia/Shanghai",
        now: datetime | None = None,
        legal_citations: list[LegalCitation] | None = None,
    ) -> DeadlineResult:
        trigger = delivery.extracted_date
        lookup_date = trigger or (now.date() if now else date.today())
        try:
            rule = self.rules.get(
                rule_id, as_of_date=lookup_date, jurisdiction=jurisdiction
            )
        except (KeyError, ValueError) as exc:
            return self._disputed(
                matter_type=matter_type,
                rule_id=rule_id,
                law_id="unknown",
                delivery=delivery,
                reason=str(exc),
                timezone=timezone,
            )

        required_matter = rule.conditions.get("matter_type")
        if required_matter != matter_type:
            return self._disputed(
                matter_type=matter_type,
                rule_id=rule.rule_id,
                law_id=rule.source_law_id,
                delivery=delivery,
                reason=(
                    f"Rule matter mismatch: expected {required_matter}, got {matter_type}."
                ),
                timezone=timezone,
            )
        if (
            delivery.status is not DeliveryDateStatus.CONFIRMED
            or trigger is None
        ):
            return self._disputed(
                matter_type=matter_type,
                rule_id=rule.rule_id,
                law_id=rule.source_law_id,
                delivery=delivery,
                reason="送达日期未确认或存在争议，禁止自动起算。",
                timezone=timezone,
            )
        if not self.calendar.covers(trigger):
            return self._disputed(
                matter_type=matter_type,
                rule_id=rule.rule_id,
                law_id=rule.source_law_id,
                delivery=delivery,
                reason=(
                    f"Official working-day calendar does not cover "
                    f"{trigger.isoformat()}."
                ),
                timezone=timezone,
            )

        logic = rule.decision_logic
        if (
            logic.get("unit") != "working_day"
            or not logic.get("exclude_trigger_day")
            or not logic.get("calendar_required")
        ):
            return self._disputed(
                matter_type=matter_type,
                rule_id=rule.rule_id,
                law_id=rule.source_law_id,
                delivery=delivery,
                reason="规则缺少已核验的工作日、起算日或日历计算口径。",
                timezone=timezone,
            )
        try:
            due_date = self.calendar.add_working_days(
                trigger, int(logic["duration"])
            )
        except ValueError as exc:
            return self._disputed(
                matter_type=matter_type,
                rule_id=rule.rule_id,
                law_id=rule.source_law_id,
                delivery=delivery,
                reason=str(exc),
                timezone=timezone,
            )

        tz = ZoneInfo(timezone)
        due_at = datetime.combine(due_date, time(23, 59, 59), tzinfo=tz)
        current = now.astimezone(tz) if now else datetime.now(tz)
        remaining = due_at - current
        if current.date() < trigger:
            status = DeadlineStatus.NOT_STARTED
        elif remaining.total_seconds() < 0:
            status = DeadlineStatus.EXPIRED
        elif remaining <= timedelta(hours=24):
            status = DeadlineStatus.DUE_SOON
        else:
            status = DeadlineStatus.ACTIVE
        citations = [
            item
            for item in (legal_citations or [])
            if item.document_id == rule.source_law_id
            and item.article_no
            and item.article_no in rule.source_article
        ]
        legal_review = (
            LegalReviewStatus.NOT_NEEDED
            if citations
            else LegalReviewStatus.NEEDS_LEGAL_REVIEW
        )
        return DeadlineResult(
            deadline_id=f"DEADLINE-{rule.rule_id.removeprefix('RULE-')}-{trigger.isoformat()}",
            matter_type=matter_type,
            trigger_date=trigger,
            original_trigger_text=delivery.original_date_text,
            rule_id=rule.rule_id,
            law_id=rule.source_law_id,
            calculation_method={
                **logic,
                "calendar_id": self.calendar.calendar_id,
                "calendar_source": self.calendar.source_url,
                "calendar_document": self.calendar.source_document,
            },
            due_at=due_at,
            remaining_duration=_iso_duration(remaining),
            status=status,
            legal_citations=citations,
            assumptions=[
                "送达当日不计入期间，次一工作日起算。",
                "系统以截止日23:59:59作提醒边界；实际受理窗口或电子提交可用时点需人工确认。",
            ],
            requires_human_confirmation=(
                delivery.requires_human_confirmation or not citations
            ),
            legal_review_status=legal_review,
            timezone=timezone,
        )

    @staticmethod
    def _disputed(
        *,
        matter_type: str,
        rule_id: str,
        law_id: str,
        delivery: DeliveryDateResult,
        reason: str,
        timezone: str,
    ) -> DeadlineResult:
        return DeadlineResult(
            deadline_id=f"DEADLINE-DISPUTED-{matter_type.upper()}",
            matter_type=matter_type,
            trigger_date=None,
            original_trigger_text=delivery.original_date_text,
            rule_id=rule_id,
            law_id=law_id,
            calculation_method={"method": "not_calculated"},
            status=DeadlineStatus.DISPUTED,
            assumptions=[reason],
            requires_human_confirmation=True,
            legal_review_status=LegalReviewStatus.NEEDS_LEGAL_REVIEW,
            timezone=timezone,
        )


def _iso_duration(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    sign = "-" if seconds < 0 else ""
    return f"{sign}PT{abs(seconds)}S"
