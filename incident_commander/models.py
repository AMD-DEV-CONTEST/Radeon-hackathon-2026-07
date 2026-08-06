from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Evidence:
    id: str
    timestamp: str
    source: str
    content: str

    @classmethod
    def from_dict(cls, value: dict[str, Any], index: int) -> "Evidence":
        if not isinstance(value, dict):
            raise ValueError(f"evidence[{index}] must be an object")
        content = str(value.get("content", "")).strip()
        if not content:
            raise ValueError(f"evidence[{index}].content is required")
        return cls(
            id=str(value.get("id") or f"EV-{index + 1:03d}"),
            timestamp=str(value.get("timestamp", "unknown")),
            source=str(value.get("source", "operator")),
            content=content,
        )


@dataclass(frozen=True)
class Incident:
    title: str
    service: str
    severity: str
    summary: str
    evidence: tuple[Evidence, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Incident":
        title = str(value.get("title", "")).strip()
        summary = str(value.get("summary", "")).strip()
        if not title:
            raise ValueError("title is required")
        if not summary:
            raise ValueError("summary is required")
        raw_evidence = value.get("evidence", [])
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ValueError("at least one evidence item is required")
        evidence = tuple(Evidence.from_dict(item, index) for index, item in enumerate(raw_evidence))
        if len({item.id for item in evidence}) != len(evidence):
            raise ValueError("evidence IDs must be unique")
        return cls(
            title=title,
            service=str(value.get("service", "unknown-service")),
            severity=str(value.get("severity", "SEV-2")).upper(),
            summary=summary,
            evidence=evidence,
        )


@dataclass(frozen=True)
class Hypothesis:
    title: str
    confidence: float
    rationale: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    priority: str
    action: str
    reason: str
    safety: str


@dataclass(frozen=True)
class IncidentReport:
    incident: Incident
    executive_summary: str
    hypotheses: tuple[Hypothesis, ...]
    actions: tuple[Action, ...]
    timeline: tuple[Evidence, ...]
    uncertainties: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
