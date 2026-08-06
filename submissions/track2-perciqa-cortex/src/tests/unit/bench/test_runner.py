import asyncio
from datetime import UTC, datetime

import pytest

from cortex.bench.runner import BenchRunner


class _FakeBrokerClient:
    def __init__(self) -> None:
        self.published = []

    async def publish_envelope(self, env) -> None:
        self.published.append(env)


class _EmbedStub:
    def probe_once(self):
        return (16, 0.05)


class _CpuEmbedStub:
    def probe_once(self):
        return (16, 0.5)


class _QueryStub:
    def probe_once(self):
        return (10, 0.2, 5.0)


class _CpuQueryStub:
    def probe_once(self):
        return (10, 2.0, 200.0)


class _ZeroGpuSensorStub:
    def snapshot(self):
        return {"mem_util_pct": 0.0}


def _stub_probe_factory(node_id: str):
    return {
        "embed_radeon": _EmbedStub(),
        "embed_cpu": _CpuEmbedStub(),
        "query_radeon": _QueryStub(),
        "query_cpu": _CpuQueryStub(),
    }


@pytest.mark.asyncio
async def test_runner_publishes_three_envelopes_in_three_ticks(monkeypatch):
    fake_broker = _FakeBrokerClient()
    runner = BenchRunner(
        node_id="did:percq:org:soc-alpha",
        broker_url="wss://broker.local:7432",
        config_path="bench.yaml",
        tick_interval=0.05,
        broker_client_factory=lambda url: fake_broker,
        probe_factory=_stub_probe_factory,
        gpu_sensor=_ZeroGpuSensorStub(),
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.18)
    await runner.stop()
    await task
    assert len(fake_broker.published) >= 3
    for env in fake_broker.published:
        assert env.type.value == "metrics" or env.type.name == "METRICS"
        assert env.src == "did:percq:org:soc-alpha"
        assert env.dst == "*"
        assert "embeds_per_sec_radeon" in env.payload
        assert "embeds_per_sec_cpu" in env.payload
        assert "queries_per_sec_radeon" in env.payload
        assert "queries_per_sec_cpu" in env.payload
        assert "gpu_mem_util_pct" in env.payload
        assert "p95_query_latency_ms" in env.payload
        assert isinstance(env.ts, datetime)
        assert env.ts.tzinfo == UTC
    first = fake_broker.published[0].payload
    assert 319.0 <= first["embeds_per_sec_radeon"] <= 321.0
    assert 31.0 <= first["embeds_per_sec_cpu"] <= 33.0
    assert first["p95_query_latency_ms"] == 5.0
    assert 0.0 <= first["gpu_mem_util_pct"] <= 100.0
