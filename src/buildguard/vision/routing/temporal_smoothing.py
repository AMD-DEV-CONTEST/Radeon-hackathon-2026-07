"""Thread-safe per-track probability smoothing."""

from __future__ import annotations

import threading


class TemporalProbabilitySmoother:
    def __init__(self, alpha: float) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("temporal alpha must be within (0, 1]")
        self.alpha = alpha
        self._history: dict[str, dict[str, float]] = {}
        self._lock = threading.RLock()

    def smooth(
        self,
        temporal_key: str,
        current: dict[str, float],
        *,
        initial_previous: float | None = None,
    ) -> dict[str, float]:
        if not temporal_key:
            raise ValueError("temporal_key must not be empty")
        if any(value < 0 or value > 1 for value in current.values()):
            raise ValueError("probabilities must be within 0..1")
        if initial_previous is not None and not 0 <= initial_previous <= 1:
            raise ValueError("initial_previous must be within 0..1")
        with self._lock:
            previous = self._history.get(temporal_key, {})
            smoothed = {
                name: (
                    self.alpha * probability
                    + (1.0 - self.alpha)
                    * previous.get(
                        name,
                        probability if initial_previous is None else initial_previous,
                    )
                )
                for name, probability in current.items()
            }
            self._history[temporal_key] = dict(smoothed)
            return smoothed

    def reset(self, temporal_key: str | None = None) -> None:
        with self._lock:
            if temporal_key is None:
                self._history.clear()
            else:
                self._history.pop(temporal_key, None)
