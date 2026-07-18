import asyncio

import pytest

from tests.unit.bench.fixtures import _RecordingBroker, make_runner


@pytest.mark.asyncio
async def test_two_sidecars_each_publish_to_their_broker():
    broker_a = _RecordingBroker()
    broker_b = _RecordingBroker()
    runner_a = make_runner("did:percq:org:soc-alpha", broker_a, tick=0.1)
    runner_b = make_runner("did:percq:org:soc-beta", broker_b, tick=0.1)

    task_a = asyncio.create_task(runner_a.run())
    task_b = asyncio.create_task(runner_b.run())
    await asyncio.sleep(0.65)
    await runner_a.stop()
    await runner_b.stop()
    await task_a
    await task_b

    assert len(broker_a.published) >= 2, f"sidecar A only published {len(broker_a.published)}"
    assert len(broker_b.published) >= 2, f"sidecar B only published {len(broker_b.published)}"

    required_keys = {
        "node", "embeds_per_sec_radeon", "embeds_per_sec_cpu",
        "queries_per_sec_radeon", "queries_per_sec_cpu",
        "gpu_mem_util_pct", "p95_query_latency_ms",
    }
    for env in broker_a.published + broker_b.published:
        assert required_keys.issubset(env.payload.keys())
        for k in required_keys - {"node"}:
            assert isinstance(env.payload[k], (int, float))
        assert env.payload["node"].startswith("did:percq:org:")


@pytest.mark.asyncio
async def test_sidecar_metrics_payload_uses_design_5_8_key_order():
    broker = _RecordingBroker()
    runner = make_runner("did:percq:org:soc-alpha", broker, tick=0.1)
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.15)
    await runner.stop()
    await task
    env = broker.published[0]
    assert list(env.payload.keys()) == [
        "node",
        "embeds_per_sec_radeon",
        "embeds_per_sec_cpu",
        "queries_per_sec_radeon",
        "queries_per_sec_cpu",
        "gpu_mem_util_pct",
        "p95_query_latency_ms",
    ]
