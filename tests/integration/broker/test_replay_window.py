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


async def setup_sub(uri: str, org: str, node_id: str, topics, scopes):
    ws = await websockets.connect(uri)
    await ws.send(json.dumps({
        "type": "subscribe", "msg_id": f"s-{node_id}", "src": org, "dst": "broker",
        "ts": "2026-07-18T12:00:00Z",
        "payload": {"node_id": node_id, "topics": topics, "scopes": scopes},
    }))
    await asyncio.wait_for(ws.recv(), timeout=2.0)
    return ws


def iso(now: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


@pytest.mark.asyncio
async def test_stale_envelope_rejected_with_deadline_exceeded(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        alpha = await setup_sub(uri, "did:percq:org:soc-alpha", "node-alpha",
                                ["threat-intel"], ["public"])
        stale_ts = iso(int(time.time()) - 700)
        await alpha.send(json.dumps({
            "type": "publish", "msg_id": "stale-1",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": stale_ts,
            "payload": {"article": {"id": "art-stale", "scope": "public",
                                    "topic": "threat-intel", "content": "x"}},
        }))
        raw = await asyncio.wait_for(alpha.recv(), timeout=2.0)
        env = json.loads(raw)
        assert env["type"] == "error"
        assert env["payload"]["code"] == "DEADLINE_EXCEEDED"
        await alpha.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_duplicate_msg_id_within_window_dropped_silently(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        alpha = await setup_sub(uri, "did:percq:org:soc-alpha", "node-alpha",
                                ["threat-intel"], ["public"])
        beta = await setup_sub(uri, "did:percq:org:soc-beta", "node-beta",
                               ["threat-intel"], ["public"])
        now = iso(int(time.time()))
        pub = {
            "type": "publish", "msg_id": "dup-1",
            "src": "did:percq:org:soc-alpha", "dst": "*", "ts": now,
            "payload": {"article": {"id": "art-dup", "scope": "public",
                                    "topic": "threat-intel", "content": "x"}},
        }
        await alpha.send(json.dumps(pub))
        ack = json.loads(await asyncio.wait_for(alpha.recv(), timeout=2.0))
        assert ack["type"] == "ack"
        fwd = json.loads(await asyncio.wait_for(beta.recv(), timeout=2.0))
        assert fwd["msg_id"] == "dup-1"

        await alpha.send(json.dumps(pub))
        try:
            extra = await asyncio.wait_for(alpha.recv(), timeout=0.4)
            raise AssertionError(f"no ack expected for duplicate, got {extra!r}")
        except TimeoutError:
            pass
        try:
            extra = await asyncio.wait_for(beta.recv(), timeout=0.4)
            raise AssertionError(f"no forward expected for duplicate, got {extra!r}")
        except TimeoutError:
            pass
        await alpha.close()
        await beta.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
