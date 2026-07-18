from pathlib import Path

import pytest

from cortex.node.node import CortexNode
from tests.unit.node.test_node_publish import FakeBroker, make_keys  # noqa: F401


@pytest.mark.asyncio
async def test_health_loop_swaps_to_cpu(cfg: Path, tmp_path: Path, monkeypatch) -> None:
    keys = make_keys(tmp_path); broker = FakeBroker()
    node = CortexNode(org_did="did:percq:org:soc-alpha", agent_did="did:percq:agent:alpha-bot-1",
                      key_paths=keys, broker_url="ws://localhost:7432", config_path=cfg,
                      embedder_backend_override="cpu")
    node._broker_override = broker
    await node.start()
    called = {"n": 0}

    async def fast_loop() -> None:
        called["n"] += 1
        node.embedder.fallback_to_cpu = False
        assert node.embedder._check_gpu() is False
        node.embedder.fallback_to_cpu = True
        node._on_embed_failed("healthcheck:no_gpu")

    node._health_task.cancel()
    await fast_loop()
    assert called["n"] == 1
    ev = node.store.recent_events(limit=10)
    assert any("healthcheck" in str(e) for e in ev), ev
    await node.stop()
