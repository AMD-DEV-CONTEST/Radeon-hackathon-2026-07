"""Msg-id deduplication with a 600 s replay window and a 10k-entry LRU cap."""
from __future__ import annotations

from collections import OrderedDict


class Deduplicator:
    def __init__(self, replay_window_sec: int = 600, cap: int = 10_000) -> None:
        self.replay_window_sec = replay_window_sec
        self.cap = cap
        self._seen: OrderedDict[str, int] = OrderedDict()

    def is_replay(self, msg_id: str, ts: int, now: int) -> bool:
        return abs(now - ts) > self.replay_window_sec or msg_id in self._seen

    def record(self, msg_id: str, ts: int) -> None:
        if msg_id in self._seen:
            self._seen.move_to_end(msg_id)
            self._seen[msg_id] = ts
            return
        self._seen[msg_id] = ts
        while len(self._seen) > self.cap:
            self._seen.popitem(last=False)

    def size(self) -> int:
        return len(self._seen)
