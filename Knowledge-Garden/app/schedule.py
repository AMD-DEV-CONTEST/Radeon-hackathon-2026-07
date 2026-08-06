"""schedule.py — deterministic SM-2-derived scheduling + garden growth.

Normative contract in docs/domain-contract.md section 3. Pure functions only;
no I/O. Used by tests (Todo 2) and study services (Todo 7).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

EASE_MIN = 1.3
EASE_MAX = 2.5
FIRST_INTERVAL_DAYS = 1
SECOND_INTERVAL_DAYS = 6
DUE_HOUR_LOCAL = 23  # Asia/Shanghai fixed local due time
TZ = ZoneInfo("Asia/Shanghai")

GRADE_OVERRIDE = 3
OVERRIDE_INTERVAL_CAP_DAYS = 3


def update_ease(ease: float, grade: int) -> float:
    """Canonical SM-2 ease update, applied for EVERY grade (including <3)."""
    q = float(max(0, min(5, grade)))
    ef = ease + (0.1 - (5.0 - q) * (0.08 + (5.0 - q) * 0.02))
    return max(EASE_MIN, min(EASE_MAX, ef))


def next_interval(interval_days: float, repetitions: int, grade: int, ease: float) -> float:
    """SM-2 interval step. Returns days (float)."""
    if grade < 3:
        return FIRST_INTERVAL_DAYS
    if repetitions <= 0:
        return FIRST_INTERVAL_DAYS
    if repetitions == 1:
        return SECOND_INTERVAL_DAYS
    # half-up rounding
    return math.floor(interval_days * ease + 0.5)


def compute_interval(ease: float, repetitions: int, grade: int, prev_interval: float) -> tuple[int, float]:
    """Return (new_repetitions, new_interval_days) per contract order.

    Grade >= 3: repetitions+1, interval per next_interval.
    Grade < 3: repetitions=0, interval=1d.
    """
    ef = update_ease(ease, grade)
    if grade < 3:
        return 0, FIRST_INTERVAL_DAYS
    reps = repetitions + 1
    interval = next_interval(prev_interval, reps - 1, grade, ef)
    if grade == 4 and repetitions == 1:
        interval = SECOND_INTERVAL_DAYS
    return reps, float(interval)


def due_at(interval_days: float, now_utc: datetime | None = None) -> datetime:
    """Next review instant: local 23:00 on the Nth following Asia/Shanghai calendar day."""
    now = now_utc or datetime.now(timezone.utc)
    now_local = now.astimezone(TZ)
    days = int(interval_days)
    due_local = now_local.replace(hour=DUE_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    if days <= 0:
        return due_local.astimezone(timezone.utc)
    target = datetime(now_local.year, now_local.month, now_local.day, tzinfo=TZ) + timedelta(days=days)
    due = target.replace(hour=DUE_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    return due.astimezone(timezone.utc)


def growth_value(total_verified: int, learned_verified: int,
                latest_masteries: list[int], overdue_count: int) -> int:
    """Derived garden growth per contract: clamp(floor(100*(0.6cov+0.4mast)) - 3*overdue, 0, 100)."""
    if total_verified <= 0:
        return 0
    coverage = learned_verified / total_verified
    mastery = sum(latest_masteries) / max(1, 5 * total_verified)
    raw = math.floor(100.0 * (0.6 * coverage + 0.4 * mastery)) - 3 * overdue_count
    return max(0, min(100, raw))


def mastery_to_grade(mastery: int) -> int:
    """mastery 5->5, 4->4, 3->3, 0-2->2."""
    return {5: 5, 4: 4, 3: 3}.get(mastery, 2)


def override_grade() -> int:
    return GRADE_OVERRIDE


def override_interval_cap() -> int:
    return OVERRIDE_INTERVAL_CAP_DAYS
