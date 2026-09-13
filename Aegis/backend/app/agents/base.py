"""
BaseAgent — shared execution scaffolding every specialist agent inherits.

Centralizing this here (rather than each agent hand-rolling its own timing/
logging/persistence) is what makes explainability and benchmarking uniform
across the whole system: every agent, without exception, produces an
AgentStep record with reasoning, timing, and token metrics.
"""
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AgentExecutionError
from app.core.logging import get_logger
from app.db.models.agent_run import AgentStep
from app.inference.client import InferenceClient, get_inference_client

logger = get_logger(__name__)

MAX_RETRIES = 2


class BaseAgent(ABC):
    name: str = "base_agent"
    system_prompt: str = "You are a helpful assistant."

    def __init__(self, db: AsyncSession, inference_client: InferenceClient | None = None) -> None:
        self.db = db
        self.inference = inference_client or get_inference_client()

    @abstractmethod
    async def act(self, state: dict[str, Any]) -> dict[str, Any]:
        """Returns a partial state update (LangGraph merges this into shared state)."""
        ...

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 2):
            try:
                logger.info("agent.start", agent=self.name, attempt=attempt)
                update = await self.act(state)
                duration_ms = (time.perf_counter() - start) * 1000

                if state.get("agent_run_id"):
                    step = AgentStep(
                        agent_run_id=uuid.UUID(str(state["agent_run_id"])),
                        agent_name=self.name,
                        sequence=state.get("step_sequence", 0),
                        input_summary=self._summarize_input(state),
                        output_summary=self._summarize_output(update),
                        reasoning=update.get("_reasoning"),
                        tool_calls=update.get("_tool_calls", []),
                        confidence=update.get("_confidence"),
                        duration_ms=duration_ms,
                        tokens_generated=update.get("_tokens_generated"),
                        tokens_per_second=update.get("_tokens_per_second"),
                    )
                    self.db.add(step)
                    await self.db.flush()

                logger.info("agent.complete", agent=self.name, duration_ms=round(duration_ms, 2))
                # Strip internal bookkeeping keys before merging into shared state
                return {k: v for k, v in update.items() if not k.startswith("_")}

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("agent.attempt_failed", agent=self.name, attempt=attempt, error=str(exc))

        raise AgentExecutionError(
            f"Agent '{self.name}' failed after {MAX_RETRIES + 1} attempts",
            details={"agent": self.name, "last_error": str(last_error)},
        )

    def _summarize_input(self, state: dict[str, Any]) -> str:
        return f"incident={state.get('incident_id')} title={state.get('title', '')[:200]}"

    def _summarize_output(self, update: dict[str, Any]) -> str:
        visible = {k: v for k, v in update.items() if not k.startswith("_")}
        return str(visible)[:500]
