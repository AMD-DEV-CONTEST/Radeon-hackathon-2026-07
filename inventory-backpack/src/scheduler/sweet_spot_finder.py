"""
Sweet spot detection - automatically find the optimal latency-throughput balance point

Core idea: binary search to find the P99 jump critical point
"""

import asyncio
import logging
import statistics
from dataclasses import dataclass, field
from typing import List, Deque, Optional, Callable, Awaitable
from collections import deque
import time

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweetSpot:
    """Latency-throughput sweet spot"""
    concurrency: int           # Optimal concurrency
    rps: float               # Corresponding throughput
    ttft_p99: float          # P99 first-token latency
    ttft_p50: float          # P50 first-token latency
    tail_ratio: float        # P99/P50
    efficiency: float        # Overall efficiency score

    def is_healthy(self, target_p99: float = 1000.0) -> bool:
        """Whether latency target is met"""
        return self.ttft_p99 <= target_p99 and self.tail_ratio < 3.0


class SweetSpotFinder:
    """
    Sweet spot finder - automatically find optimal concurrency config

    Algorithm: variable-step binary search + jump detection
    """

    def __init__(
        self,
        min_concurrency: int = 3,
        max_concurrency: int = 30,
        target_p99_ms: float = 1000.0,
        max_tail_ratio: float = 3.0,
    ):
        self.min_concurrency = min_concurrency
        self.max_concurrency = max_concurrency
        self.target_p99 = target_p99_ms
        self.max_tail_ratio = max_tail_ratio

        # Cache measured points
        self._cache: dict = {}
        self._measured: List[SweetSpot] = []
    
    async def find(
        self,
        benchmark_func: Callable[[int], Awaitable[dict]],
        precision: int = 2,  # Search precision (concurrency error < 2)
    ) -> SweetSpot:
        """
        Find sweet spot

        Args:
            benchmark_func: benchmark function, takes concurrency and returns performance metrics
            precision: search precision

        Returns:
            Optimal sweet spot config
        """

        # Phase 1: Coarse scan to find jump region
        logger.info("Phase 1: Coarse scan for jump region")
        jump_region = await self._coarse_scan(benchmark_func)

        # Phase 2: Fine binary search
        logger.info(f"Phase 2: Fine search in region {jump_region}")
        sweet_spot = await self._fine_search(benchmark_func, jump_region, precision)

        return sweet_spot

    async def _coarse_scan(
        self,
        benchmark_func: Callable[[int], Awaitable[dict]],
        step: int = 3,
    ) -> tuple:
        """
        Coarse scan - find the region where P99 jumps

        Returns:
            (low_concurrency, high_concurrency) jump region
        """

        concurrencies = list(range(self.min_concurrency, self.max_concurrency + 1, step))

        # Parallel scan (reduce total time)
        tasks = [self._measure_safe(benchmark_func, c) for c in concurrencies]
        results = await asyncio.gather(*tasks)

        # Record results
        for c, result in zip(concurrencies, results):
            if result:
                self._cache[c] = result
                self._measured.append(result)

        # Find jump point: P99 jumps from <1s to >1s
        healthy = [(r.concurrency, r) for r in self._measured if r.is_healthy(self.target_p99)]
        unhealthy = [(r.concurrency, r) for r in self._measured if not r.is_healthy(self.target_p99)]

        if not healthy:
            # All unhealthy, take min concurrency
            return (self.min_concurrency, self.min_concurrency + step)

        if not unhealthy:
            # All healthy, take max
            return (max(r.concurrency for r in self._measured), self.max_concurrency)

        # Find jump boundary
        max_healthy = max(c for c, _ in healthy)
        min_unhealthy = min(c for c, _ in unhealthy)

        return (max_healthy, min_unhealthy)
    
    async def _fine_search(
        self,
        benchmark_func: Callable[[int], Awaitable[dict]],
        region: tuple,
        precision: int,
    ) -> SweetSpot:
        """
        Fine search - binary search for optimal within the jump region
        """

        low, high = region

        while high - low > precision:
            mid = (low + high) // 2

            # Measure midpoint
            result = await self._measure_safe(benchmark_func, mid)

            if result and result.is_healthy(self.target_p99):
                # Healthy, try higher concurrency
                low = mid
            else:
                # Unhealthy, lower concurrency
                high = mid

        # Return optimal result
        best = None
        for c in range(low, high + 1):
            if c in self._cache:
                if best is None or self._cache[c].rps > best.rps:
                    best = self._cache[c]

        return best or self._measured[0]

    async def _measure_safe(
        self,
        benchmark_func: Callable[[int], Awaitable[dict]],
        concurrency: int,
    ) -> Optional[SweetSpot]:
        """Safe measurement, with cache"""
        
        if concurrency in self._cache:
            return self._cache[concurrency]
        
        try:
            result = await benchmark_func(concurrency)
            
            spot = SweetSpot(
                concurrency=concurrency,
                rps=result.get("rps", 0),
                ttft_p99=result.get("ttft_p99", 99999),
                ttft_p50=result.get("ttft_p50", 99999),
                tail_ratio=result.get("tail_ratio", 999),
                efficiency=result.get("rps", 0) / max(result.get("ttft_p99", 1), 1) * 1000,
            )
            
            self._cache[concurrency] = spot
            return spot
            
        except Exception as e:
            logger.error(f"Measurement failed for concurrency={concurrency}: {e}")
            return None
    
    def get_efficiency_frontier(self) -> List[SweetSpot]:
        """
        Get efficiency frontier (Pareto frontier)

        Returns: optimal trade-off curve of latency and throughput
        """

        if not self._measured:
            return []

        # Sort by concurrency
        sorted_spots = sorted(self._measured, key=lambda x: x.concurrency)

        # Pareto frontier: no other point has both higher RPS and lower P99
        frontier = []
        for spot in sorted_spots:
            dominated = False
            for other in sorted_spots:
                if other is spot:
                    continue
                if other.rps >= spot.rps and other.ttft_p99 <= spot.ttft_p99:
                    if other.rps > spot.rps or other.ttft_p99 < spot.ttft_p99:
                        dominated = True
                        break
            
            if not dominated:
                frontier.append(spot)
        
        return frontier


class ContinuousSweetSpotMonitor:
    """
    Continuous monitoring - dynamically detect sweet spot drift

    When the environment changes (e.g. traffic pattern changes), automatically re-detect
    """

    def __init__(
        self,
        finder: SweetSpotFinder,
        check_interval_sec: float = 300.0,  # Check every 5 minutes
        drift_threshold: float = 0.2,       # 20% change triggers re-detection
    ):
        self.finder = finder
        self.check_interval = check_interval_sec
        self.drift_threshold = drift_threshold
        
        self._current_spot: Optional[SweetSpot] = None
        self._baseline_rps: float = 0
        self._baseline_p99: float = 0
        
        self._running = False
    
    async def start(
        self,
        benchmark_func: Callable[[int], Awaitable[dict]],
        on_spot_change: Callable[[SweetSpot], Awaitable],
    ):
        """Start continuous monitoring"""

        self._running = True

        # Initial detection
        self._current_spot = await self.finder.find(benchmark_func)
        self._update_baseline(self._current_spot)

        logger.info(f"Initial sweet spot: {self._current_spot}")

        # Continuous monitoring
        while self._running:
            await asyncio.sleep(self.check_interval)

            # Quick validation of current config
            current = await self._quick_check(benchmark_func)

            # Detect drift
            if self._detect_drift(current):
                logger.warning("Performance drift detected, re-finding sweet spot")

                # Re-detect
                new_spot = await self.finder.find(benchmark_func)

                if new_spot.concurrency != self._current_spot.concurrency:
                    logger.info(f"Sweet spot changed: {self._current_spot} -> {new_spot}")
                    await on_spot_change(new_spot)
                    self._current_spot = new_spot
                    self._update_baseline(new_spot)

    def _update_baseline(self, spot: SweetSpot):
        """Update baseline"""
        self._baseline_rps = spot.rps
        self._baseline_p99 = spot.ttft_p99

    async def _quick_check(self, benchmark_func) -> dict:
        """Quick validation - only test current config"""
        # Simplified: only run a few requests
        return await benchmark_func(self._current_spot.concurrency)

    def _detect_drift(self, current: dict) -> bool:
        """Detect performance drift"""
        if not current:
            return True
        
        rps_drift = abs(current.get("rps", 0) - self._baseline_rps) / max(self._baseline_rps, 1)
        p99_drift = abs(current.get("ttft_p99", 0) - self._baseline_p99) / max(self._baseline_p99, 1)
        
        return rps_drift > self.drift_threshold or p99_drift > self.drift_threshold
    
    def stop(self):
        self._running = False