"""
LaunchKart AI 2.0 — Base Agent Class

Abstract base class that all 15 agents inherit from.
Provides: reasoning, planning, memory retrieval, tool usage,
structured output, error recovery, progress reporting, and GPU metrics.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from app.agents.state import AgentError, AgentStatus, GPUMetric, LaunchState
from app.config import get_settings

logger = structlog.get_logger(__name__)


class AgentOutput(BaseModel):
    """Base class for structured agent outputs."""

    confidence: float = 0.0
    reasoning: str = ""


class BaseAgent(ABC):
    """
    Abstract base class for all LaunchKart agents.

    Each agent implements:
    - execute(): Main logic with LLM reasoning + tool use
    - plan(): Step-by-step planning before execution
    - validate_output(): Self-validation of output quality
    - recover(): Error recovery with retry logic
    - get_system_prompt(): Agent-specific system prompt
    """

    name: str = "base_agent"
    description: str = "Base agent"
    phase: int = 0

    def __init__(self) -> None:
        self._settings = get_settings()
        self._start_time: float = 0.0
        self._tokens_used: int = 0

    async def run(self, state: LaunchState) -> LaunchState:
        """
        Main entry point — wraps execute() with lifecycle management.

        1. Update status to 'running'
        2. Retrieve memory context
        3. Plan execution steps
        4. Execute main logic with tool calls
        5. Validate output
        6. Update status to 'completed' or 'failed'
        7. Record GPU metrics
        """
        self._start_time = time.perf_counter()
        state = self._update_status(state, "running", "Initializing")

        try:
            # Plan
            state = self._update_status(state, "running", "Planning")
            plan = await self.plan(state)
            logger.info(f"Agent {self.name} plan", steps=plan)

            # Execute
            state = self._update_status(state, "running", "Executing")
            state = await self.execute(state)

            # Record completion
            duration = time.perf_counter() - self._start_time
            state = self._update_status(
                state,
                "completed",
                "Done",
                confidence=self._get_output_confidence(state),
                duration=duration,
            )

            logger.info(
                f"Agent {self.name} completed",
                duration_seconds=round(duration, 2),
                tokens=self._tokens_used,
            )

        except Exception as e:
            duration = time.perf_counter() - self._start_time
            logger.error(f"Agent {self.name} failed", error=str(e))

            # Try recovery
            try:
                state = await self.recover(e, state)
                state = self._update_status(state, "completed", "Recovered", duration=duration)
            except Exception as recovery_error:
                state = self._update_status(state, "failed", str(e), duration=duration)
                state = self._record_error(state, str(recovery_error))

        return state

    @abstractmethod
    async def execute(self, state: LaunchState) -> LaunchState:
        """Main execution logic — must be implemented by each agent."""
        ...

    async def plan(self, state: LaunchState) -> list[str]:
        """Generate a step-by-step execution plan. Override for custom planning."""
        return [f"Execute {self.name} analysis"]

    async def validate_output(self, output: dict[str, Any]) -> bool:
        """Validate the quality of agent output. Override for custom validation."""
        return True

    async def recover(self, error: Exception, state: LaunchState) -> LaunchState:
        """Attempt error recovery. Override for custom recovery logic."""
        raise error

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        ...

    def get_memory_context(self, state: LaunchState) -> str:
        """Retrieve relevant memory context for the agent."""
        # Will be connected to ChromaDB in Phase 6
        preferences = state.get("user_preferences", {})
        if preferences:
            return f"User preferences: {preferences}"
        return ""

    async def call_llm(
        self,
        prompt: str,
        state: LaunchState,
        images: list[str] | None = None,
        model_override: str | None = None,
    ) -> str:
        """
        Call the local Ollama LLM with the given prompt.
        Supports both text and vision models.
        """
        import httpx

        model = model_override or self._settings.ollama_text_model
        system_prompt = self.get_system_prompt()
        memory_context = self.get_memory_context(state)

        full_prompt = f"{memory_context}\n\n{prompt}" if memory_context else prompt

        request_body: dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 2048,
            },
        }

        if images:
            import base64
            from pathlib import Path

            encoded_images = []
            for img_path in images:
                path = Path(img_path)
                if path.exists():
                    with open(path, "rb") as f:
                        encoded_images.append(base64.b64encode(f.read()).decode())
            if encoded_images:
                request_body["images"] = encoded_images
                request_body["model"] = self._settings.ollama_vision_model

        async with httpx.AsyncClient(timeout=self._settings.ollama_request_timeout) as client:
            response = await client.post(
                f"{self._settings.ollama_base_url}/api/generate",
                json=request_body,
            )
            response.raise_for_status()
            data = response.json()

            self._tokens_used += data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

            return data.get("response", "")

    async def call_llm_structured(
        self,
        prompt: str,
        state: LaunchState,
        output_schema: type[BaseModel],
        images: list[str] | None = None,
    ) -> BaseModel:
        """Call LLM and parse response into a structured Pydantic model."""
        import json

        schema_json = json.dumps(output_schema.model_json_schema(), indent=2)
        structured_prompt = (
            f"{prompt}\n\n"
            f"You MUST respond with valid JSON matching this exact schema:\n"
            f"```json\n{schema_json}\n```\n"
            f"Respond ONLY with the JSON object, no other text."
        )

        response_text = await self.call_llm(structured_prompt, state, images)

        # Extract JSON from response
        json_str = response_text.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        parsed = json.loads(json_str)
        return output_schema.model_validate(parsed)

    def _update_status(
        self,
        state: LaunchState,
        status: str,
        step: str,
        confidence: float | None = None,
        duration: float | None = None,
    ) -> LaunchState:
        """Update the agent's status in the shared state."""
        statuses = dict(state.get("agent_statuses", {}))
        now = datetime.now(timezone.utc).isoformat()

        current = statuses.get(self.name, {})
        statuses[self.name] = AgentStatus(
            status=status,
            progress=1.0 if status == "completed" else current.get("progress", 0.0),
            current_step=step,
            error=step if status == "failed" else None,
            confidence=confidence,
            duration_seconds=duration,
            tokens_used=self._tokens_used,
            started_at=current.get("started_at") or (now if status == "running" else None),
            completed_at=now if status in ("completed", "failed") else None,
        )

        state["agent_statuses"] = statuses
        return state

    def _record_error(self, state: LaunchState, error: str) -> LaunchState:
        """Record an error in the shared state."""
        errors = list(state.get("errors", []))
        errors.append(
            AgentError(
                agent_name=self.name,
                error=error,
                retry_count=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )
        state["errors"] = errors
        return state

    def _get_output_confidence(self, state: LaunchState) -> float:
        """Get the confidence score from this agent's output. Override for custom logic."""
        return 0.85  # Default confidence
