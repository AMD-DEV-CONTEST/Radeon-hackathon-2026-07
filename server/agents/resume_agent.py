"""Resume analysis agent architecture (no AI logic yet)."""

from __future__ import annotations

from agents.base import BaseAgent
from agents.types import AgentContext, AgentResult, AgentType


class ResumeAgent(BaseAgent):
    """Parses and structures candidate resume data."""

    def __init__(self) -> None:
        super().__init__(name="Resume Agent", agent_type=AgentType.RESUME)

    async def initialize(self) -> None:
        self._mark_initialized()

    async def run(self, context: AgentContext) -> AgentResult:
        self._ensure_initialized()
        self._mark_running()
        result = AgentResult(
            success=True,
            agent_type=self.agent_type,
            data={
                "resume_id": str(context.resume_id) if context.resume_id else None,
                "candidate_id": str(context.candidate_id) if context.candidate_id else None,
            },
            message="ResumeAgent architecture stub — AI logic not implemented",
        )
        self._mark_standby()
        return result

    async def shutdown(self) -> None:
        self._mark_shutdown()
