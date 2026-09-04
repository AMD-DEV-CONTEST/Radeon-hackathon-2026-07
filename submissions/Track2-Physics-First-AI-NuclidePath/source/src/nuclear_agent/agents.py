"""Deterministic agent runtime used before local LLM integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .contracts import run_transport_contract


class Planner(Protocol):
    def plan(self, payload: Mapping[str, Any]) -> list[str]: ...


class DeterministicPlanner:
    """Safe baseline planner; later replaceable by a local LLM planner."""

    def plan(self, payload: Mapping[str, Any]) -> list[str]:
        return ["validate_input", "environment_agent", "synthesize_report"]


@dataclass(frozen=True)
class AgentRun:
    scenario_id: str
    plan: tuple[str, ...]
    agents_called: tuple[str, ...]
    tool_result: dict[str, Any]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "plan": list(self.plan),
            "agents_called": list(self.agents_called),
            "tool_result": self.tool_result,
            "warnings": list(self.warnings),
        }


class Orchestrator:
    """Coordinates safe planning and delegation for one scenario."""

    _ALLOWED_STEPS = frozenset(
        {"validate_input", "environment_agent", "synthesize_report"}
    )

    def __init__(self, planner: Planner) -> None:
        self.planner = planner

    def run(self, payload: Mapping[str, Any]) -> AgentRun:
        plan = tuple(self.planner.plan(payload))
        unsupported = set(plan) - self._ALLOWED_STEPS
        if unsupported:
            raise ValueError(f"unsupported plan step: {sorted(unsupported)[0]}")
        if "validate_input" not in plan or "environment_agent" not in plan:
            raise ValueError("plan must validate input and call environment_agent")

        tool_result = run_transport_contract(payload).to_dict()
        return AgentRun(
            scenario_id=tool_result["scenario_id"],
            plan=plan,
            agents_called=("environment_agent",),
            tool_result=tool_result,
            warnings=tuple(tool_result["warnings"]),
        )
