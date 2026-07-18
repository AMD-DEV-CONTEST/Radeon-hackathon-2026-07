from __future__ import annotations

import asyncio
import json
import logging

import websockets

from cortex.console.fanout import Fanout

log = logging.getLogger(__name__)


class BrokerSubscriber:
    """Persistent WS client to the broker. Reconnects with exponential backoff."""

    def __init__(self, uri: str, fanout: Fanout, min_backoff: float = 1.0, max_backoff: float = 30.0) -> None:
        self._uri = uri
        self._fanout = fanout
        self._min_backoff = min_backoff
        self._max_backoff = max_backoff
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        backoff = self._min_backoff
        while not self._stop.is_set():
            try:
                async with websockets.connect(self._uri) as ws:
                    log.info("broker connected: %s", self._uri)
                    backoff = self._min_backoff
                    while not self._stop.is_set():
                        raw = await ws.recv()
                        try:
                            env = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if env.get("type") == "event":
                            self._fanout.publish_event(env.get("payload", {}))
                        elif env.get("type") == "metrics":
                            self._fanout.publish_metrics(env.get("payload", {}))
            except (OSError, websockets.ConnectionClosed):
                if self._stop.is_set():
                    break
                log.warning("broker disconnected; retrying in %.1fs", backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(self._max_backoff, backoff * 2)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def start(self) -> asyncio.Task:
        self._task = asyncio.create_task(self.run())
        return self._task
