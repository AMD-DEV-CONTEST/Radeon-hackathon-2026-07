"""Stage J — TTL-based Cache with invalidation for index, embedding, and reports.

Provides a thread-safe, in-memory cache with distinct TTL windows per content
type (index / embedding / report).  Supports manual invalidation by key prefix
so that stale entries are purged when source data changes.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any

from app.config import Settings


class TTLCache:
    """Thread-safe TTL cache with LRU eviction and prefix-based invalidation.

    Each entry stores ``(value, expires_at)``.  Entries are evicted on access
    if expired, and the overall cache size is capped at ``max_entries``.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.RLock()

        # TTL per category (seconds)
        self._ttls: dict[str, int] = {
            "index": settings.cache_index_ttl_seconds,
            "embedding": settings.cache_embedding_ttl_seconds,
            "report": settings.cache_report_ttl_seconds,
        }
        self._max_entries = settings.cache_max_entries

        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._enabled = settings.cache_enabled

        # Metrics
        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        """Retrieve a cached value, or *None* if absent/expired."""
        if not self._enabled:
            return None

        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None

            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                self._evictions += 1
                self._misses += 1
                return None

            # LRU: move to end
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any, category: str = "index") -> None:
        """Store *value* under *key* with a TTL derived from *category*."""
        if not self._enabled or not key:
            return

        ttl = self._ttls.get(category, self._ttls["index"])
        expires_at = time.time() + ttl

        with self._lock:
            # Evict oldest if at capacity
            while len(self._store) >= self._max_entries:
                self._store.popitem(last=False)
                self._evictions += 1

            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)

    def invalidate(self, key_prefix: str) -> int:
        """Remove all entries whose key starts with *key_prefix*.

        Returns:
            Number of entries removed.
        """
        with self._lock:
            to_remove = [k for k in self._store if k.startswith(key_prefix)]
            for k in to_remove:
                del self._store[k]
            return len(to_remove)

    def invalidate_project(self, project_id: str) -> int:
        """Invalidate all cached entries for a given *project_id*."""
        return self.invalidate(f"project:{project_id}:")

    def invalidate_category(self, category: str) -> int:
        """Invalidate all cached entries for a given cache *category*."""
        total = 0
        with self._lock:
            prefix_map = {
                "index": "index:",
                "embedding": "embedding:",
                "report": "report:",
            }
            prefix = prefix_map.get(category, "")
            if prefix:
                to_remove = [k for k in self._store if prefix in k]
                for k in to_remove:
                    del self._store[k]
                total = len(to_remove)
        return total

    def clear(self) -> int:
        """Remove all entries."""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    # ------------------------------------------------------------------
    # statistics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        with self._lock:
            size = len(self._store)
        return {
            "enabled": self._enabled,
            "size": size,
            "max_entries": self._max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / max(total, 1), 4),
            "evictions": self._evictions,
            "ttls": dict(self._ttls),
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    # ------------------------------------------------------------------
    # key builders
    # ------------------------------------------------------------------

    @staticmethod
    def build_index_key(project_id: str, query_hash: str) -> str:
        return f"project:{project_id}:index:{query_hash}"

    @staticmethod
    def build_embedding_key(project_id: str, content_hash: str) -> str:
        return f"project:{project_id}:embedding:{content_hash}"

    @staticmethod
    def build_report_key(project_id: str, report_id: str) -> str:
        return f"project:{project_id}:report:{report_id}"

    @staticmethod
    def hash_content(content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()[:16]


# Module-level singleton
_cache_instance: TTLCache | None = None


def get_cache(settings: Settings | None = None) -> TTLCache:
    """Return the module-level TTLCache singleton."""
    global _cache_instance
    if _cache_instance is None:
        if settings is None:
            settings = Settings()
        _cache_instance = TTLCache(settings)
    return _cache_instance
