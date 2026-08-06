import asyncio
import contextlib

import pytest

from cortex.bench.runner import BenchRunner


class _FakeBroker:
    def __init__(self) -> None:
        self.published = []
        self.closed = False

    async def publish_envelope(self, env) -> None:
        self.published.append(env)

    async def close(self) -> None:
        self.closed = True


class _EmbedStub:
    def probe_once(self):
        return (16, 0.05)


class _QueryStub:
    def probe_once(self):
        return (10, 0.2, 5.0)


class _ZeroGpuSensorStub:
    def snapshot(self):
        return {"mem_util_pct": 0.0}


def _stub_probe_factory(node_id):
    return {
        "embed_radeon": _EmbedStub(),
        "embed_cpu": _EmbedStub(),
        "query_radeon": _QueryStub(),
        "query_cpu": _QueryStub(),
    }


@pytest.mark.asyncio
async def test_stop_cancels_loop_and_closes_broker():
    fake_broker = _FakeBroker()
    runner = BenchRunner(
        node_id="did:percq:org:soc-alpha",
        broker_url="wss://broker.local:7432",
        config_path="bench.yaml",
        tick_interval=0.02,
        broker_client_factory=lambda url: fake_broker,
        probe_factory=_stub_probe_factory,
        gpu_sensor=_ZeroGpuSensorStub(),
    )
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    await runner.stop()
    await task
    assert fake_broker.closed is True


@pytest.mark.asyncio
async def test_cancelled_error_in_run_triggers_clean_stop():
    fake_broker = _FakeBroker()
    runner = BenchRunner(
        node_id="did:percq:org:soc-alpha",
        broker_url="wss://broker.local:7432",
        config_path="bench.yaml",
        tick_interval=0.02,
        broker_client_factory=lambda url: fake_broker,
        probe_factory=_stub_probe_factory,
        gpu_sensor=_ZeroGpuSensorStub(),
    )

    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
        await task
    await runner.stop()
    assert fake_broker.closed is True
