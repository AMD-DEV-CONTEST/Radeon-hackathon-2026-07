import asyncio
from pathlib import Path

import pytest

from cortex.node.node import CortexNode
from tests.unit.node.test_node_publish import make_keys  # noqa: F401


def make_node(cfg: Path, tmp_path: Path, broker) -> CortexNode:
    node = CortexNode(org_did="did:percq:org:soc-alpha",
                      agent_did="did:percq:agent:alpha-bot-1",
                      key_paths=make_keys(tmp_path),
                      broker_url="ws://localhost:7432",
                      config_path=cfg,
                      embedder_backend_override="cpu")
    node.broker = broker
    return node


class FakeBroker:
    def __init__(self, loop, results) -> None:
        self._loop = loop
        self._results = results

    async def query_fanout(self, env: dict) -> dict:
        await asyncio.sleep(0.01)
        return {"type": "query_result", "payload": {"results": self._results}}


@pytest.mark.asyncio
async def test_fanout_query_returns_remote_results_from_worker_thread(
        cfg: Path, tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    node = make_node(cfg, tmp_path, FakeBroker(loop, [{"article_id": "r2", "score": 0.5}]))

    results = await asyncio.to_thread(node._fanout_query, "q", [], ["public"], 5, 0.0, 400)
    assert results == [{"article_id": "r2", "score": 0.5}]


@pytest.mark.asyncio
async def test_fanout_query_from_loop_thread_degrades_to_empty(
        cfg: Path, tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    node = make_node(cfg, tmp_path, FakeBroker(loop, [{"article_id": "r3", "score": 0.4}]))

    start = asyncio.get_event_loop().time()
    results = node._fanout_query("q", [], ["public"], 5, 0.0, 100)
    elapsed = asyncio.get_event_loop().time() - start
    assert results == []
    assert elapsed < 5.0, "loop-thread fan-out must return within the bounded timeout"


@pytest.mark.asyncio
async def test_fanout_query_returns_empty_without_broker_loop(cfg: Path, tmp_path: Path) -> None:
    node = make_node(cfg, tmp_path, FakeBroker(None, []))
    assert node._fanout_query("q", [], ["public"], 5, 0.0, 400) == []
