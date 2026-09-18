"""Risk level boundaries."""

from buildguard.schemas.common import Severity


def risk_level(score: float) -> Severity:
    if not 0 <= score <= 1:
        raise ValueError("Risk score must be within 0..1")
    if score < 0.30:
        return Severity.LOW
    if score < 0.55:
        return Severity.NORMAL
    if score < 0.75:
        return Severity.HIGH
    return Severity.CRITICAL

