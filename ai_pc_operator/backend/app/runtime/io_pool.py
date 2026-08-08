"""Shared I/O thread pool for blocking disk/model work."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar


T = TypeVar("T")


class IOPool:
    """Small shared executor for blocking I/O.

    The event loop should stay responsive while model files, screenshots, and
    slow filesystem operations happen in worker threads.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="screenai-io",
        )

    async def run(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, partial(func, *args, **kwargs))

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

