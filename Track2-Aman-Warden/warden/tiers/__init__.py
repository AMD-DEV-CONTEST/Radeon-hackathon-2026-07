"""Tier 0: Regex/heuristic security checks (~0ms, no GPU, no model)."""

from __future__ import annotations

from warden.tiers.base import TierChecker, CheckResult
from warden.config import Decision


class Tier0RegexChecker(TierChecker):
    """Tier 0 — Regex and heuristic pattern matching."""

    from warden.tiers.base import CheckResult
