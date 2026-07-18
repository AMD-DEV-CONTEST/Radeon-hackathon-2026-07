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


@pytest.mark.asyncio
async def test_partner_beta_from_alpha_does_not_reach_other_org_subscriber(  # noqa: E501
    tmp_path, unused_tcp_port,
):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)

        beta_ws = await websockets.connect(uri)
        await beta_ws.send(json.dumps({
            "type": "subscribe", "msg_id": "sb", "src": "did:percq:org:soc-beta",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-beta",
                        "topics": ["threat-intel"],
                        "scopes": ["partner:did:percq:org:soc-delta"]},
        }))
        await asyncio.wait_for(beta_ws.recv(), timeout=2.0)

        alpha_ws = await websockets.connect(uri)
        await alpha_ws.send(json.dumps({
            "type": "subscribe", "msg_id": "sa", "src": "did:percq:org:soc-alpha",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-alpha",
                        "topics": ["threat-intel"], "scopes": ["public"]},
        }))
        await asyncio.wait_for(alpha_ws.recv(), timeout=2.0)

        publish = {
            "type": "publish", "msg_id": "pub-sv",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": _ts(),
            "payload": {"article": {"id": "art-sv", "scope": "partner:did:percq:org:soc-delta",
                                    "topic": "threat-intel", "content": "secret"}},
        }
        await alpha_ws.send(json.dumps(publish))
        ack = json.loads(await asyncio.wait_for(alpha_ws.recv(), timeout=2.0))
        assert ack["type"] == "ack"

        try:
            extra = await asyncio.wait_for(beta_ws.recv(), timeout=0.4)
            raise AssertionError(f"beta should not receive anything, got: {extra!r}")
        except TimeoutError:
            pass
        await beta_ws.close()
        await alpha_ws.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_scope_violation_event_mirrored_when_no_recipient_allowed(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)

        event_ws = await websockets.connect(f"{uri}/?channel=event")
        server._event_clients.add(event_ws)

        alpha_ws = await websockets.connect(uri)
        await alpha_ws.send(json.dumps({
            "type": "subscribe", "msg_id": "sa2", "src": "did:percq:org:soc-alpha",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-alpha",
                        "topics": ["threat-intel"], "scopes": ["public"]},
        }))
        await asyncio.wait_for(alpha_ws.recv(), timeout=2.0)

        # Drain both peer_connected events from the event channel
        for _ in range(3):
            try:
                await asyncio.wait_for(event_ws.recv(), timeout=0.3)
            except TimeoutError:
                break

        publish = {
            "type": "publish", "msg_id": "pub-private",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": _ts(),
            "payload": {"article": {"id": "art-priv", "scope": "private",
                                    "topic": "threat-intel", "content": "internal"}},
        }
        await alpha_ws.send(json.dumps(publish))
        ack = json.loads(await asyncio.wait_for(alpha_ws.recv(), timeout=2.0))
        assert ack["type"] == "ack"

        ev = json.loads(await asyncio.wait_for(event_ws.recv(), timeout=2.0))
        assert ev["type"] == "event"
        assert ev["payload"]["event"] == "broker.scope_violation"
        await event_ws.close()
        await alpha_ws.close()
        server._event_clients.discard(event_ws)
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
