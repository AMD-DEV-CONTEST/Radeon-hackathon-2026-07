from __future__ import annotations

from datetime import datetime


def current_date_system_context() -> str:
    current = datetime.now().astimezone()
    return (
        "Current local calendar date: "
        f"{current.date().isoformat()} ({current.tzname() or 'local timezone'})."
    )
