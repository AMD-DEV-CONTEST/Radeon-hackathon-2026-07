import asyncio
import contextlib
import json

import pytest
from websockets.asyncio.server import serve

from cortex.console.broker_subscriber import BrokerSubscriber
from cortex.console.fanout import Fanout


@pytest.mark.asyncio
async def test_broker_events_reach_fanout(unused_tcp_port: int):
    received: list[dict] = []
    fanout = Fanout(on_event=lambda env: received.append(env))

    async def broker_handler(ws):
        event = {"type": "event", "payload": {
            "event": "article.published", "data": {"id": "a1"}}}
        await ws.send(json.dumps(event))

    server = await serve(broker_handler, "127.0.0.1", unused_tcp_port)
    sub = BrokerSubscriber(uri=f"ws://127.0.0.1:{unused_tcp_port}", fanout=fanout)
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.4)
    finally:
        await sub.stop()
        server.close()
        await server.wait_closed()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert received == [{"event": "article.published", "data": {"id": "a1"}}]
