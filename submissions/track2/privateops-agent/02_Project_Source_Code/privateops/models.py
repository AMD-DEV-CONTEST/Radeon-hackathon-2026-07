from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    source: str
    snippet: str
    score: float
    evidence_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PermissionDecision:
    level: str
    reason: str
    requires_confirmation: bool
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Confirmation:
    token: str
    action: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResult:
    name: str
    status: str
    summary: str
    output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanStep:
    id: str
    title: str
    kind: str
    status: str = "pending"
    tool_name: str = ""
    result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RocmProfile:
    gpu_name: str = ""
    rocm_version: str = ""
    model_endpoint: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResponse:
    answer: str
    evidence: list[Evidence]
    permission: PermissionDecision
    memory_updates: dict[str, str]
    provider: str
    plan: list[PlanStep] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    audit_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "evidence": [item.to_dict() for item in self.evidence],
            "permission": self.permission.to_dict(),
            "memory_updates": dict(self.memory_updates),
            "provider": self.provider,
            "plan": [item.to_dict() for item in self.plan],
            "tool_results": [item.to_dict() for item in self.tool_results],
            "metrics": dict(self.metrics),
            "audit_id": self.audit_id,
        }
