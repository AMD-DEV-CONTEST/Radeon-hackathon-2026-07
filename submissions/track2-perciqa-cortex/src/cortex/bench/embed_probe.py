from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal

from cortex.node.embedder import Embedder

EmbedderFactory = Callable[..., Embedder]


class EmbedProbe:
    def __init__(
        self,
        text_pool: list[str],
        batch_size: int = 16,
        mode: Literal["radeon", "cpu"] = "radeon",
        embedder_factory: EmbedderFactory | None = None,
    ) -> None:
        self.text_pool = text_pool
        self.batch_size = batch_size
        self.mode = mode
        self._cursor = 0
        backend = "gpu" if mode == "radeon" else "cpu"
        factory = embedder_factory or (lambda backend=backend: Embedder(backend=backend))
        try:
            self._embedder = factory(backend=backend)
            self.available = True
        except Exception:
            self._embedder = None
            self.available = False

    def probe_once(self) -> tuple[int, float]:
        if not self.available or self._embedder is None:
            return (0, 0.0)
        texts = [self.text_pool[self._cursor % len(self.text_pool)] for _ in range(self.batch_size)]
        self._cursor += self.batch_size
        t0 = time.perf_counter()
        self._embedder.embed(texts)
        elapsed = time.perf_counter() - t0
        if elapsed <= 0.0:
            elapsed = 1e-9
        return (self.batch_size, elapsed)
