"""Gateway protocol and bridge for synchronous legacy business code."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Protocol

from services.model_execution.requests import ModelTaskRequest
from services.model_execution.results import ModelTaskResult


class ModelExecutionGateway(Protocol):
    async def execute(self, request: ModelTaskRequest) -> ModelTaskResult:
        ...

    def stream(self, request: ModelTaskRequest) -> AsyncIterator[dict[str, Any]]:
        ...


def execute_sync(
    gateway: ModelExecutionGateway,
    request: ModelTaskRequest,
) -> ModelTaskResult:
    """Execute the async contract from existing synchronous business code."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(gateway.execute(request))

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(gateway.execute(request))).result()
