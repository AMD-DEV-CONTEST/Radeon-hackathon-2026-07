import asyncio
import contextlib
import json
import time
from pathlib import Path

import pytest
import websockets

from cortex.broker.server import BrokerServer


def write_registry(tmp_path: Path) -> Path:
    p = tmp_path / "org_registry.json"
    p.write_text(json.dumps({
        "did:percq:org:soc-alpha": {"pubkey": "A", "name": "Alpha", "topics": ["threat-intel"]},
    }))
    return p


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def drain_events(ws, names: list[str]) -> None:
    end = asyncio.get_event_loop().time() + 2.0
    while asyncio.get_event_loop().time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            env = json.loads(raw)
            if env.get("type") == "event":
                names.append(env["payload"]["event"])
        except TimeoutError:
            return


@pytest.mark.asyncio
async def test_broker_tolerates_disconnect_and_emits_peer_connected_on_reconnect(  # noqa: E501
    tmp_path, unused_tcp_port,
):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        event_ws = await websockets.connect(f"{uri}/?channel=event")
        events: list[str] = []

        node_ws = await websockets.connect(uri)
        await node_ws.send(json.dumps({
            "type": "subscribe", "msg_id": "sa", "src": "did:percq:org:soc-alpha",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-alpha", "topics": ["threat-intel"],
                        "scopes": ["public"]},
        }))
        await asyncio.wait_for(node_ws.recv(), timeout=2.0)
        await drain_events(event_ws, events)
        assert "broker.peer_connected" in events

        await node_ws.close()
        await asyncio.sleep(0.1)
        events.clear()
        node_ws2 = await websockets.connect(uri)
        await node_ws2.send(json.dumps({
            "type": "subscribe", "msg_id": "sa2", "src": "did:percq:org:soc-alpha",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-alpha", "topics": ["threat-intel"],
                        "scopes": ["public"]},
        }))
        await asyncio.wait_for(node_ws2.recv(), timeout=2.0)
        await drain_events(event_ws, events)
        assert "broker.peer_connected" in events
        await event_ws.close()
        await node_ws2.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
