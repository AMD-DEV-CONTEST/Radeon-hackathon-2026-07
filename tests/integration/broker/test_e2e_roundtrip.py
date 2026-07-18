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
        "did:percq:org:soc-alpha": {
            "pubkey": "A", "name": "Alpha", "topics": ["threat-intel", "apt29"]
        },
        "did:percq:org:soc-beta": {"pubkey": "B", "name": "Beta", "topics": ["threat-intel"]},
    }))
    return p


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def subscribe_as(uri: str, org: str, node_id: str, topics, scopes):
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({
        "type": "subscribe", "msg_id": f"s-{node_id}", "src": org, "dst": "broker",
        "ts": _ts(),
        "payload": {"node_id": node_id, "topics": topics, "scopes": scopes},
    }))
    await asyncio.wait_for(ws.recv(), timeout=2.0)
    return ws


@pytest.mark.asyncio
async def test_full_publish_acl_forward_event_mirror_roundtrip(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        event_ws = await websockets.connect(f"{uri}/?channel=event")
        alpha = await subscribe_as(uri, "did:percq:org:soc-alpha", "node-alpha",
                                   ["threat-intel"], ["public"])
        beta = await subscribe_as(uri, "did:percq:org:soc-beta", "node-beta",
                                  ["threat-intel"], ["public"])

        await alpha.send(json.dumps({
            "type": "publish", "msg_id": "e2e-pub",
            "src": "did:percq:org:soc-beta",
            "dst": "*", "ts": _ts(),
            "payload": {"article": {"id": "art-e2e", "scope": "public",
                                    "topic": "threat-intel", "content": "TTP"}},
        }))
        # Drain ack from alpha and the forwarded publish from beta
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(alpha.recv(), timeout=0.3)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(beta.recv(), timeout=0.3)

        await alpha.send(json.dumps({
            "type": "publish", "msg_id": "e2e-pub-2",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": _ts(),
            "payload": {"article": {"id": "art-e2e-2", "scope": "public",
                                    "topic": "threat-intel", "content": "TTP2"}},
        }))
        ack = json.loads(await asyncio.wait_for(alpha.recv(), timeout=2.0))
        assert ack["type"] == "ack"
        fwd = json.loads(await asyncio.wait_for(beta.recv(), timeout=2.0))
        assert fwd["type"] == "publish"
        assert fwd["payload"]["article"]["id"] == "art-e2e-2"

        seen_events: list[str] = []
        end = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < end and \
              "article.published" not in seen_events:
            try:
                raw = await asyncio.wait_for(event_ws.recv(), timeout=0.5)
                env = json.loads(raw)
                if env.get("type") == "event":
                    seen_events.append(env["payload"]["event"])
            except TimeoutError:
                break
        assert "broker.peer_connected" in seen_events
        assert "article.published" in seen_events

        await event_ws.close()
        await alpha.close()
        await beta.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
