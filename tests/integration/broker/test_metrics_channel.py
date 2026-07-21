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


@pytest.mark.asyncio
async def test_metrics_producer_to_consumer_forwarding(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        consumer = await websockets.connect(f"{uri}/?channel=metrics")
        producer = await websockets.connect(uri)
        await producer.send(json.dumps({
            "type": "subscribe", "msg_id": "sprod", "src": "did:percq:org:soc-alpha",
            "dst": "broker", "ts": _ts(),
            "payload": {"node_id": "node-alpha", "topics": [], "scopes": []},
        }))
        await asyncio.wait_for(producer.recv(), timeout=2.0)
        await producer.send(json.dumps({
            "type": "metrics", "msg_id": "m1",
            "src": "did:percq:org:soc-alpha", "dst": "broker", "ts": _ts(),
            "payload": {"node": "did:percq:org:soc-alpha",
                        "embeds_per_sec_radeon": 142.3,
                        "embeds_per_sec_cpu": 18.6,
                        "queries_per_sec_radeon": 23.1,
                        "queries_per_sec_cpu": 2.7,
                        "gpu_mem_util_pct": 86,
                        "p95_query_latency_ms": 42},
        }))
        ack = json.loads(await asyncio.wait_for(producer.recv(), timeout=2.0))
        assert ack["type"] == "ack"
        raw = await asyncio.wait_for(consumer.recv(), timeout=2.0)
        env = json.loads(raw)
        assert env["type"] == "metrics"
        assert env["payload"]["embeds_per_sec_radeon"] == 142.3
        await consumer.close()
        await producer.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
