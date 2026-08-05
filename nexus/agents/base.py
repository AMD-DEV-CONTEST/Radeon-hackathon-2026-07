"""
Base agent class and agent framework
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, Literal
from uuid import uuid4

from nexus.inference.engine import NexusInferenceEngine, InferenceResult

logger = logging.getLogger(__name__)


@dataclass
class AgentTask:
    """Task for an agent to execute"""
    id: str = field(default_factory=lambda: f"task_{uuid4().hex[:8]}")
    description: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 5  # 1-10, higher = more urgent


@dataclass
class AgentResult:
    """Result from agent execution"""
    task_id: str
    agent_id: str
    success: bool
    output: Any
    reasoning: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """
    Base class for all NEXUS agents
    Each agent is a specialized AI that performs specific tasks
    """

    def __init__(
        self,
        agent_id: str,
        inference_engine: NexusInferenceEngine,
        model_type: Literal["reasoning", "code", "fast"] = "fast",
    ):
        self.agent_id = agent_id
        self.inference_engine = inference_engine
        self.model_type = model_type
        self.is_running = False
        self.current_task: Optional[AgentTask] = None

    @abstractmethod
    async def execute(self, task: AgentTask) -> AgentResult:
        """
        Execute a task and return the result
        Must be implemented by subclasses
        """
        pass

    async def _infer(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> InferenceResult:
        """Helper to run inference"""
        return await self.inference_engine.infer(
            prompt=prompt,
            model_type=self.model_type,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _build_prompt(self, task: AgentTask) -> str:
        """
        Build a prompt for the model based on the task
        Can be overridden by subclasses for custom prompting
        """
        return f"""You are {self.agent_id}, a specialized AI agent in the NEXUS system.

Task: {task.description}

Context:
{self._format_context(task.context)}

Provide your analysis and recommendations."""

    def _format_context(self, context: dict[str, Any]) -> str:
        """Format context dictionary as readable text"""
        lines = []
        for key, value in context.items():
            if isinstance(value, (list, dict)):
                lines.append(f"{key}:")
                lines.append(f"  {value}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    async def run(self, task: AgentTask) -> AgentResult:
        """
        Run the agent on a task with error handling and timing
        """
        import time

        self.is_running = True
        self.current_task = task
        start_time = time.perf_counter()

        logger.info(f"Agent {self.agent_id} starting task {task.id}")

        try:
            result = await self.execute(task)
            result.latency_ms = (time.perf_counter() - start_time) * 1000
            logger.info(
                f"Agent {self.agent_id} completed task {task.id} "
                f"in {result.latency_ms:.0f}ms"
            )
            return result

        except Exception as e:
            logger.error(f"Agent {self.agent_id} failed on task {task.id}: {e}")
            latency_ms = (time.perf_counter() - start_time) * 1000
            return AgentResult(
                task_id=task.id,
                agent_id=self.agent_id,
                success=False,
                output=None,
                error=str(e),
                latency_ms=latency_ms,
            )

        finally:
            self.is_running = False
            self.current_task = None

    def __repr__(self) -> str:
        status = "running" if self.is_running else "idle"
        return f"{self.__class__.__name__}(id={self.agent_id}, status={status})"


class AgentPool:
    """
    Pool of agents for parallel execution
    Manages agent lifecycle and task distribution
    """

    def __init__(self, max_concurrent: int = 8):
        self.agents: dict[str, BaseAgent] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.task_queue: asyncio.Queue[AgentTask] = asyncio.Queue()
        self.results: dict[str, AgentResult] = {}

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent in the pool"""
        self.agents[agent.agent_id] = agent
        logger.info(f"Registered agent {agent.agent_id}")

    async def execute_task(
        self,
        agent_id: str,
        task: AgentTask,
    ) -> AgentResult:
        """Execute a task with a specific agent"""
        agent = self.agents.get(agent_id)
        if not agent:
            return AgentResult(
                task_id=task.id,
                agent_id=agent_id,
                success=False,
                output=None,
                error=f"Agent {agent_id} not found",
            )

        async with self.semaphore:
            result = await agent.run(task)
            self.results[task.id] = result
            return result

    async def execute_parallel(
        self,
        tasks: list[tuple[str, AgentTask]],  # [(agent_id, task), ...]
    ) -> list[AgentResult]:
        """Execute multiple tasks in parallel"""
        task_coroutines = [
            self.execute_task(agent_id, task)
            for agent_id, task in tasks
        ]
        return await asyncio.gather(*task_coroutines)

    def get_result(self, task_id: str) -> Optional[AgentResult]:
        """Get result for a completed task"""
        return self.results.get(task_id)

    def get_agent_status(self) -> dict[str, dict[str, Any]]:
        """Get status of all agents"""
        return {
            agent_id: {
                "is_running": agent.is_running,
                "current_task": agent.current_task.id if agent.current_task else None,
                "model_type": agent.model_type,
            }
            for agent_id, agent in self.agents.items()
        }
