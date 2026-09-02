"""Abstract workflow builder interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from agents.registry import AgentRegistry
from workflows.llm import LLMProvider, NoOpLLMProvider
from workflows.state import WorkflowState


class BaseWorkflow(ABC):
    """Modular workflow that compiles into a LangGraph state graph."""

    name: str

    def __init__(
        self,
        registry: AgentRegistry,
        *,
        llm_provider: LLMProvider | None = None,
    ) -> None:
        self.registry = registry
        self.llm_provider: LLMProvider = llm_provider or NoOpLLMProvider()
        self._compiled: CompiledStateGraph[Any, Any, Any, Any] | None = None

    @abstractmethod
    def build(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Construct and compile the LangGraph topology."""

    @property
    def graph(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Lazily compile and cache the graph."""
        if self._compiled is None:
            self._compiled = self.build()
        return self._compiled

    def compile(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        """Explicit compile alias for DI/factory usage."""
        return self.graph

    async def ainvoke(self, state: WorkflowState) -> dict[str, Any]:
        """Invoke the compiled graph asynchronously."""
        return await self.graph.ainvoke(state)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
