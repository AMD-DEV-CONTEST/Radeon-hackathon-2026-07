"""
Circuit breaker + adaptive rate limiter - prevent cascading failures

Design: when P99 exceeds threshold, fail fast to protect the queue
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
from enum import Enum, auto

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = auto()      # Normal
    OPEN = auto()        # Tripped, reject requests
    HALF_OPEN = auto()   # Probing


@dataclass
class LatencyWindow:
    """Latency window - precise P99 computation"""
    size: int = 100
    _latencies: list = field(default_factory=list)
    _index: int = 0
    
    def add(self, latency_ms: float):
        if len(self._latencies) < self.size:
            self._latencies.append(latency_ms)
        else:
            self._latencies[self._index] = latency_ms
            self._index = (self._index + 1) % self.size
    
    @property
    def p99(self) -> float:
        if not self._latencies:
            return 0.0
        sorted_lat = sorted(self._latencies)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[min(idx, len(sorted_lat)-1)]
    
    @property
    def p95(self) -> float:
        if not self._latencies:
            return 0.0
        sorted_lat = sorted(self._latencies)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat)-1)]
    
    @property
    def avg(self) -> float:
        return sum(self._latencies) / max(len(self._latencies), 1)


class AdaptiveLimiter:
    """
    Adaptive rate limiter - dynamically adjusts based on P99
    
    Algorithm: TCP-like congestion control
    - P99 < target: slowly increase concurrency
    - P99 > target: quickly decrease concurrency
    """
    
    def __init__(
        self,
        initial_limit: int = 20,
        min_limit: int = 5,
        max_limit: int = 100,
        target_p99_ms: float = 800.0,
        increase_step: int = 1,
        decrease_factor: float = 0.7,
    ):
        self.target_p99_ms = target_p99_ms
        self.min_limit = min_limit
        self.max_limit = max_limit
        self.increase_step = increase_step
        self.decrease_factor = decrease_factor
        
        self._current_limit = initial_limit
        self._window = LatencyWindow(size=100)
        self._lock = asyncio.Lock()
        self._active = 0
    
    async def acquire(self) -> bool:
        """Try to acquire a permit"""
        async with self._lock:
            if self._active >= self._current_limit:
                return False
            self._active += 1
            return True
    
    async def release(self, latency_ms: float):
        """Release and report latency"""
        async with self._lock:
            self._active -= 1
            self._window.add(latency_ms)
            
            # Dynamic adjustment
            p99 = self._window.p99
            
            if p99 > self.target_p99_ms * 1.5:
                # Severely exceeds limit, fast downgrade
                self._current_limit = max(
                    int(self._current_limit * self.decrease_factor),
                    self.min_limit
                )
                logger.warning(
                    f"Limiter DOWN: {self._current_limit} "
                    f"(p99={p99:.1f}ms > {self.target_p99_ms:.1f}ms)"
                )
            
            elif p99 < self.target_p99_ms * 0.8 and self._current_limit < self.max_limit:
                # Performance headroom, slowly increase
                self._current_limit = min(
                    self._current_limit + self.increase_step,
                    self.max_limit
                )
    
    @property
    def current_limit(self) -> int:
        return self._current_limit


class CircuitBreaker:
    """
    Circuit breaker - prevent cascading failures
    
    State machine:
    CLOSED -> (failure rate>) -> OPEN -> (timeout) -> HALF_OPEN -> (success) -> CLOSED
    """
    
    def __init__(
        self,
        failure_threshold: float = 0.5,
        recovery_timeout: float = 5.0,
        half_open_max: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._successes = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()
    
    async def call(self, func: Callable[..., Awaitable], *args, **kwargs):
        """Execute a protected call"""
        
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_count = 0
                else:
                    raise CircuitOpenError("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
            
        except Exception as e:
            await self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        if self._last_failure_time is None:
            return True
        
        elapsed = time.monotonic() - self._last_failure_time
        return elapsed >= self.recovery_timeout
    
    async def _on_success(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_count += 1
                if self._half_open_count >= self.half_open_max:
                    self._state = CircuitState.CLOSED
                    self._failures = 0
            else:
                self._successes += 1
    
    async def _on_failure(self):
        async with self._lock:
            self._failures += 1
            self._last_failure_time = time.monotonic()
            
            total = self._failures + self._successes
            if total > 0 and self._failures / total > self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.error(f"Circuit OPENED: {self._failures}/{total} failures")
    
    @property
    def state(self) -> CircuitState:
        return self._state


class CircuitOpenError(Exception):
    pass
