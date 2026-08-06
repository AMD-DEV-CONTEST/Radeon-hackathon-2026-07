"""
Multi-agent orchestrator that routes goals to specialized agents.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from ..core.agent import Agent
from ..core.llm import LLMEngine
from ..core.memory import MemoryManager
from ..core.tools import ToolRegistry

logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """
    Lightweight multi-agent system.

    Specialized agents:
    - Planner   : high-level planning and prioritization
    - Researcher: information gathering & analysis
    - Coder     : software engineering & code related tasks
    - Executor  : general purpose task execution
    """

    def __init__(
        self,
        llm: LLMEngine,
        tools: Optional[ToolRegistry] = None,
        memory: Optional[MemoryManager] = None,
        verbose: bool = True,
    ):
        self.llm = llm
        self.verbose = verbose

        # Shared tools & memory (or create defaults)
        self.tools = tools or ToolRegistry(enable_web=False, enable_python=True, enable_fs=True)
        self.memory = memory or MemoryManager()

        self.agents: Dict[str, Agent] = {
            "planner": Agent(
                llm, self.tools, self.memory, name="PlannerAgent", verbose=verbose
            ),
            "researcher": Agent(
                llm, self.tools, self.memory, name="ResearcherAgent", verbose=verbose
            ),
            "coder": Agent(
                llm, self.tools, self.memory, name="CoderAgent", verbose=verbose
            ),
            "executor": Agent(
                llm, self.tools, self.memory, name="ExecutorAgent", verbose=verbose
            ),
        }

    def route(self, goal: str) -> str:
        """Simple keyword + semantic routing."""
        g = goal.lower()

        code_keywords = [
            "code", "python", "function", "class", "debug", "implement",
            "refactor", "bug", "script", "algorithm", "api", "test",
        ]
        research_keywords = [
            "research", "search", "find", "what is", "explain", "compare",
            "analyze", "investigate", "summary", "information about",
        ]
        plan_keywords = [
            "plan", "schedule", "prioritize", "roadmap", "strategy",
            "organize", "daily plan", "todo", "agenda",
        ]

        if any(k in g for k in code_keywords):
            return "coder"
        if any(k in g for k in research_keywords):
            return "researcher"
        if any(k in g for k in plan_keywords):
            return "planner"
        return "executor"

    def run(self, goal: str, force_agent: Optional[str] = None) -> str:
        agent_key = force_agent or self.route(goal)
        agent = self.agents.get(agent_key, self.agents["executor"])

        if self.verbose:
            print(f"\n[Orchestrator] Routing goal to → {agent.name}")

        # Give specialized agents a small persona boost via context
        context = self._agent_context(agent_key)
        return agent.run(goal, use_planner=True, context=context)

    def _agent_context(self, key: str) -> str:
        contexts = {
            "planner": "You specialize in breaking work into prioritized, realistic plans.",
            "researcher": "You specialize in gathering, synthesizing, and explaining information.",
            "coder": "You specialize in writing, reviewing, and debugging code. Prefer concrete code solutions.",
            "executor": "You are a general-purpose problem solver.",
        }
        return contexts.get(key, "")
