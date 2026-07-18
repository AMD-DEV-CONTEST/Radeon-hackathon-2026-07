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
        "did:percq:org:soc-alpha": {"pubkey": "A", "name": "Alpha",
                                    "topics": ["threat-intel"]},
        "did:percq:org:soc-beta": {"pubkey": "B", "name": "Beta",
                                    "topics": ["threat-intel"]},
    }))
    return p


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def drain_events(ws, names_seen: list, expected: set[str], deadline=2.0) -> None:
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            env = json.loads(raw)
            if env.get("type") == "event":
                names_seen.append(env["payload"]["event"])
                if expected.issubset(set(names_seen)):
                    return
        except TimeoutError:
            pass


@pytest.mark.asyncio
async def test_event_channel_sees_peer_connected_and_article_published(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        event_ws = await websockets.connect(f"{uri}/?channel=event")
        observed: list[str] = []

        node_ws = await websockets.connect(uri)
        await node_ws.send(json.dumps({
            "type": "subscribe", "msg_id": "sa", "src": "did:percq:org:soc-alpha",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-alpha",
                        "topics": ["threat-intel"], "scopes": ["public"]},
        }))
        await asyncio.wait_for(node_ws.recv(), timeout=2.0)

        await node_ws.send(json.dumps({
            "type": "publish", "msg_id": "pub-1",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": _ts(),
            "payload": {"article": {"id": "art-1", "scope": "public",
                                    "topic": "threat-intel", "content": "x"}},
        }))
        await asyncio.wait_for(node_ws.recv(), timeout=2.0)

        await drain_events(event_ws, observed, {"broker.peer_connected", "article.published"})
        assert "broker.peer_connected" in observed
        assert "article.published" in observed

        await event_ws.close()
        await node_ws.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
