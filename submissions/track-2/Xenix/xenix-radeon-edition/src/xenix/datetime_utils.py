from __future__ import annotations

from datetime import datetime, timezone, tzinfo


def normalize_datetime_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_datetime_for_display(
    value: datetime,
    *,
    format_string: str,
    target_tz: tzinfo | None = None,
) -> str:
    normalized = normalize_datetime_to_utc(value)
    resolved_tz = target_tz or datetime.now().astimezone().tzinfo or timezone.utc
    return normalized.astimezone(resolved_tz).strftime(format_string)
