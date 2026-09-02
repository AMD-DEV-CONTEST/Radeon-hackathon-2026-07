"""Abstract agent interface and shared lifecycle helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from agents.types import AgentContext, AgentResult, AgentStatus, AgentType


@runtime_checkable
class AgentProtocol(Protocol):
    """Structural interface for injectable agents."""

    name: str
    agent_type: AgentType
    status: AgentStatus

    async def initialize(self) -> None: ...

    async def run(self, context: AgentContext) -> AgentResult: ...

    async def shutdown(self) -> None: ...


class BaseAgent(ABC):
    """Abstract base class for all AgentVox agents.

    Concrete agents must implement initialize/run/shutdown and remain
    independent from other agent implementations.
    """

    def __init__(self, *, name: str, agent_type: AgentType) -> None:
        self.name = name
        self.agent_type = agent_type
        self.status = AgentStatus.IDLE
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @abstractmethod
    async def initialize(self) -> None:
        """Prepare agent resources before execution."""

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent against the provided context."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release agent resources and return to idle."""

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError(f"{self.name} is not initialized")

    def _mark_initialized(self) -> None:
        self._initialized = True
        self.status = AgentStatus.STANDBY

    def _mark_shutdown(self) -> None:
        self._initialized = False
        self.status = AgentStatus.IDLE

    def _mark_running(self) -> None:
        self.status = AgentStatus.RUNNING

    def _mark_standby(self) -> None:
        self.status = AgentStatus.STANDBY

    def _mark_error(self) -> None:
        self.status = AgentStatus.ERROR

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} name={self.name!r} "
            f"type={self.agent_type} status={self.status}>"
        )
