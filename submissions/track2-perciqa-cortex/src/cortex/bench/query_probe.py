from __future__ import annotations

import time

from cortex.node.node import CortexNode


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(0.95 * (len(s) - 1))
    return float(s[idx])


class QueryProbe:
    def __init__(
        self,
        node: CortexNode,
        query_pool: list[str],
        top_k: int = 5,
        count: int = 10,
    ) -> None:
        self.node = node
        self.query_pool = query_pool
        self.top_k = top_k
        self.count = count
        self._cursor = 0

    def probe_once(self) -> tuple[int, float, float]:
        latencies_ms: list[float] = []
        t0 = time.perf_counter()
        for _ in range(self.count):
            q = self.query_pool[self._cursor % len(self.query_pool)]
            self._cursor += 1
            call_t0 = time.perf_counter()
            self.node.query(q, top_k=self.top_k)
            latencies_ms.append((time.perf_counter() - call_t0) * 1000.0)
        elapsed = time.perf_counter() - t0
        return (self.count, elapsed, _p95(latencies_ms))

    async def probe_once_async(self) -> tuple[int, float, float]:
        import asyncio

        return await asyncio.to_thread(self.probe_once)
