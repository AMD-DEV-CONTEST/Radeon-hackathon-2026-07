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
        "did:percq:org:soc-beta": {"pubkey": "B", "name": "Beta", "topics": ["threat-intel"]},
    }))
    return p


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def setup_sub(uri: str, org: str, node_id: str, topics, scopes):
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({
        "type": "subscribe", "msg_id": f"s-{node_id}", "src": org, "dst": "broker",
        "ts": _ts(),
        "payload": {"node_id": node_id, "topics": topics, "scopes": scopes},
    }))
    await asyncio.wait_for(ws.recv(), timeout=2.0)
    return ws


async def drain_non_dead_letter(ws, deadline=1.0) -> dict:
    """Drain events from event_ws until broker.dead_letter is found."""
    end = asyncio.get_event_loop().time() + deadline
    while asyncio.get_event_loop().time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            env = json.loads(raw)
            if env.get("type") == "event" and \
               env["payload"].get("event") == "broker.dead_letter":
                return env
        except TimeoutError:
            pass
    raise AssertionError("no broker.dead_letter event observed")


@pytest.mark.asyncio
async def test_dead_letter_emitted_when_send_fails(tmp_path, unused_tcp_port, monkeypatch):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)

        # Connect event channel and drain initial events
        event_ws = await asyncio.wait_for(
            websockets.connect(f"{uri}/?channel=event"), timeout=2.0)
        for _ in range(3):
            try:
                await asyncio.wait_for(event_ws.recv(), timeout=0.3)
            except TimeoutError:
                break

        await setup_sub(uri, "did:percq:org:soc-beta", "node-beta",
                               ["threat-intel"], ["public"])
        alpha = await setup_sub(uri, "did:percq:org:soc-alpha", "node-alpha",
                                ["threat-intel"], ["public"])

        # Replace beta's server-side WebSocket with a broken one that fails on send
        class BrokenWS:
            async def send(self, msg):
                json.loads(msg) if isinstance(msg, str) else msg
                raise ConnectionResetError("forced send failure for dead_letter test")

        for sub in server.router.all_subscribers():
            if sub.node_id == "node-beta":
                sub.ws = BrokenWS()
                break

        await alpha.send(json.dumps({
            "type": "publish", "msg_id": "pub-dl",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": _ts(),
            "payload": {"article": {"id": "art-dl", "scope": "public",
                                    "topic": "threat-intel", "content": "x"}},
        }))
        await asyncio.wait_for(alpha.recv(), timeout=2.0)

        ev = await drain_non_dead_letter(event_ws, deadline=3.0)
        assert ev["payload"]["event"] == "broker.dead_letter"
        await event_ws.close()
        await alpha.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
