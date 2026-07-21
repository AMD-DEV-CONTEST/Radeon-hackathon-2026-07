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
                                    "topics": ["threat-intel", "apt29"]},
        "did:percq:org:soc-beta": {"pubkey": "B", "name": "Beta",
                                   "topics": ["threat-intel"]},
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


@pytest.mark.asyncio
async def test_query_fanout_merges_top_k_within_deadline(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        beta = await setup_sub(uri, "did:percq:org:soc-beta", "node-beta",
                               ["threat-intel"], ["public"])
        alpha = await setup_sub(uri, "did:percq:org:soc-alpha", "node-alpha",
                                ["threat-intel"], ["public"])

        # Register canned responses for query "q1"
        server._response_registry["node-beta"] = [
            {"article_id": "b1", "score": 0.55, "trust": 0.6, "summary": "b1"},
            {"article_id": "b2", "score": 0.91, "trust": 0.9, "summary": "b2"},
        ]
        server._response_registry["node-alpha"] = [
            {"article_id": "a1", "score": 0.72, "trust": 0.7, "summary": "a1"},
        ]

        query = {
            "type": "query", "msg_id": "q1",
            "src": "did:percq:org:soc-beta", "dst": "*", "ts": _ts(),
            "payload": {"query_id": "q1",
                        "query_text": "TTPs APT29",
                        "topic_filter": ["threat-intel"],
                        "scope_filter": ["public"],
                        "top_k": 2,
                        "min_trust": 0.0,
                        "deadline_ms": 500},
        }
        await beta.send(json.dumps(query))
        seen_result = None
        for _ in range(5):
            raw = await asyncio.wait_for(beta.recv(), timeout=3.0)
            env = json.loads(raw)
            if env.get("type") == "query_result":
                seen_result = env
                break
        assert seen_result is not None
        results = seen_result["payload"]["results"]
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == 0.91
        assert len(results) <= 2
        await beta.close()
        await alpha.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_query_deadline_truncation_returns_partial(tmp_path, unused_tcp_port):
    registry_path = write_registry(tmp_path)
    server = BrokerServer(registry_path=registry_path, host="127.0.0.1", port=unused_tcp_port)
    task = asyncio.create_task(server.serve())
    uri = f"ws://127.0.0.1:{unused_tcp_port}"
    try:
        await asyncio.sleep(0.05)
        beta = await setup_sub(uri, "did:percq:org:soc-beta", "node-beta",
                               ["threat-intel"], ["public"])
        alpha = await setup_sub(uri, "did:percq:org:soc-alpha", "node-alpha",
                                ["threat-intel"], ["public"])

        # Only beta responds (fast), alpha never registers (simulates stall/deadline)
        server._response_registry["node-beta"] = [
            {"article_id": "b1", "score": 0.5, "trust": 0.5, "summary": "b"},
        ]

        query = {
            "type": "query", "msg_id": "q2",
            "src": "did:percq:org:soc-beta", "dst": "*", "ts": _ts(),
            "payload": {"query_id": "q2",
                        "query_text": "slow",
                        "topic_filter": ["threat-intel"],
                        "scope_filter": ["public"],
                        "top_k": 5, "min_trust": 0.0,
                        "deadline_ms": 200},
        }
        await beta.send(json.dumps(query))
        seen_result = None
        start = time.time()
        for _ in range(5):
            try:
                raw = await asyncio.wait_for(beta.recv(), timeout=2.0)
            except TimeoutError:
                break
            env = json.loads(raw)
            if env.get("type") == "query_result":
                seen_result = env
                break
        elapsed = time.time() - start
        assert seen_result is not None
        assert elapsed < 1.0
        assert len(seen_result["payload"]["results"]) == 1
        await beta.close()
        await alpha.close()
    finally:
        await server.stop()
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
