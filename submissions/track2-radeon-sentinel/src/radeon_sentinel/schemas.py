"""Serializable domain objects used by the agent."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class Evidence:
    source: str
    excerpt: str
    score: float


@dataclass(frozen=True)
class PlanStep:
    title: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ToolResult:
    name: str
    status: str
    output: Dict[str, Any]
    requires_approval: bool = False


@dataclass
class AgentResponse:
    case_id: str
    status: str
    summary: str
    plan: List[PlanStep] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
