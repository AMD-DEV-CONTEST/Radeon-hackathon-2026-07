"""Memory-bounded recent-frame storage and latest-frame queue."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from buildguard.realtime.schemas import FramePriority, VideoFrame


class FrameBuffer:
    def __init__(
        self,
        duration_seconds: float,
        max_frames: int,
        max_memory_mb: float,
    ) -> None:
        if duration_seconds <= 0 or max_frames <= 0 or max_memory_mb <= 0:
            raise ValueError("Frame buffer limits must be positive")
        self.duration_seconds = duration_seconds
        self.max_frames = max_frames
        self.max_memory_bytes = round(max_memory_mb * 1024 * 1024)
        self._frames: deque[VideoFrame] = deque()
        self._memory_bytes = 0
        self._lock = threading.RLock()

    def _remove_at(self, index: int) -> None:
        self._frames.rotate(-index)
        removed = self._frames.popleft()
        self._frames.rotate(index)
        self._memory_bytes -= removed.memory_bytes

    def _evict_oldest_prefer_normal(self) -> None:
        index = next(
            (position for position, frame in enumerate(self._frames) if not frame.key_frame),
            0,
        )
        self._remove_at(index)

    def append(self, frame: VideoFrame) -> None:
        with self._lock:
            self._frames.append(frame)
            self._memory_bytes += frame.memory_bytes
            cutoff = frame.captured_at.timestamp() - self.duration_seconds
            while self._frames and self._frames[0].captured_at.timestamp() < cutoff:
                self._remove_at(0)
            while len(self._frames) > self.max_frames or self._memory_bytes > self.max_memory_bytes:
                self._evict_oldest_prefer_normal()

    def between(self, start: datetime, end: datetime) -> list[VideoFrame]:
        if end < start:
            raise ValueError("Frame interval end must not precede start")
        with self._lock:
            return [
                frame.model_copy(deep=False)
                for frame in self._frames
                if start <= frame.captured_at <= end
            ]

    def latest(self) -> VideoFrame | None:
        with self._lock:
            return self._frames[-1].model_copy(deep=False) if self._frames else None

    @property
    def memory_bytes(self) -> int:
        with self._lock:
            return self._memory_bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)


@dataclass
class _QueuedFrame:
    frame: VideoFrame
    priority: FramePriority
    enqueued_at: float
    expires_at: float | None


class BoundedFrameQueue:
    """Deadline-aware queue that protects key and suspected-risk frames."""

    def __init__(self, max_size: int) -> None:
        if max_size <= 0:
            raise ValueError("Queue size must be positive")
        self.max_size = max_size
        self._items: deque[_QueuedFrame] = deque()
        self._condition = threading.Condition()
        self.dropped_normal_frames = 0
        self.expired_normal_frames = 0
        self.critical_waits = 0
        self.peak_size = 0
        self.last_dequeue_age_ms = 0.0

    def _record_peak(self) -> None:
        self.peak_size = max(self.peak_size, len(self._items))

    def _drop_expired(self, now: float) -> None:
        retained: deque[_QueuedFrame] = deque()
        for item in self._items:
            expired = item.expires_at is not None and now >= item.expires_at
            discardable = item.priority >= FramePriority.NORMAL and not item.frame.key_frame
            if expired and discardable:
                self.expired_normal_frames += 1
                continue
            retained.append(item)
        self._items = retained

    def _evict_for(self, priority: FramePriority) -> bool:
        candidates = [
            (item.priority, -position, position)
            for position, item in enumerate(self._items)
            if not item.frame.key_frame
            and item.priority >= FramePriority.NORMAL
            and item.priority >= priority
        ]
        if not candidates:
            return False
        _, _, position = max(candidates)
        self._items.rotate(-position)
        self._items.popleft()
        self._items.rotate(position)
        self.dropped_normal_frames += 1
        return True

    def put(
        self,
        frame: VideoFrame,
        timeout: float | None = None,
        *,
        priority: FramePriority = FramePriority.NORMAL,
        max_age_seconds: float | None = None,
    ) -> bool:
        if max_age_seconds is not None and max_age_seconds <= 0:
            raise ValueError("frame max age must be positive")
        effective_priority = FramePriority.CRITICAL if frame.key_frame else priority
        with self._condition:
            now = time.monotonic()
            self._drop_expired(now)
            if len(self._items) < self.max_size:
                self._items.append(
                    _QueuedFrame(
                        frame=frame,
                        priority=effective_priority,
                        enqueued_at=now,
                        expires_at=(
                            now + max_age_seconds
                            if max_age_seconds is not None
                            else None
                        ),
                    )
                )
                self._record_peak()
                self._condition.notify_all()
                return True
            if self._evict_for(effective_priority):
                self._items.append(
                    _QueuedFrame(
                        frame=frame,
                        priority=effective_priority,
                        enqueued_at=now,
                        expires_at=(
                            now + max_age_seconds
                            if max_age_seconds is not None
                            else None
                        ),
                    )
                )
                self._record_peak()
                self._condition.notify_all()
                return True
            if effective_priority >= FramePriority.NORMAL:
                self.dropped_normal_frames += 1
                return False
            deadline = None if timeout is None else time.monotonic() + timeout
            self.critical_waits += 1
            while len(self._items) >= self.max_size:
                now = time.monotonic()
                self._drop_expired(now)
                if self._evict_for(effective_priority):
                    break
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("Critical frame queue remained full")
                self._condition.wait(remaining)
            now = time.monotonic()
            self._items.append(
                _QueuedFrame(
                    frame=frame,
                    priority=effective_priority,
                    enqueued_at=now,
                    expires_at=(
                        now + max_age_seconds
                        if max_age_seconds is not None
                        else None
                    ),
                )
            )
            self._record_peak()
            self._condition.notify_all()
            return True

    def get(self, timeout: float | None = None) -> VideoFrame:
        with self._condition:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                now = time.monotonic()
                self._drop_expired(now)
                if self._items:
                    item = self._items.popleft()
                    self.last_dequeue_age_ms = max(
                        0.0,
                        (now - item.enqueued_at) * 1000,
                    )
                    self._condition.notify_all()
                    return item.frame
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("Frame queue is empty")
                self._condition.wait(remaining)

    def __len__(self) -> int:
        with self._condition:
            return len(self._items)

    def metrics(self) -> dict[str, int]:
        with self._condition:
            return {
                "length": len(self._items),
                "max_size": self.max_size,
                "peak_size": self.peak_size,
                "dropped_normal_frames": self.dropped_normal_frames,
                "critical_waits": self.critical_waits,
            }

    def freshness_metrics(self) -> dict[str, int]:
        with self._condition:
            return {
                "expired_normal_frames": self.expired_normal_frames,
                "last_dequeue_age_ms": round(self.last_dequeue_age_ms),
            }
