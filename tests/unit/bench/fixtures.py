from typing import Any

from cortex.bench.embed_probe import EmbedProbe
from cortex.bench.query_probe import QueryProbe
from cortex.bench.runner import BenchRunner
from cortex.bench.targets import BENCH_EMBED_BATCH, BENCH_QUERY_COUNT


class _RecordingBroker:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def connect(self) -> None:
        pass

    async def publish_envelope(self, env) -> None:
        self.published.append(env)

    async def close(self) -> None:
        pass


class _ZeroGpuSensorStub:
    def snapshot(self):
        return {"mem_util_pct": 0.0}


class _InstantEmbedder:
    def __init__(self, backend: str = "gpu") -> None:
        self.backend = backend

    def embed(self, texts):
        import numpy as np
        return np.zeros((len(texts), 384), dtype=np.float32)


class _FakeCortexNode:
    def __init__(self, backend: str) -> None:
        self.backend = backend

    def query(self, query_text: str, top_k: int = 5):
        import time
        time.sleep(0.001)
        return [{"article_id": "a1", "score": 0.9}]


def make_probe_factory(node_id: str):
    pool = ["synthetic SOC finding text"] * 16
    query_pool = ["APT29 TTPs"] * 8

    def factory(node_id_inner):
        return {
            "embed_radeon": EmbedProbe(
                pool, batch_size=BENCH_EMBED_BATCH, mode="radeon",
                embedder_factory=lambda backend="gpu": _InstantEmbedder(backend),
            ),
            "embed_cpu": EmbedProbe(
                pool, batch_size=BENCH_EMBED_BATCH, mode="cpu",
                embedder_factory=lambda backend="cpu": _InstantEmbedder(backend),
            ),
            "query_radeon": QueryProbe(
                _FakeCortexNode("gpu"), query_pool, top_k=5, count=BENCH_QUERY_COUNT,
            ),
            "query_cpu": QueryProbe(
                _FakeCortexNode("cpu"), query_pool, top_k=5, count=BENCH_QUERY_COUNT,
            ),
        }

    return factory


def make_runner(node_id: str, broker: _RecordingBroker, tick: float) -> BenchRunner:
    return BenchRunner(
        node_id=node_id,
        broker_url="inmemory",
        config_path="bench.yaml",
        tick_interval=tick,
        broker_client_factory=lambda url: broker,
        probe_factory=make_probe_factory(node_id),
        gpu_sensor=_ZeroGpuSensorStub(),
    )
