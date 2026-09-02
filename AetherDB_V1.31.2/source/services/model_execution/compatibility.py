"""Compatibility adapter for the existing LLMRouter."""

import asyncio
from typing import Any, AsyncIterator

from services.model_execution.gateway import ModelExecutionGateway
from services.model_execution.requests import ModelTaskRequest
from services.model_execution.results import ModelTaskResult


class LegacyLLMCompatibilityGateway:
    """Adapt the current string-returning router without changing its behavior."""

    def __init__(self, legacy_router):
        self._legacy_router = legacy_router

    async def execute(self, request: ModelTaskRequest) -> ModelTaskResult:
        content = await asyncio.to_thread(
            self._legacy_router.route,
            task_type=request.task_type,
            messages=list(request.messages),
        )
        return ModelTaskResult(
            task_id=request.task_id,
            model_profile_id="legacy_default",
            provider_id="legacy_router",
            content=content,
            usage={},
            provider_model_name="legacy_default",
            task_type=request.canonical_task_type,
            legacy_task_type=request.legacy_task_type,
            runtime="legacy_router",
        )

    async def stream(self, request: ModelTaskRequest) -> AsyncIterator[dict[str, Any]]:
        result = await self.execute(request)
        yield {"type": "final", "content": result.content}
        yield {"type": "done", "task_id": result.task_id}


def get_default_gateway() -> ModelExecutionGateway:
    try:
        from services.model_registry import list_model_profiles

        if list_model_profiles():
            from services.model_routing import RoutedModelExecutionGateway

            return RoutedModelExecutionGateway()
    except Exception:
        pass
    from services.llm_engine.router import LLMRouter

    return LegacyLLMCompatibilityGateway(LLMRouter())
