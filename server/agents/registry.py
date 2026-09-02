"""Agent registry for dependency injection and lifecycle management."""

from __future__ import annotations

from agents.base import BaseAgent
from agents.types import AgentType


class AgentRegistry:
    """In-process registry that owns independent agent instances."""

    def __init__(self) -> None:
        self._agents: dict[AgentType, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.agent_type in self._agents:
            raise ValueError(f"Agent already registered for type: {agent.agent_type}")
        self._agents[agent.agent_type] = agent

    def get(self, agent_type: AgentType) -> BaseAgent:
        try:
            return self._agents[agent_type]
        except KeyError as exc:
            raise KeyError(f"No agent registered for type: {agent_type}") from exc

    def has(self, agent_type: AgentType) -> bool:
        return agent_type in self._agents

    def all(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def types(self) -> list[AgentType]:
        return list(self._agents.keys())

    async def initialize_all(self) -> None:
        for agent in self._agents.values():
            if not agent.is_initialized:
                await agent.initialize()

    async def shutdown_all(self) -> None:
        for agent in self._agents.values():
            if agent.is_initialized:
                await agent.shutdown()


def build_default_registry() -> AgentRegistry:
    """Construct a registry with all default independent agents."""
    # Local imports keep agent modules independent and avoid circular deps.
    from agents.behavioral_agent import BehavioralAgent
    from agents.evaluation_agent import EvaluationAgent
    from agents.fact_checker_agent import FactCheckerAgent
    from agents.hiring_agent import HiringAgent
    from agents.planner_agent import PlannerAgent
    from agents.resume_agent import ResumeAgent
    from agents.technical_agent import TechnicalAgent

    registry = AgentRegistry()
    for agent in (
        ResumeAgent(),
        PlannerAgent(),
        TechnicalAgent(),
        BehavioralAgent(),
        FactCheckerAgent(),
        EvaluationAgent(),
        HiringAgent(),
    ):
        registry.register(agent)
    return registry


_registry: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Return the process-wide agent registry (lazy singleton)."""
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


def reset_agent_registry() -> None:
    """Reset the singleton registry (useful for tests)."""
    global _registry
    _registry = None
