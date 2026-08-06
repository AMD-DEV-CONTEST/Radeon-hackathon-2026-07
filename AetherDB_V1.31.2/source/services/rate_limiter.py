import time
from collections import defaultdict
import threading


class RateLimiter:
    """Simple in-memory sliding-window rate limiter.
    
    Uses per-key windows (client IP, API key, etc.) to limit request rates.
    Thread-safe for multi-worker deployments.
    """
    
    def __init__(self, default_limit: int = 60, window_seconds: int = 60):
        self.default_limit = default_limit
        self.window = window_seconds
        self._requests: dict = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str, limit: int = None) -> bool:
        """Check if a request from this key is allowed."""
        max_req = limit if limit is not None else self.default_limit
        now = time.time()
        cutoff = now - self.window
        
        with self._lock:
            timestamps = self._requests.get(key, [])
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= max_req:
                return False
            timestamps.append(now)
            self._requests[key] = timestamps
            return True

    def get_remaining(self, key: str, limit: int = None) -> int:
        """Get remaining requests for this key in current window."""
        max_req = limit if limit is not None else self.default_limit
        now = time.time()
        cutoff = now - self.window
        
        with self._lock:
            timestamps = self._requests.get(key, [])
            timestamps = [t for t in timestamps if t > cutoff]
            self._requests[key] = timestamps
            return max(0, max_req - len(timestamps))

    def get_reset_time(self, key: str) -> float:
        """Get seconds until the rate limit window resets."""
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            timestamps = self._requests.get(key, [])
            active = [t for t in timestamps if t > cutoff]
            if not active:
                return 0
            return int(self.window - (now - min(active)))
