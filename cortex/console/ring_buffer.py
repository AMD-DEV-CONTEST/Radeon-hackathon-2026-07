from __future__ import annotations

from collections import deque
from collections.abc import Iterable


class EventRingBuffer:
    def __init__(self, capacity: int = 1000) -> None:
        self._capacity = capacity
        self._buf: deque[dict] = deque(maxlen=capacity)

    def append(self, item: dict) -> None:
        self._buf.append(item)

    def extend(self, items: Iterable[dict]) -> None:
        for it in items:
            self.append(it)

    def snapshot(self) -> list[dict]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


class MetricsRingBuffer:
    """Per-node ring of the last N samples."""

    def __init__(self, per_node_capacity: int = 60) -> None:
        self._per_node_capacity = per_node_capacity
        self._by_node: dict[str, deque[dict]] = {}

    def append(self, sample: dict) -> None:
        node = sample.get("node", "")
        dq = self._by_node.setdefault(node, deque(maxlen=self._per_node_capacity))
        dq.append(sample)

    def snapshot(self, node: str | None = None) -> dict[str, list[dict]] | list[dict]:
        if node is not None:
            return list(self._by_node.get(node, []))
        return {n: list(dq) for n, dq in self._by_node.items()}
