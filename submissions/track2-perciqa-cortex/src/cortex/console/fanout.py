from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class Fanout:
    """Broadcasts event/metrics envelopes to all connected WebSocket clients."""
    def __init__(
        self,
        on_event: Callable[[dict], Awaitable[None]] | Callable[[dict], None] | None = None,
        on_metrics: Callable[[dict], Awaitable[None]] | Callable[[dict], None] | None = None,
    ) -> None:
        self._event_clients: set[asyncio.Queue] = set()
        self._metrics_clients: set[asyncio.Queue] = set()
        self._on_event = on_event
        self._on_metrics = on_metrics

    def add_event_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._event_clients.add(q)
        return q

    def remove_event_client(self, q: asyncio.Queue) -> None:
        self._event_clients.discard(q)

    def add_metrics_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._metrics_clients.add(q)
        return q

    def remove_metrics_client(self, q: asyncio.Queue) -> None:
        self._metrics_clients.discard(q)

    def publish_event(self, payload: dict) -> None:
        for q in list(self._event_clients):
            q.put_nowait(payload)
        if self._on_event is not None:
            res = self._on_event(payload)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)

    def publish_metrics(self, payload: dict) -> None:
        for q in list(self._metrics_clients):
            q.put_nowait(payload)
        if self._on_metrics is not None:
            res = self._on_metrics(payload)
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
