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
            "pubkey": "-----BEGIN PUBLIC KEY-----\nA\n-----END PUBLIC KEY-----\n",
            "name": "SOC Alpha",
            "topics": ["threat-intel", "apt29"],
        },
        "did:percq:org:soc-beta": {
            "pubkey": "-----BEGIN PUBLIC KEY-----\nB\n-----END PUBLIC KEY-----\n",
            "name": "SOC Beta",
            "topics": ["threat-intel"],
        },
    }))
    return p


def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@pytest.mark.asyncio
async def test_subscribe_handshake_registers_subscriber(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    try:
        await asyncio.sleep(0.05)
        uri = f"ws://127.0.0.1:{unused_tcp_port}"
        async with websockets.connect(uri) as ws:
            sub_env = {
                "type": "subscribe",
                "msg_id": "00000000-0000-4000-8000-000000000001",
                "src": "did:percq:org:soc-alpha",
                "dst": "broker",
                "ts": _ts(),
                "payload": {"node_id": "node-A", "topics": ["threat-intel"], "scopes": ["public"]},
            }
            await ws.send(json.dumps(sub_env))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            ack = json.loads(raw)
            assert ack["type"] == "ack"
        subs = server.router.subscribers_for("threat-intel", "public", "did:percq:org:soc-alpha")
        assert any(s.node_id == "node-A" for s in subs)
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_unknown_org_in_handshake_is_rejected(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    try:
        await asyncio.sleep(0.05)
        uri = f"ws://127.0.0.1:{unused_tcp_port}"
        async with websockets.connect(uri) as ws:
            sub_env = {
                "type": "subscribe",
                "msg_id": "00000000-0000-4000-8000-000000000002",
                "src": "did:percq:org:rogue",
                "dst": "broker",
                "ts": _ts(),
                "payload": {"node_id": "rogue", "topics": ["x"], "scopes": ["public"]},
            }
            await ws.send(json.dumps(sub_env))
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            err = json.loads(raw)
            assert err["type"] == "error"
            assert err["payload"]["code"] == "UNKNOWN_PRODUCER"
        assert server.router.all_subscribers() == []
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
