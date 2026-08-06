from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.base import BaseTrigger

from agent_factory.scheduler_system.schema import SchedulerScheduleType


def build_trigger(
    *,
    schedule_type: SchedulerScheduleType,
    schedule_expr: str,
    timezone: str,
    anchor_at: str | None = None,
) -> BaseTrigger:
    tz = ZoneInfo(timezone)
    expr = schedule_expr.strip()
    if schedule_type == "cron":
        return CronTrigger.from_crontab(expr, timezone=tz)
    if schedule_type == "interval":
        seconds = _interval_seconds(expr)
        return IntervalTrigger(
            seconds=seconds,
            timezone=tz,
            start_date=_date_value(anchor_at, tz) if anchor_at else None,
        )
    if schedule_type == "date":
        return DateTrigger(run_date=_date_value(expr, tz), timezone=tz)
    raise ValueError(f"unsupported schedule_type: {schedule_type}")


def validate_schedule_expression(*, schedule_type: SchedulerScheduleType, schedule_expr: str, timezone: str) -> None:
    build_trigger(schedule_type=schedule_type, schedule_expr=schedule_expr, timezone=timezone)


def _interval_seconds(expr: str) -> int:
    value = expr.strip()
    if value.startswith("seconds="):
        value = value.split("=", 1)[1].strip()
    try:
        seconds = int(value)
    except ValueError as exc:
        raise ValueError("interval schedule_expr must be integer seconds or seconds=<integer>") from exc
    if seconds <= 0:
        raise ValueError("interval schedule_expr seconds must be greater than 0")
    return seconds


def _date_value(expr: str, tz: ZoneInfo) -> datetime:
    try:
        value = datetime.fromisoformat(expr)
    except ValueError as exc:
        raise ValueError("date schedule_expr must be ISO datetime") from exc
    if value.tzinfo is None:
        value = value.replace(tzinfo=tz)
    return value
