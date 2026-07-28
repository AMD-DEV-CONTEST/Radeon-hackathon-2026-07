"""In-memory sliding-window rate limiter, keyed by an arbitrary string
(IP, username, etc). Not distributed -- resets on process restart, and
each process has its own counters. Fine for a single-instance desktop app.
"""

import threading
import time
from typing import Dict, List


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: Dict[str, List[float]] = {}
        self._lock = threading.Lock()
        self._last_swept = time.monotonic()
        self._sweep_interval = max(window_seconds * 2, 120)

    def check(self, key: str) -> bool:
        """True if `key` is still under its limit (and records this hit);
        False if it's already at the limit for the current window."""
        now = time.monotonic()
        with self._lock:
            self._sweep_if_due(now)
            cutoff = now - self.window_seconds
            recent = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(recent) >= self.max_requests:
                self._hits[key] = recent
                return False
            recent.append(now)
            self._hits[key] = recent
            return True

    def _sweep_if_due(self, now: float) -> None:
        if now - self._last_swept < self._sweep_interval:
            return
        self._last_swept = now
        cutoff = now - self.window_seconds
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
