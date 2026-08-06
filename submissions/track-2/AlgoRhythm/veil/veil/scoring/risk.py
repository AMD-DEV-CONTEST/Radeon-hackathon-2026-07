"""Risk scoring — residual risk on a defensible scale.

Residual risk is not an average of severities. One unresolved Tier M finding
means the document is compromised regardless of how clean everything else is,
so the score is dominated by the worst surviving finding and only modestly
adjusted for accumulation.

Every component is reported alongside the number, because a privacy score that
cannot be interrogated is a score nobody should act on.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veil.types import Finding, Tier

_TIER_CEILING = {Tier.MECHANICAL: 1.00, Tier.CORRELATIONAL: 0.85, Tier.STYLISTIC: 0.35}


@dataclass
class RiskScore:
    value: float                 # 0..1
    band: str
    dominant: str | None
    components: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "residual_risk": self.value,
            "band": self.band,
            "dominant_finding": self.dominant,
            "components": self.components,
        }


def _band(v: float) -> str:
    if v >= 0.85:
        return "CRITICAL"
    if v >= 0.6:
        return "HIGH"
    if v >= 0.35:
        return "MODERATE"
    if v >= 0.15:
        return "LOW"
    return "MINIMAL"


def score(findings: list[Finding]) -> RiskScore:
    live = [f for f in findings if not f.resolved]
    if not live:
        return RiskScore(
            0.0,
            "MINIMAL",
            None,
            {"live_findings": 0, "note": "No surviving findings after re-attack."},
        )

    weighted = [(f, min(f.severity, _TIER_CEILING[f.tier])) for f in live]
    worst_finding, worst = max(weighted, key=lambda x: x[1])

    # Accumulation: additional independent findings raise risk, with sharply
    # diminishing returns. Five moderate leaks are worse than one, but they do
    # not add up to a mechanical extraction.
    others = sorted((w for f, w in weighted if f.id != worst_finding.id), reverse=True)
    accumulation = 0.0
    for i, w in enumerate(others[:5]):
        accumulation += w * (0.5 ** (i + 1)) * 0.3

    value = round(min(1.0, worst + accumulation), 3)

    tier_counts = {t.value: sum(1 for f in live if f.tier is t) for t in Tier}
    return RiskScore(
        value=value,
        band=_band(value),
        dominant=worst_finding.claim,
        components={
            "live_findings": len(live),
            "by_tier": tier_counts,
            "worst_weighted_severity": round(worst, 3),
            "accumulation_bonus": round(accumulation, 3),
            "dominant_tier": worst_finding.tier.value,
            "dominant_candidate_set": worst_finding.candidate_set_size,
        },
    )
