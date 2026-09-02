"""Fact-checker agent architecture (no AI logic yet)."""

from __future__ import annotations

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, AgentType


class FactCheckerAgent(BaseAgent):
    """Validates candidate claims against resume and transcript evidence."""

    def __init__(self) -> None:
        super().__init__(name="Fact Checker Agent", agent_type=AgentType.FACT_CHECKER)

    async def initialize(self) -> None:
        self._mark_initialized()

    async def run(self, context: AgentContext) -> AgentResult:
        self._ensure_initialized()
        self._mark_running()
        result = AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "interview_id": str(context.interview_id) if context.interview_id else None,
                "resume_id": str(context.resume_id) if context.resume_id else None,
            },
            message="FactCheckerAgent architecture stub — AI logic not implemented",
        )
        self._mark_standby()
        return result

    async def shutdown(self) -> None:
        self._mark_shutdown()
