import asyncio

import pytest

from cortex.bench.runner import BenchRunner


class _DyingBroker:
    def __init__(self) -> None:
        self.published = []

    async def publish_envelope(self, env) -> None:
        self.published.append(env)


class _ExplodingProbe:
    available = False

    def probe_once(self):
        raise RuntimeError("embedder OOM")


class _ExplodingQueryProbe:
    def probe_once(self):
        raise RuntimeError("query engine offline")


class _ZeroGpuSensor:
    def snapshot(self) -> dict:
        return {"mem_util_pct": 0.0}


@pytest.mark.asyncio
async def test_sidecar_keeps_publishing_zeros_when_all_probes_fail():
    def probe_factory(node_id):
        return {
            "embed_radeon": _ExplodingProbe(),
            "embed_cpu": _ExplodingProbe(),
            "query_radeon": _ExplodingQueryProbe(),
            "query_cpu": _ExplodingQueryProbe(),
        }

    broker = _DyingBroker()
    runner = BenchRunner(
        node_id="did:percq:org:soc-alpha",
        broker_url="inmemory",
        config_path="bench.yaml",
        tick_interval=0.02,
        broker_client_factory=lambda url: broker,
        probe_factory=probe_factory,
        gpu_sensor=_ZeroGpuSensor(),
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.1)
    await runner.stop()
    await task

    msg = "sidecar must keep emitting METRICS envelopes even when probes fail"
    assert len(broker.published) >= 1, msg
    for env in broker.published:
        assert env.payload["embeds_per_sec_radeon"] == 0.0
        assert env.payload["embeds_per_sec_cpu"] == 0.0
        assert env.payload["queries_per_sec_radeon"] == 0.0
        assert env.payload["queries_per_sec_cpu"] == 0.0
        assert env.payload["p95_query_latency_ms"] == 0.0
        assert env.payload["gpu_mem_util_pct"] == 0.0
