import asyncio
import time

from cortex.bench.query_probe import QueryProbe


class _FakeQueryResult:
    def __init__(self, article_id: str, score: float):
        self.article_id = article_id
        self.score = score


class _FakeCortexNode:
    def __init__(self, latencies_ms: list[float]) -> None:
        self.latencies_ms = latencies_ms
        self._i = 0
        self.query_count = 0

    def query(self, query_text: str, top_k: int = 5) -> list:
        self.query_count += 1
        delay = self.latencies_ms[self._i % len(self.latencies_ms)]
        self._i += 1
        time.sleep(delay / 1000.0)
        return [_FakeQueryResult("a1", 0.9)]


def test_probe_once_returns_count_throughput_p95():
    # 20 calls: 15 fast (1ms) + 5 slow (50ms) outliers
    latencies = [1.0] * 15 + [50.0] * 5
    node = _FakeCortexNode(latencies)
    probe = QueryProbe(node=node, query_pool=["q"] * 20, top_k=5, count=20)
    count, elapsed, p95 = probe.probe_once()
    assert count == 20
    assert elapsed > 0.0
    throughput = count / elapsed
    assert throughput > 0.0
    assert p95 >= 40.0


def test_p95_uses_per_call_latencies_not_wall_time(monkeypatch):
    node = _FakeCortexNode([5.0, 5.0, 5.0, 5.0])
    probe = QueryProbe(node=node, query_pool=["q"] * 4, top_k=5, count=4)
    count, _, p95 = probe.probe_once()
    assert count == 4
    assert 4.0 <= p95 <= 10.0


def test_query_probe_is_async_aware():
    node = _FakeCortexNode([1.0] * 3)
    probe = QueryProbe(node=node, query_pool=["q"] * 3, top_k=5, count=3)
    result = asyncio.run(asyncio.to_thread(probe.probe_once))
    assert result[0] == 3
