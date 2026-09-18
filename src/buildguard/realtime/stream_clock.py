"""Monotonic pacing and source-time normalization for video streams."""

from __future__ import annotations

import time
from collections.abc import Callable


class StreamClock:
    """Map local-video presentation timestamps onto a monotonic playback clock."""

    def __init__(
        self,
        *,
        pace: bool,
        playback_speed: float = 1.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if playback_speed <= 0:
            raise ValueError("playback_speed must be positive")
        self.pace = pace
        self.playback_speed = playback_speed
        self.monotonic = monotonic
        self._first_source_time: float | None = None
        self._first_monotonic: float | None = None

    def delay_seconds(self, source_time_seconds: float) -> float:
        if source_time_seconds < 0:
            raise ValueError("source timestamp must be non-negative")
        if not self.pace:
            return 0.0
        now = self.monotonic()
        if self._first_source_time is None or self._first_monotonic is None:
            self._first_source_time = source_time_seconds
            self._first_monotonic = now
            return 0.0
        expected = (
            source_time_seconds - self._first_source_time
        ) / self.playback_speed
        elapsed = now - self._first_monotonic
        return max(0.0, expected - elapsed)

    def reset(self) -> None:
        self._first_source_time = None
        self._first_monotonic = None
