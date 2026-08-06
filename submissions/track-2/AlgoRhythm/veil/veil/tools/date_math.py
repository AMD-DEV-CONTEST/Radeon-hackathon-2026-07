"""Date arithmetic — turns dates into the quasi-identifiers they actually are.

A date in a document is rarely just a date. "Started the Monday after the
May bank holiday", "18 months before the acquisition closed", "the day of the
outage" all resolve to a specific calendar date, and a specific calendar date
is a 1-in-365 selector. This tool does the resolution deterministically so the
model does not have to do arithmetic in its head — which it does badly, and
which would make findings unreproducible.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from veil.tools.registry import REGISTRY

_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y",
    "%d %b %Y", "%b %d, %Y", "%Y/%m/%d", "%d-%m-%Y",
)


def parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in _FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _granularity_note(d: date) -> str:
    return (
        f"An exact date is a ~1-in-365 selector. Generalising to "
        f"{d.strftime('%B %Y')} costs little context and widens the candidate "
        f"set roughly 30x; generalising to {d.year} widens it ~365x."
    )


@REGISTRY.register(
    name="date_math",
    description=(
        "Resolve and compare dates: compute offsets, derive an exact date from "
        "a relative reference, and report how precisely a date pins someone "
        "down. Use this instead of doing arithmetic yourself."
    ),
    parameters={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["resolve", "offset", "between", "precision"],
                "description": (
                    "resolve: parse a date string. offset: anchor + N days. "
                    "between: days between two dates. precision: how "
                    "identifying a date is."
                ),
            },
            "date_a": {"type": "string", "description": "Primary date string."},
            "date_b": {"type": "string", "description": "Second date, for 'between'."},
            "days": {"type": "integer", "description": "Offset in days, for 'offset'."},
        },
        "required": ["operation", "date_a"],
    },
)
def date_math(
    operation: str,
    date_a: str,
    date_b: str | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    a = parse_date(date_a)
    if a is None:
        return {"ok": False, "error": f"Could not parse {date_a!r}. Supported: ISO, D/M/Y, '3 May 2019'."}

    if operation == "resolve":
        return {
            "ok": True,
            "iso": a.isoformat(),
            "weekday": a.strftime("%A"),
            "month_year": a.strftime("%B %Y"),
            "year": a.year,
        }

    if operation == "offset":
        if days is None:
            return {"ok": False, "error": "'offset' requires days."}
        r = a + timedelta(days=days)
        return {"ok": True, "anchor": a.isoformat(), "offset_days": days, "result": r.isoformat(), "weekday": r.strftime("%A")}

    if operation == "between":
        b = parse_date(date_b or "")
        if b is None:
            return {"ok": False, "error": f"Could not parse date_b {date_b!r}."}
        delta = (b - a).days
        return {
            "ok": True,
            "from": a.isoformat(),
            "to": b.isoformat(),
            "days": delta,
            "years": round(delta / 365.25, 2),
        }

    if operation == "precision":
        return {
            "ok": True,
            "iso": a.isoformat(),
            "selectivity_kind": "exact_date",
            "note": _granularity_note(a),
            "suggested_generalisations": [a.strftime("%B %Y"), f"Q{((a.month - 1) // 3) + 1} {a.year}", str(a.year)],
        }

    return {"ok": False, "error": f"Unknown operation {operation!r}."}
