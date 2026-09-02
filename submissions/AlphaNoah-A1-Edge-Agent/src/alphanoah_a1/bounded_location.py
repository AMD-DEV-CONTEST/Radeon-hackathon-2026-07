"""Deterministic location boundary for the bounded Web fault demo."""

from __future__ import annotations

import re


MAX_LOCATION_LENGTH = 64
_LOCATION_PATTERN = re.compile(
    rf"[A-Za-z0-9](?:[A-Za-z0-9 _-]{{0,{MAX_LOCATION_LENGTH - 2}}}"
    rf"[A-Za-z0-9])?\Z"
)


def is_valid_demo_location(location: str) -> bool:
    """Return whether location is one normalized, safe demo identifier."""

    return (
        isinstance(location, str)
        and 1 <= len(location) <= MAX_LOCATION_LENGTH
        and location == location.strip()
        and _LOCATION_PATTERN.fullmatch(location) is not None
    )


def aircon_asset_id_for_location(location: str) -> str:
    """Derive the bounded air-conditioner identity from a valid location."""

    if not is_valid_demo_location(location):
        raise ValueError("location must be a valid identifier")
    return f"{location}-AIRCON"


__all__ = [
    "MAX_LOCATION_LENGTH",
    "aircon_asset_id_for_location",
    "is_valid_demo_location",
]
