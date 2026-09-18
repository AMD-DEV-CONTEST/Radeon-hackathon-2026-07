"""Fixed numeric risk formula."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskComponents:
    severity: float
    confidence: float
    location: float
    evidence: float
    duration: float = 0.0
    frequency: float = 0.0

    def __post_init__(self) -> None:
        values = (
            self.severity,
            self.confidence,
            self.location,
            self.evidence,
            self.duration,
            self.frequency,
        )
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("Risk component scores must be within 0..1")


class RiskScorer:
    """LLM-independent deterministic scorer."""

    @staticmethod
    def score(components: RiskComponents) -> float:
        return (
            0.35 * components.severity
            + 0.15 * components.confidence
            + 0.20 * components.location
            + 0.10 * components.evidence
            + 0.10 * components.duration
            + 0.10 * components.frequency
        )
