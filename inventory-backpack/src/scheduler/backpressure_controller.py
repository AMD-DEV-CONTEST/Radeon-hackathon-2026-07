"""
Adaptive backpressure - prevents queue avalanche

Core idea: dynamically adjust admission rate based on real-time TTFT
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Deque, Optional, Callable, Awaitable
from collections import deque
from enum import Enum, auto

logger = logging.getLogger(__name__)


class PressureLevel(Enum):
    """Pressure level"""
    NORMAL = auto()      # Normal, full-speed processing
    ELEVATED = auto()    # Elevated, light rate limiting
    HIGH = auto()        # High pressure, strict rate limiting
    CRITICAL = auto()    # Critical, reject new requests


@dataclass
class BackpressureConfig:
    """Rate limit config"""
    # Latency threshold (ms)
    ttft_p99_threshold_normal: float = 500.0
    ttft_p99_threshold_elevated: float = 1000.0
    ttft_p99_threshold_high: float = 2000.0

    # Corresponding rate limit ratio
    rate_limit_normal: float = 1.0      # 100%
    rate_limit_elevated: float = 0.8   # 80%
    rate_limit_high: float = 0.5       # 50%
    rate_limit_critical: float = 0.1    # 10%

    # Recovery parameters
    recovery_window_ms: float = 5000.0   # 5-second recovery window
    cooldown_ms: float = 1000.0          # State change cooldown


class BackpressureController:
    """
    Adaptive rate limit controller

    Dynamically adjusts admission rate based on real-time P99 TTFT
    """

    def __init__(self, config: Optional[BackpressureConfig] = None):
        self.config = config or BackpressureConfig()

        # State
        self._current_level = PressureLevel.NORMAL
        self._current_rate = 1.0

        # History window
        self._ttft_window: Deque[float] = deque(maxlen=1000)
        self._request_times: Deque[float] = deque()  # Used for RPS calculation

        # Token bucket
        self._tokens = 1.0
        self._last_update = time.monotonic()

        # Lock
        self._lock = asyncio.Lock()
        self._last_state_change = 0
    
    async def acquire(self, tokens: float = 1.0) -> bool:
        """
        Try to acquire processing permit

        Returns:
            True: allowed to process
            False: rejected, service overloaded
        """
        now = time.monotonic()

        async with self._lock:
            # Refill tokens
            elapsed = now - self._last_update
            self._tokens = min(
                1.0 / max(self._current_rate, 0.01),  # Capacity
                self._tokens + elapsed * self._current_rate  # Refill
            )
            self._last_update = now

            # Try to acquire
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True

            return False

    async def report_latency(self, ttft_ms: float):
        """
        Report latency sample

        Automatically adjusts pressure level
        """
        self._ttft_window.append(ttft_ms)
        self._request_times.append(time.monotonic())

        # Clean up expired request times
        cutoff = time.monotonic() - 60  # 60-second window
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

        # Periodic evaluation (every 100 samples)
        if len(self._ttft_window) >= 100 and len(self._ttft_window) % 100 == 0:
            await self._evaluate()

    async def _evaluate(self):
        """Evaluate current pressure state"""

        # Calculate P99
        sorted_ttft = sorted(self._ttft_window)
        p99 = sorted_ttft[int(len(sorted_ttft) * 0.99)]

        # Calculate RPS
        rps = len(self._request_times) / 60.0 if self._request_times else 0

        # Determine new state
        new_level = self._determine_level(p99)

        # State change cooldown
        now = time.monotonic() * 1000
        if now - self._last_state_change < self.config.cooldown_ms:
            return

        if new_level != self._current_level:
            old_level = self._current_level
            self._current_level = new_level
            self._last_state_change = now

            # Update rate limit ratio
            rate_map = {
                PressureLevel.NORMAL: self.config.rate_limit_normal,
                PressureLevel.ELEVATED: self.config.rate_limit_elevated,
                PressureLevel.HIGH: self.config.rate_limit_high,
                PressureLevel.CRITICAL: self.config.rate_limit_critical,
            }
            self._current_rate = rate_map[new_level]

            logger.warning(
                f"Backpressure state: {old_level.name} -> {new_level.name}, "
                f"rate={self._current_rate:.0%}, p99={p99:.0f}ms, rps={rps:.2f}"
            )

    def _determine_level(self, p99: float) -> PressureLevel:
        """Determine pressure level based on P99"""
        
        if p99 > self.config.ttft_p99_threshold_high:
            return PressureLevel.CRITICAL
        elif p99 > self.config.ttft_p99_threshold_elevated:
            return PressureLevel.HIGH
        elif p99 > self.config.ttft_p99_threshold_normal:
            return PressureLevel.ELEVATED
        else:
            return PressureLevel.NORMAL
    
    @property
    def current_state(self) -> dict:
        """Current state"""
        return {
            "level": self._current_level.name,
            "rate_limit": self._current_rate,
            "window_size": len(self._ttft_window),
        }


class AdaptiveRouter:
    """
    Adaptive routing - multi-node load balancing + fallback

    When the primary node is under too much pressure, automatically routes to backup nodes or returns a degraded response
    """

    def __init__(self):
        # Node management
        self._nodes: dict = {}  # node_id -> BackpressureController
        self._node_weights: dict = {}  # Dynamic weights

        # Fallback strategy
        self._fallback_handler: Optional[Callable] = None

    def register_node(self, node_id: str, controller: BackpressureController):
        """Register node"""
        self._nodes[node_id] = controller
        self._node_weights[node_id] = 1.0

    def set_fallback(self, handler: Callable):
        """Set fallback handler"""
        self._fallback_handler = handler

    async def route(self, request: dict) -> Optional[str]:
        """
        Route request to the optimal node

        Returns:
            Node ID, None means fallback is needed
        """

        # Collect each node's state
        healthy_nodes = []

        for node_id, controller in self._nodes.items():
            state = controller.current_state

            if state["level"] == PressureLevel.CRITICAL.name:
                continue  # Skip critical nodes

            weight = self._node_weights.get(node_id, 1.0)

            # Adjust weight by pressure
            if state["level"] == PressureLevel.HIGH.name:
                weight *= 0.5
            elif state["level"] == PressureLevel.ELEVATED.name:
                weight *= 0.8

            healthy_nodes.append((node_id, weight))

        if not healthy_nodes:
            # All overloaded, trigger fallback
            if self._fallback_handler:
                return await self._fallback_handler(request)
            return None

        # Weighted random selection
        total_weight = sum(w for _, w in healthy_nodes)
        r = random.random() * total_weight

        cumulative = 0
        for node_id, weight in healthy_nodes:
            cumulative += weight
            if r <= cumulative:
                return node_id

        return healthy_nodes[-1][0]

    async def get_node_for_request(self) -> Optional[str]:
        """Select node for current request"""
        # Simplified implementation
        return await self.route({})