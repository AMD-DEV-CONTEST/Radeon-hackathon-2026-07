"""Time utilities."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(UTC)

