#!/usr/bin/env python3
"""
LLM Streaming Benchmark Tool - Complete Version
Supports streaming stress testing for OpenAI-compatible APIs
"""

import asyncio
import json
import random
import socket
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
from collections import defaultdict

import aiohttp
import click


# ==================== Configuration Constants ====================

TPS_THRESHOLD = 50000       # TPS filter threshold (prevents cache hit interference)
WARMUP_RATIO = 0.05         # Warmup filter ratio
MAX_RETRIES = 1            # Max retry attempts per request
RETRY_BASE_DELAY = 0.1      # Base delay between retries (seconds)
PREWARM_CONNECTIONS = 5    # Number of connections to pre-establish

# Dynamic concurrency control
TTFT_HIGH_WATERMARK = 500   # ms - reduce concurrency when TTFT exceeds this
TTFT_LOW_WATERMARK = 150   # ms - increase concurrency when TTFT drops below this
TTFT_WINDOW_SIZE = 20       # number of recent requests to track
MIN_CONCURRENCY = 1         # floor for dynamic concurrency
CONCURRENCY_ADJUST_INTERVAL = 0.5  # seconds between adjustments

# Adaptive timeout
BASE_TIMEOUT = 5            # base connect timeout (seconds)
JITTER_TIMEOUT = 5         # extended timeout when jitter detected (seconds)
JITTER_THRESHOLD = 0.5      # CV threshold to trigger extended timeout

# Cooldown for third-party hosted APIs (prevents cumulative server exhaustion)
DEFAULT_COOLDOWN = 60       # seconds between runs
MAX_RETRIES_PER_REQUEST = 3 # cap retries for hosted APIs

# Error classification
RETRYABLE_ERRORS = {"timeout", "connection", "cancelled"}
ERROR_TYPES = {
    "timeout": ["timeout", "timed out", "time out", "Server disconnected"],
    "connection": ["connection", "connect", "refused", "reset", "broken", "RemoteDisconnected"],
    "http_5xx": ["500", "502", "503", "504", "HTTP 5"],
    "http_4xx": ["400", "401", "403", "404", "429", "HTTP 4"],
    "json": ["JSON", "decode", "parse"],
    "cancelled": ["cancel", "abort"],
    "other": [],
}


# ==================== Data Structures ====================

@dataclass
class TokenLatency:
    """Latency information for a single token (used for inter-token latency analysis)"""
    token_index: int = 0
    timestamp_ms: float = 0.0
    content: str = ""


@dataclass
class StreamMetrics:
    """Complete metrics for a single request"""
    # Basic latency
    ttft_ms: float = 0.0                    # Time To First Token
    tpot_ms: float = 0.0                    # Time Per Output Token (avg)
    itl_list: List[float] = field(default_factory=list)  # Inter-Token Latency list

    # Generation phase
    generation_ms: float = 0.0
    total_ms: float = 0.0

    # Token statistics
    tokens_input: int = 0                   # Input token count (estimated)
    tokens_output: int = 0
    tokens_total: int = 0

    # Throughput
    tps: float = 0.0                        # tokens per second

    # Streaming quality
    first_token_content: str = ""           # First token content (detect if empty)
    token_variance: float = 0.0             # Token output interval variance

    # Errors
    error: Optional[str] = None
    error_type: Optional[str] = None

    # Metadata
    start_time: float = 0.0
    end_time: float = 0.0
    attempts: int = 1
    retry_count: int = 0
    
    @property
    def is_valid(self) -> bool:
        return (
            self.error is None 
            and self.tokens_output > 0 
            and 0 < self.tps < TPS_THRESHOLD
            and self.ttft_ms > 0
        )
    
    @property
    def latency_total_ms(self) -> float:
        return self.ttft_ms + self.generation_ms


@dataclass
class LatencyDistribution:
    """Latency distribution statistics"""
    p50: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    mean: float = 0.0
    std: float = 0.0
    cv: float = 0.0  # Coefficient of variation = std/mean
    # Winsorized stats (clip top/bottom 1% to filter outliers)
    winsor_mean: float = 0.0
    winsor_std: float = 0.0
    winsor_cv: float = 0.0
    winsor_max: float = 0.0

    @classmethod
    def from_data(cls, data: List[float]) -> "LatencyDistribution":
        if not data:
            return cls()
        sorted_data = sorted(data)
        n = len(sorted_data)

        def _p(pct):
            idx = int(n * pct / 100)
            return sorted_data[min(idx, n - 1)]

        mean = statistics.mean(data)
        std = statistics.stdev(data) if n > 1 else 0

        # Winsorized: clip top/bottom 1% to remove extreme outliers
        lo_idx = max(1, int(n * 0.01))
        hi_idx = n - lo_idx
        clip_lo = sorted_data[lo_idx]
        clip_hi = sorted_data[hi_idx]
        winsor_data = [max(clip_lo, min(clip_hi, v)) for v in data]
        winsor_mean = statistics.mean(winsor_data)
        winsor_std = statistics.stdev(winsor_data) if n > 1 else 0
        winsor_cv = winsor_std / winsor_mean if winsor_mean > 0 else 0

        return cls(
            p50=_p(50), p90=_p(90), p95=_p(95), p99=_p(99),
            min_val=min(data), max_val=max(data),
            mean=mean, std=std, cv=std / mean if mean > 0 else 0,
            winsor_mean=winsor_mean, winsor_std=winsor_std,
            winsor_cv=winsor_cv, winsor_max=clip_hi,
        )


@dataclass
class BenchmarkReport:
    """Complete benchmark report"""
    # Request statistics
    count: int = 0
    valid_count: int = 0
    error_count: int = 0
    timeout_count: int = 0

    # Time
    duration: float = 0.0
    rps: float = 0.0

    # Latency distribution (unit: ms)
    ttft: "LatencyDistribution" = field(default_factory=LatencyDistribution)
    tpot: "LatencyDistribution" = field(default_factory=LatencyDistribution)
    generation_time: "LatencyDistribution" = field(default_factory=LatencyDistribution)
    total_latency: "LatencyDistribution" = field(default_factory=LatencyDistribution)
    inter_token: "LatencyDistribution" = field(default_factory=LatencyDistribution)

    # Throughput
    tps: "LatencyDistribution" = field(default_factory=LatencyDistribution)

    # Token statistics
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    avg_output_tokens: float = 0.0

    # Error classification
    errors_by_type: Dict[str, int] = field(default_factory=dict)
    
    # Retry statistics
    total_retries: int = 0
    retried_success: int = 0

    # Raw data (for later analysis)
    ttft_list: List[float] = field(default_factory=list)
    tps_list: List[float] = field(default_factory=list)
    error_list: List[str] = field(default_factory=list)

    def _calc_distribution(self, data: List[float]) -> "LatencyDistribution":
        return LatencyDistribution.from_data(data)

    def finalize(self):
        """Calculate all distributions"""
        if self.ttft_list:
            self.ttft = self._calc_distribution(self.ttft_list)
        if self.tps_list:
            self.tps = self._calc_distribution(self.tps_list)
    
    def print(self):
        print(f"\n{'='*70}")
        print(f"📊  LLM STREAMING BENCHMARK REPORT")
        print(f"{'='*70}")
        
        # Request overview
        success_rate = (self.valid_count / self.count * 100) if self.count > 0 else 0
        retry_rate = (self.total_retries / self.count * 100) if self.count > 0 else 0
        print(f"\n📋 Request Summary")
        print(f"   Total Requests:     {self.count}")
        print(f"   Valid Responses:    {self.valid_count} ({success_rate:.1f}%)")
        print(f"   Errors:             {self.error_count} ({self.error_count/self.count*100:.2f}%)" if self.count > 0 else "   Errors:             0")
        print(f"   Timeouts:           {self.timeout_count}")
        print(f"   Duration:           {self.duration:.2f}s")
        print(f"   Throughput (RPS):   {self.rps:.2f}")
        if self.total_retries > 0:
            print(f"   Retries:            {self.total_retries} total "
                  f"(recovered: {self.retried_success}, rate: {retry_rate:.1f}%)")
        
        # Token statistics
        print(f"\n📝 Token Statistics")
        print(f"   Total Input:        {self.total_input_tokens:,}")
        print(f"   Total Output:       {self.total_output_tokens:,}")
        print(f"   Avg Output/Req:     {self.avg_output_tokens:.1f}")

        # TTFT analysis
        print(f"\n⏱️  Time To First Token (TTFT) [ms]")
        print(f"   Min/Mean/P50/P90/P95/P99/Max")
        print(f"   {self.ttft.min_val:.1f} / {self.ttft.mean:.1f} / {self.ttft.p50:.1f} / "
              f"{self.ttft.p90:.1f} / {self.ttft.p95:.1f} / {self.ttft.p99:.1f} / {self.ttft.max_val:.1f}")
        print(f"   StdDev: {self.ttft.std:.2f} | CV: {self.ttft.cv:.3f}")
        print(f"   Winsorized (1% clip): CV={self.ttft.winsor_cv:.3f} | Max={self.ttft.winsor_max:.1f}ms")
        
        # Generation analysis
        print(f"\n🔄 Generation Phase [ms]")
        print(f"   Mean Time:          {self.generation_time.mean:.2f}")
        print(f"   TPOT (avg):         {self.tpot.mean:.3f}")
        print(f"   Inter-Token StdDev: {self.inter_token.std:.3f}")
        
        # End-to-end latency
        print(f"\n🌐 End-to-End Latency [ms]")
        print(f"   Mean/P95/P99:       {self.total_latency.mean:.1f} / "
              f"{self.total_latency.p95:.1f} / {self.total_latency.p99:.1f}")

        # Throughput
        print(f"\n🚀 Throughput (tokens/sec)")
        print(f"   Mean/P50/P90/P99:   {self.tps.mean:.2f} / {self.tps.p50:.2f} / "
              f"{self.tps.p90:.2f} / {self.tps.p99:.2f}")

        # Error analysis
        if self.errors_by_type:
            print(f"\n⚠️  Error Breakdown")
            for err_type, count in sorted(self.errors_by_type.items(), key=lambda x: -x[1]):
                print(f"   {err_type:15s}     {count}")
        
        # Retry summary
        if self.total_retries > 0:
            print(f"\n🔄 Retry Summary")
            print(f"   Total Retries:    {self.total_retries}")
            print(f"   Recovered:        {self.retried_success} (success after retry)")
            if self.count > 0:
                print(f"   Recovery Rate:    {self.retried_success/(self.count-self.error_count)*100:.1f}%" if self.count > self.error_count else f"   Recovery Rate:    N/A")
        
        # Quality assessment
        print(f"\n📈 Quality Assessment")
        issues = []
        if self.ttft.winsor_cv > 1.0:
            issues.append(f"🔴 TTFT Winsor-CV={self.ttft.winsor_cv:.2f} (high jitter) - reduce concurrency or fix server-side latency")
        elif self.ttft.winsor_cv > 0.5:
            issues.append(f"🟡 TTFT Winsor-CV={self.ttft.winsor_cv:.2f} (moderate jitter)")
        else:
            issues.append(f"🟢 TTFT Winsor-CV={self.ttft.winsor_cv:.2f} (low variance, stable)")

        if self.ttft.max_val > self.ttft.p99 * 2:
            outlier_pct = sum(1 for v in self.ttft_list if v > self.ttft.p99 * 2) / max(len(self.ttft_list), 1) * 100
            issues.append(f"� TTFT Max ({self.ttft.max_val:.0f}ms) >> P99 ({self.ttft.p99:.0f}ms) "
                          f"- {outlier_pct:.3f}% extreme outliers (infrastructural, not client-fixable)")
        
        if self.inter_token.cv > 1.0:
            issues.append(f"⚠️  Token output interval unstable (CV={self.inter_token.cv:.2f})")
        
        if self.error_count > self.count * 0.05:
            issues.append(f"🔴 Error rate high ({self.error_count/self.count*100:.1f}%) - check server health")
        
        for issue in issues:
            print(f"   {issue}")
        
        # Optimization suggestions
        suggestions = []
        if self.ttft.max_val > 3000:
            suggestions.append("TTFT Max > 3s: Consider reducing concurrency or scaling server resources")
        if self.ttft.cv > 1.0:
            suggestions.append("High TTFT variance: Try enabling TCP_NODELAY, reducing concurrency, or using a single connection pool")
        if self.error_count > self.count * 0.02:
            suggestions.append("Elevated error rate: Check server logs for OOM, rate limits, or network issues")
        if self.total_retries > 0:
            suggestions.append(f"{self.total_retries} retries happened: Some requests needed retry to succeed")
        if self.duration > 0 and self.rps < self.count / self.duration * 0.8:
            suggestions.append("Throughput below potential: Consider connection pool optimization")
        
        if suggestions:
            print(f"\n💡 Optimization Suggestions:")
            for s in suggestions:
                print(f"   • {s}")
        
        print(f"{'='*70}")


# ==================== Low-Latency TCP Connector ====================

class LowLatencyConnector(aiohttp.TCPConnector):
    """TCPConnector with TCP_NODELAY (disables Nagle's algorithm)"""
    
    async def _create_direct_connection(self, req, traces, timeout):
        transport, protocol = await super()._create_direct_connection(req, traces, timeout)
        sock = transport.get_extra_info('socket')
        if sock is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (OSError, AttributeError):
                pass
        return transport, protocol


# ==================== Dynamic Concurrency Controller ====================

class DynamicConcurrencyController:
    """Monitors TTFT in real-time and adjusts concurrency to minimize outliers.

    - When recent TTFT > high watermark: reduce concurrency (queue is building up)
    - When recent TTFT < low watermark: increase concurrency (server has headroom)
    - Tracks a sliding window of TTFT values for responsive adjustment
    """

    def __init__(self, initial_concurrency: int, max_concurrency: int):
        self._target = initial_concurrency
        self._max = max_concurrency
        self._min = MIN_CONCURRENCY
        self._ttft_window: list[float] = []
        self._window_size = TTFT_WINDOW_SIZE
        self._adjustments = 0
        self._current_sem = asyncio.Semaphore(initial_concurrency)

    def record_ttft(self, ttft_ms: float):
        """Record a TTFT sample and adjust concurrency if needed."""
        self._ttft_window.append(ttft_ms)
        if len(self._ttft_window) > self._window_size:
            self._ttft_window.pop(0)

        if len(self._ttft_window) < 10:
            return

        recent_mean = statistics.mean(self._ttft_window)
        recent_max = max(self._ttft_window)

        # High TTFT → reduce concurrency to drain queue
        if recent_mean > TTFT_HIGH_WATERMARK or recent_max > TTFT_HIGH_WATERMARK * 3:
            new_target = max(self._min, self._target - 1)
            if new_target != self._target:
                self._adjustments += 1
                self._target = new_target
                self._rebuild_semaphore()
                return f"↓ reduce to c={self._target} (TTFT mean={recent_mean:.0f}ms max={recent_max:.0f}ms)"

        # Low TTFT → increase concurrency if we have headroom
        elif recent_mean < TTFT_LOW_WATERMARK and recent_max < TTFT_LOW_WATERMARK * 2:
            new_target = min(self._max, self._target + 1)
            if new_target != self._target:
                self._adjustments += 1
                self._target = new_target
                self._rebuild_semaphore()
                return f"↑ increase to c={self._target} (TTFT mean={recent_mean:.0f}ms)"

        return None

    def _rebuild_semaphore(self):
        """Rebuild semaphore with new concurrency limit."""
        self._current_sem = asyncio.Semaphore(self._target)

    @property
    def current_concurrency(self) -> int:
        return self._target

    @property
    def total_adjustments(self) -> int:
        return self._adjustments

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._current_sem

    def get_stats(self) -> dict:
        if not self._ttft_window:
            return {"concurrency": self._target, "adjustments": self._adjustments}
        return {
            "concurrency": self._target,
            "adjustments": self._adjustments,
            "recent_ttft_mean": statistics.mean(self._ttft_window),
            "recent_ttft_max": max(self._ttft_window),
        }


# ==================== Core Benchmark Class ====================

class LLMBenchmark:
    def __init__(self, base_url: str, model: str, api_key: Optional[str] = None,
                 max_connections: int = 100, timeout: int = 120,
                 hosted_mode: bool = False):
        # Handle URL: preserve the full path entered by the user
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            if "/v1" not in self.base_url:
                self.base_url += "/v1"

        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.hosted_mode = hosted_mode  # Third-party API mode

        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

        self._max_connections = max_connections
        self._session = None
        self._connector = None

        # Adaptive concurrency state
        self._current_concurrency = max_connections
        self._recent_errors = 0
        self._recent_requests = 0
        self._error_window_start = 0
        
        # Pre-warmed connections
        self._prewarmed = False

    def _classify_error(self, error_msg: str) -> str:
        """Classify error type with priority ordering"""
        error_lower = error_msg.lower()
        for err_type in ["http_5xx", "http_4xx", "timeout", "connection", "cancelled", "json"]:
            keywords = ERROR_TYPES[err_type]
            if any(kw.lower() in error_lower for kw in keywords):
                return err_type
        return "other"

    def _build_connector(self) -> LowLatencyConnector:
        """Build optimized TCP connector with TCP_NODELAY for low latency"""
        return LowLatencyConnector(
            limit=self._max_connections * 2,
            limit_per_host=self._max_connections * 2,
            force_close=False,
            keepalive_timeout=60.0,
            enable_cleanup_closed=True,
            ssl=False,
        )

    def _build_timeout(self, extended: bool = False) -> aiohttp.ClientTimeout:
        """Build optimized timeout config.

        Args:
            extended: use longer sock_read when jitter detected (10s vs 5s base)
        """
        connect_timeout = JITTER_TIMEOUT if extended else BASE_TIMEOUT
        return aiohttp.ClientTimeout(
            total=300,             # Max total time
            connect=connect_timeout,
            sock_connect=connect_timeout,
            sock_read=120,         # Socket read timeout (streaming tolerance)
        )

    async def _prewarm_connections(self, session: aiohttp.ClientSession) -> bool:
        """Pre-establish connections to the server (DNS resolve + TCP handshake)"""
        if self._prewarmed:
            return True

        test_payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }

        for i in range(PREWARM_CONNECTIONS):
            try:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=test_payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=15, connect=5)
                ) as resp:
                    if resp.status == 200:
                        self._prewarmed = True
                        return True
                    elif resp.status == 404:
                        self._prewarmed = True
                        return True
            except Exception:
                continue

        self._prewarmed = True  # Still mark as prewarmed to avoid repeated attempts
        return False

    async def _keepalive_loop(self, session: aiohttp.ClientSession, stop_event: asyncio.Event):
        """Background task: send periodic minimal requests to keep model in GPU memory.

        Runs during benchmark idle gaps to prevent cold-start penalties.
        """
        keepalive_payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "ok"}],
            "max_tokens": 1,
            "stream": False,
        }
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2.0)
                break  # stop_event was set
            except asyncio.TimeoutError:
                pass  # 2s elapsed, send keepalive
            try:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=keepalive_payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=5, connect=3),
                ) as resp:
                    pass  # Just need the request to reach the server
            except Exception:
                pass  # Keepalive failures are non-critical

    def _should_retry(self, error_type: str, retries_done: int) -> bool:
        """Decide whether to retry based on error type and retry count"""
        if retries_done >= MAX_RETRIES:
            return False
        if error_type in RETRYABLE_ERRORS:
            return True
        if error_type == "http_5xx":
            return True
        return False

    async def _stream_request(self, session: aiohttp.ClientSession,
                              prompt: str, max_tokens: int,
                              temperature: float = 0.0) -> StreamMetrics:
        """Execute a single streaming request with retry logic"""
        m = StreamMetrics()
        m.start_time = time.perf_counter()
        m.tokens_input = len(prompt) // 4

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        last_error = None
        max_retries = 1 if self.hosted_mode else MAX_RETRIES  # Reduce retries for third-party APIs

        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.05)
                await asyncio.sleep(delay)
                # Reset timing for retry
                m = StreamMetrics()
                m.start_time = time.perf_counter()
                m.tokens_input = len(prompt) // 4
            
            token_timestamps = []
            first_token_time = None
            first_token_content = ""
            
            try:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self.headers
                ) as resp:
                    
                    if resp.status == 429:
                        m.error = f"Rate limited (HTTP 429)"
                        m.error_type = "http_4xx"
                        return m
                    
                    if resp.status == 401 or resp.status == 403:
                        body = await resp.text()
                        m.error = f"Auth error (HTTP {resp.status}): {body[:200]}"
                        m.error_type = "http_4xx"
                        return m
                    
                    if resp.status != 200:
                        body = await resp.text()
                        m.error = f"HTTP {resp.status}: {body[:200]}"
                        m.error_type = self._classify_error(m.error)
                        if self._should_retry(m.error_type, attempt):
                            last_error = m.error
                            continue
                        return m
                    
                    async for line in resp.content:
                        line = line.decode('utf-8').strip()
                        if not line.startswith("data: "):
                            continue
                        
                        chunk = line[6:]
                        if chunk == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(chunk)
                            choices = data.get("choices", [{}])
                            delta = choices[0].get("delta", {}) if choices else {}
                            
                            if "content" in delta and delta["content"]:
                                now = time.perf_counter()
                                content = delta["content"]
                                
                                if first_token_time is None:
                                    first_token_time = now
                                    first_token_content = content
                                
                                token_timestamps.append(now)
                                m.tokens_output += 1
                                
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue
                
                m.end_time = time.perf_counter()
                m.total_ms = (m.end_time - m.start_time) * 1000
                
                if first_token_time:
                    m.ttft_ms = (first_token_time - m.start_time) * 1000
                    m.generation_ms = (m.end_time - first_token_time) * 1000
                    
                    if len(token_timestamps) > 1:
                        m.itl_list = [
                            (token_timestamps[i+1] - token_timestamps[i]) * 1000
                            for i in range(len(token_timestamps) - 1)
                        ]
                        m.tpot_ms = statistics.mean(m.itl_list) if m.itl_list else 0
                        m.token_variance = statistics.stdev(m.itl_list) if len(m.itl_list) > 1 else 0
                
                m.tps = (m.tokens_output / m.generation_ms * 1000) if m.generation_ms > 0 else 0
                m.tokens_total = m.tokens_input + m.tokens_output
                m.first_token_content = first_token_content
                m.attempts = attempt + 1
                
                if attempt > 0:
                    m.retry_count = attempt
                
                return m
                
            except asyncio.TimeoutError:
                m.error = "Request timeout"
                m.error_type = "timeout"
                if self._should_retry(m.error_type, attempt):
                    last_error = m.error
                    continue
            except aiohttp.ClientConnectorError as e:
                m.error = f"Connection error: {str(e)[:200]}"
                m.error_type = "connection"
                if self._should_retry(m.error_type, attempt):
                    last_error = m.error
                    continue
            except Exception as e:
                m.error = str(e)[:200]
                m.error_type = self._classify_error(m.error)
                if self._should_retry(m.error_type, attempt):
                    last_error = m.error
                    continue
        
        # All retries exhausted
        if last_error:
            m.error = f"Failed after {MAX_RETRIES + 1} attempts: {last_error}"
        m.error_type = self._classify_error(m.error or "max retries exceeded")
        return m

    async def run(self, concurrency: int, total_requests: int,
                  max_tokens: int, prompt: str = None,
                  temperature: float = 0.0,
                  dynamic: bool = False) -> BenchmarkReport:
        """Execute benchmark with optimized connection management.

        Args:
            dynamic: enable dynamic concurrency control (auto-adjust based on TTFT)
        """
        report = BenchmarkReport()
        prompts = [prompt or "Explain quantum computing in simple terms."] * total_requests

        connector = self._build_connector()
        timeout_cfg = self._build_timeout()

        warmup_count = int(total_requests * WARMUP_RATIO)
        results_collected = []
        first_error_printed = False
        self._prewarmed = False
        self._current_concurrency = concurrency

        # Dynamic concurrency controller
        dyn_ctrl = None
        if dynamic:
            dyn_ctrl = DynamicConcurrencyController(
                initial_concurrency=concurrency,
                max_concurrency=concurrency * 3,
            )
            print(f"  🎛️  Dynamic concurrency: ON (initial c={concurrency}, max c={concurrency*3})")
            print(f"     High watermark: {TTFT_HIGH_WATERMARK}ms | Low watermark: {TTFT_LOW_WATERMARK}ms")

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout_cfg
        ) as session:
            self._session = session
            self._connector = connector
            
            # Phase 1: Test connectivity
            print(f"  🔍 Testing connection to {self.base_url}/chat/completions ...")
            test_result = await self._stream_request(session, prompts[0], max_tokens)
            if test_result.error:
                print(f"  ❌ Connection test FAILED: {test_result.error[:200]}")
                print(f"     Error type: {test_result.error_type}")
                print(f"     URL: {self.base_url}/chat/completions")
                print(f"     Model: {self.model}")
                print(f"     API Key: {'***' if self.api_key else 'None'}")
                
                if test_result.error_type == "http_4xx":
                    print(f"\n  ❌ FATAL: Authentication/client error detected.")
                    print(f"     This error will NOT improve with retries or more requests.")
                    print(f"     Use these commands to diagnose:")
                    print(f"     # Test models endpoint:")
                    print(f"     curl -H 'Authorization: Bearer YOUR_KEY' \\")
                    print(f"       '{self.base_url}/models'")
                    print(f"     # Test chat completion:")
                    print(f"     curl -H 'Authorization: Bearer YOUR_KEY' \\")
                    print(f"       '{self.base_url}/chat/completions' \\")
                    print(f"       -d '{{\"model\":\"{self.model}\",\"messages\":[{{\"role\":\"user\",\"content\":\"hi\"}}]}}'")
                    print(f"\n  ❌ Skipping benchmark — 10000 requests would ALL fail.\n")
                    report.duration = 0
                    return report
                elif test_result.error_type in ("timeout", "connection"):
                    print(f"     ⚠️  Network issue detected. Check if server is reachable.")
                    print(f"     ⚠️  Continuing but expect high failure rate...\n")
                else:
                    print(f"     ⚠️  Continuing benchmark anyway...\n")
            else:
                print(f"  ✅ Connection OK! TTFT: {test_result.ttft_ms:.0f}ms, "
                      f"output tokens: {test_result.tokens_output}\n")
            
            # Phase 2: Pre-warm connections (establish TCP/TLS handshake)
            print(f"  🔌 Pre-warming {PREWARM_CONNECTIONS} connections...")
            prewarm_ok = await self._prewarm_connections(session)
            if prewarm_ok:
                print(f"  ✅ Connections pre-warmed successfully")
            else:
                print(f"  ⚠️  Some pre-warm connections failed (may affect latency)")

            # Phase 2b: Start keepalive background task (prevents model cold-start)
            keepalive_stop = asyncio.Event()
            keepalive_task = asyncio.create_task(
                self._keepalive_loop(session, keepalive_stop)
            )

            # Phase 3: Execute benchmark
            sem = asyncio.Semaphore(self._current_concurrency)

            def _first_error_handler():
                nonlocal first_error_printed
                first_error_printed = True

            async def bounded_request(idx: int, p: str) -> StreamMetrics:
                # Use dynamic semaphore if enabled, otherwise static
                active_sem = dyn_ctrl.semaphore if dyn_ctrl else sem
                async with active_sem:
                    result = await self._stream_request(session, p, max_tokens, temperature=temperature)
                    if result.error and not first_error_printed:
                        _first_error_handler()
                        print(f"  ⚠️  First error (request #{idx}): {result.error[:150]}")

                    # Feed TTFT to dynamic controller
                    if dyn_ctrl and result.ttft_ms > 0:
                        adj = dyn_ctrl.record_ttft(result.ttft_ms)
                        if adj:
                            print(f"  🎛️  {adj}")

                    return result
            
            # Create tasks
            tasks = [bounded_request(i, p) for i, p in enumerate(prompts)]

            # Execute with progress display
            start_time = time.perf_counter()
            last_print = start_time
            completed = 0
            error_count = 0
            
            for coro in asyncio.as_completed(tasks):
                result = await coro
                completed += 1
                results_collected.append(result)
                
                if result.error:
                    error_count += 1
                
                now = time.perf_counter()
                if now - last_print >= 1.0:
                    elapsed = now - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    err_rate = error_count / completed * 100 if completed > 0 else 0
                    dyn_info = ""
                    if dyn_ctrl:
                        stats = dyn_ctrl.get_stats()
                        dyn_info = f" | c={stats['concurrency']} (adj={stats['adjustments']})"
                    print(f"  ⏳ [{elapsed:.0f}s] Progress: {completed}/{total_requests} "
                          f"({completed/total_requests*100:.0f}%) | "
                          f"Rate: {rate:.1f} req/s | Errors: {error_count} ({err_rate:.1f}%){dyn_info}",
                          flush=True)
                    last_print = now

            # Print final dynamic concurrency stats
            if dyn_ctrl and dyn_ctrl.total_adjustments > 0:
                stats = dyn_ctrl.get_stats()
                print(f"\n  🎛️  Dynamic concurrency final: c={stats['concurrency']} "
                      f"(total adjustments: {stats['total_adjustments']})")

            # Stop keepalive background task
            keepalive_stop.set()
            await asyncio.wait_for(keepalive_task, timeout=5.0)

        self._session = None
        self._connector = None
        
        # Compute report
        report.duration = time.perf_counter() - start_time
        report.count = len(results_collected)

        valid_results = [r for r in results_collected[warmup_count:] if r.is_valid]
        report.valid_count = len(valid_results)
        report.error_count = report.count - len([r for r in results_collected if r.is_valid])
        report.timeout_count = sum(1 for r in results_collected if r.error_type == "timeout")
        
        # Aggregate metrics
        for r in valid_results:
            report.ttft_list.append(r.ttft_ms)
            report.tps_list.append(r.tps)
            report.total_output_tokens += r.tokens_output
            report.total_input_tokens += r.tokens_input
            if r.retry_count > 0:
                report.retried_success += 1
                report.total_retries += r.retry_count
            
            if r.error:
                report.error_list.append(r.error)
                report.errors_by_type[r.error_type] = report.errors_by_type.get(r.error_type, 0) + 1
        
        # Also count retries from failed results
        for r in results_collected:
            if r.error and r.retry_count > 0:
                report.total_retries += r.retry_count
        
        if valid_results:
            report.avg_output_tokens = report.total_output_tokens / len(valid_results)
            report.generation_time = LatencyDistribution.from_data([r.generation_ms for r in valid_results])
            report.total_latency = LatencyDistribution.from_data([r.latency_total_ms for r in valid_results])
            report.tpot = LatencyDistribution.from_data([r.tpot_ms for r in valid_results])
            report.inter_token = LatencyDistribution.from_data(
                [x for r in valid_results for x in r.itl_list] or [0]
            )
        
        report.rps = report.count / report.duration if report.duration > 0 else 0
        report.finalize()
        
        return report


# ==================== CLI ====================

@click.group()
def cli():
    """LLM Streaming Benchmark Tool"""
    pass


@cli.command()
@click.option("--url", default="http://localhost:8000", help="Base URL")
@click.option("--model", default="Qwen/Qwen2.5-0.5B-Instruct", help="Model name")
@click.option("--api-key", default=None, help="API Key (use EMPTY for no auth)")
@click.option("-c", "--concurrency", type=int, default=10, help="Concurrency level")
@click.option("-n", "--total", type=int, default=1000, help="Total number of requests")
@click.option("--max-tokens", type=int, default=100, help="Maximum output tokens")
@click.option("--max-conn", type=int, default=100, help="Connection pool size")
@click.option("--timeout", type=int, default=120, help="Timeout in seconds")
@click.option("--prompt", default=None, help="Custom prompt")
@click.option("--dynamic", is_flag=True, default=False,
              help="Enable dynamic concurrency control (auto-adjust based on TTFT)")
@click.option("--cooldown", type=int, default=0,
              help="Cooldown seconds before starting (for third-party hosted APIs)")
@click.option("--hosted", is_flag=True, default=False,
              help="Optimize for third-party hosted API (reduces retries, adds safeguards)")
def load(url, model, api_key, concurrency, total, max_tokens, max_conn, timeout, prompt, dynamic, cooldown, hosted):
    """Run streaming benchmark (optimized for third-party hosted APIs)"""
    # Handle EMPTY special value
    if api_key and api_key.upper() == "EMPTY":
        api_key = None

    mode = "dynamic" if dynamic else "static"
    hosted_info = " | HOSTED mode (reduced retries)" if hosted else ""
    print(f"🚀 Starting Stream Benchmark | Concurrency: {concurrency} | Total: {total} | Mode: {mode}{hosted_info}")
    print(f"   URL: {url}")
    print(f"   Model: {model}")
    print(f"   API Key: {'***' if api_key else 'None'}")

    if cooldown > 0:
        print(f"   ⏸️  Cooldown: {cooldown}s (waiting for server recovery)")
        import time as _time
        _time.sleep(cooldown)

    bench = LLMBenchmark(
        base_url=url,
        model=model,
        api_key=api_key,
        max_connections=max_conn,
        timeout=timeout,
        hosted_mode=hosted,
    )

    report = asyncio.run(bench.run(
        concurrency=concurrency,
        total_requests=total,
        max_tokens=max_tokens,
        prompt=prompt,
        dynamic=dynamic,
    ))
    report.print()


@cli.command()
@click.option("--url", default="http://localhost:8000", help="Base URL")
@click.option("--model", default="Qwen/Qwen2.5-0.5B-Instruct", help="Model name")
@click.option("--api-key", default=None, help="API Key (use EMPTY for no auth)")
@click.option("--total", type=int, default=500, help="Total number of requests per concurrency level")
@click.option("--max-tokens", type=int, default=100, help="Maximum output tokens")
@click.option("--max-conn", type=int, default=100, help="Connection pool size")
@click.option("--timeout", type=int, default=120, help="Timeout in seconds")
@click.option("--levels", default="1,2,3,5,7,10", help="Concurrency levels to sweep, comma-separated")
@click.option("--cv-target", type=float, default=0.5, help="Target CV threshold for recommendation")
def sweep(url, model, api_key, total, max_tokens, max_conn, timeout, levels, cv_target):
    """Sweep concurrency levels to find optimal point with CV < target (default 0.5)"""
    if api_key and api_key.upper() == "EMPTY":
        api_key = None

    concurrency_levels = [int(x.strip()) for x in levels.split(",")]

    print(f"🔍 Concurrency Sweep | Model: {model} | CV Target: {cv_target}")
    print(f"{'='*90}")

    all_results = []

    for c in concurrency_levels:
        print(f"\n{'='*90}")
        print(f"🎯 Testing concurrency: {c} ({total} requests)")

        bench = LLMBenchmark(
            base_url=url,
            model=model,
            api_key=api_key,
            max_connections=max_conn,
            timeout=timeout
        )

        report = asyncio.run(bench.run(
            concurrency=c,
            total_requests=total,
            max_tokens=max_tokens
        ))

        result = {
            "concurrency": c,
            "rps": report.rps,
            "ttft_mean": report.ttft.mean,
            "ttft_p99": report.ttft.p99,
            "ttft_max": report.ttft.max_val,
            "ttft_cv": report.ttft.cv,
            "ttft_winsor_cv": report.ttft.winsor_cv,
            "ttft_winsor_max": report.ttft.winsor_max,
            "tps_mean": report.tps.mean,
            "success_rate": report.valid_count / report.count * 100 if report.count else 0,
            "errors": report.error_count,
        }

        # Composite score: prioritize CV < target, then RPS
        cv_penalty = 1.0 if result["ttft_winsor_cv"] < cv_target else 0.3
        result["score"] = (
            result["rps"] * 0.4 * cv_penalty +
            (1000 / max(result["ttft_p99"], 1)) * 0.3 * cv_penalty +
            result["success_rate"] * 0.3
        )
        all_results.append(result)

        cv_emoji = "🟢" if result["ttft_winsor_cv"] < cv_target else "🟡" if result["ttft_winsor_cv"] < 1.0 else "🔴"
        print(f"   {cv_emoji} RPS: {result['rps']:.2f} | TTFT CV: {result['ttft_cv']:.3f} "
              f"(winsor: {result['ttft_winsor_cv']:.3f}) | Max: {result['ttft_max']:.0f}ms "
              f"(winsor: {result['ttft_winsor_max']:.0f}ms) | Success: {result['success_rate']:.1f}%")

    # Output comparison table
    print(f"\n{'='*90}")
    print(f"📊 SWEEP RESULTS (sorted by score)")
    print(f"{'='*90}")
    print(f"{'Conc':>5} {'RPS':>8} {'TTFT Mean':>10} {'P99':>8} {'Max':>8} {'CV':>7} {'W-CV':>7} {'W-Max':>8} {'Succ%':>7} {'Score':>8}")
    print("-" * 90)

    all_results.sort(key=lambda x: x["score"], reverse=True)
    best = all_results[0] if all_results else None

    for r in all_results:
        marker = " ⭐" if r is best else ""
        print(f"{r['concurrency']:>5} {r['rps']:>8.2f} {r['ttft_mean']:>10.1f} "
              f"{r['ttft_p99']:>8.1f} {r['ttft_max']:>8.0f} {r['ttft_cv']:>7.3f} "
              f"{r['ttft_winsor_cv']:>7.3f} {r['ttft_winsor_max']:>8.0f} "
              f"{r['success_rate']:>7.1f} {r['score']:>8.1f}{marker}")

    # Find CV-qualified candidates
    cv_qualified = [r for r in all_results if r["ttft_winsor_cv"] < cv_target]
    cv_qualified.sort(key=lambda x: x["rps"], reverse=True)

    print(f"\n{'='*90}")
    print(f"📋 RECOMMENDATION")
    print(f"{'='*90}")

    if cv_qualified:
        rec = cv_qualified[0]
        print(f"✅ Best concurrency with CV < {cv_target}: {rec['concurrency']}")
        print(f"   RPS: {rec['rps']:.2f} | Winsor CV: {rec['ttft_winsor_cv']:.3f} | "
              f"Winsor Max: {rec['ttft_winsor_max']:.0f}ms | Success: {rec['success_rate']:.1f}%")
        print(f"\n   Command to run full benchmark:")
        print(f"   python benchmark.py load --url \"{url}\" --model \"{model}\" "
              f"{'--api-key EMPTY' if not api_key else f'--api-key {api_key[:8]}...'} "
              f"-c {rec['concurrency']} -n 10000")
    else:
        print(f"⚠️  No concurrency level achieved Winsor CV < {cv_target}")
        print(f"   Lowest CV: {min(r['ttft_winsor_cv'] for r in all_results):.3f} "
              f"at concurrency={min(all_results, key=lambda x: x['ttft_winsor_cv'])['concurrency']}")
        print(f"\n   The extreme outliers (Max >> P99) are likely caused by:")
        print(f"   - GPU memory cleanup / GC pauses on the server")
        print(f"   - Network transient blips (TCP retransmission)")
        print(f"   - Server-side request queue spikes")
        print(f"\n   These are infrastructural and cannot be fully eliminated by client-side tuning.")
        print(f"   Best achievable with current infrastructure:")
        best_cv = min(all_results, key=lambda x: x["ttft_winsor_cv"])
        print(f"   Concurrency={best_cv['concurrency']}: CV={best_cv['ttft_winsor_cv']:.3f}, "
              f"RPS={best_cv['rps']:.2f}, Success={best_cv['success_rate']:.1f}%")


@cli.command()
@click.option("--url", default="http://localhost:8000", help="Base URL")
@click.option("--model", default="Qwen/Qwen2.5-0.5B-Instruct", help="Model name")
@click.option("--api-key", default=None, help="API Key (use EMPTY for no auth)")
@click.option("--levels", default="1,2,5,10,20,50", help="Concurrency levels to test")
@click.option("--total", type=int, default=200, help="Total requests per level")
@click.option("--timeout", type=int, default=60, help="Timeout in seconds")
def throughput(url, model, api_key, levels, total, timeout):
    """Find the RPS ceiling by testing max_tokens=1 (TTFT-only, no generation bottleneck).

    This isolates API overhead from generation speed:
    - If max_tokens=1 RPS is still low → API/server bottleneck (rate limit, queueing)
    - If max_tokens=1 RPS is high but max_tokens=100 RPS is low → generation bottleneck (GPU speed)
    """
    if api_key and api_key.upper() == "EMPTY":
        api_key = None

    concurrency_levels = [int(x.strip()) for x in levels.split(",")]

    print(f"🚀 THROUGHPUT CEILING TEST | Model: {model}")
    print(f"   Strategy: max_tokens=1 (TTFT-only, isolates API overhead from generation)")
    print(f"{'='*85}")

    all_results = []

    for c in concurrency_levels:
        bench = LLMBenchmark(
            base_url=url, model=model, api_key=api_key,
            max_connections=max(c * 2, 20), timeout=timeout,
        )

        print(f"\n  🎯 c={c}, max_tokens=1, {total} requests...", end="", flush=True)
        report = asyncio.run(bench.run(
            concurrency=c, total_requests=total,
            max_tokens=1, prompt="Hi",
        ))

        # Also test max_tokens=100 for comparison (smaller sample)
        print(f" done | c={c}, max_tokens=100, {min(total, 50)} requests...", end="", flush=True)
        bench2 = LLMBenchmark(
            base_url=url, model=model, api_key=api_key,
            max_connections=max(c * 2, 20), timeout=timeout,
        )
        report100 = asyncio.run(bench2.run(
            concurrency=c, total_requests=min(total, 50),
            max_tokens=100, prompt="Hi",
        ))

        r1 = {
            "concurrency": c,
            "rps_1tok": report.rps,
            "ttft_1tok": report.ttft.mean,
            "success_1tok": report.valid_count / report.count * 100 if report.count else 0,
            "rps_100tok": report100.rps,
            "ttft_100tok": report100.ttft.mean,
            "gen_100tok": report100.generation_time.mean,
            "success_100tok": report100.valid_count / report100.count * 100 if report100.count else 0,
        }
        # Theoretical: if generation is the bottleneck, RPS_100tok = c / gen_time
        # If API overhead is the bottleneck, RPS_1tok = c / ttft
        if r1["gen_100tok"] > 0:
            r1["theoretical_rps_100tok"] = c / (r1["gen_100tok"] / 1000)
        else:
            r1["theoretical_rps_100tok"] = 0
        if r1["ttft_1tok"] > 0:
            r1["theoretical_rps_1tok"] = c / (r1["ttft_1tok"] / 1000)
        else:
            r1["theoretical_rps_1tok"] = 0

        all_results.append(r1)
        print(f" done")
        print(f"     1-token:  RPS={r1['rps_1tok']:.1f} | TTFT={r1['ttft_1tok']:.0f}ms | Succ={r1['success_1tok']:.0f}%")
        print(f"     100-token: RPS={r1['rps_100tok']:.1f} | TTFT={r1['ttft_100tok']:.0f}ms | Gen={r1['gen_100tok']:.0f}ms | Succ={r1['success_100tok']:.0f}%")

    # Summary table
    print(f"\n{'='*85}")
    print(f"📊 THROUGHPUT CEILING ANALYSIS")
    print(f"{'='*85}")
    print(f"{'Conc':>5} {'RPS(1tok)':>10} {'RPS(100tok)':>12} {'TTFT(1t)':>9} {'Gen(100t)':>10} {'Theo.RPS':>9} {'Bottleneck':>20}")
    print("-" * 85)

    best_1tok_rps = max(r["rps_1tok"] for r in all_results) if all_results else 0
    best_100tok_rps = max(r["rps_100tok"] for r in all_results) if all_results else 0

    for r in all_results:
        # Determine bottleneck
        if r["rps_1tok"] > r["rps_100tok"] * 3:
            bottleneck = "GENERATION (GPU)"
        elif r["rps_1tok"] < 10:
            bottleneck = "API OVERHEAD"
        elif r["success_1tok"] < 95:
            bottleneck = "SERVER LIMIT"
        else:
            bottleneck = "BALANCED"

        theo = r["theoretical_rps_100tok"]
        print(f"{r['concurrency']:>5} {r['rps_1tok']:>10.1f} {r['rps_100tok']:>12.1f} "
              f"{r['ttft_1tok']:>9.0f} {r['gen_100tok']:>10.0f} {theo:>9.1f} {bottleneck:>20}")

    # Diagnosis
    print(f"\n{'='*85}")
    print(f"📋 DIAGNOSIS")
    print(f"{'='*85}")

    best_1tok = max(all_results, key=lambda x: x["rps_1tok"]) if all_results else None
    best_100tok = max(all_results, key=lambda x: x["rps_100tok"]) if all_results else None

    if best_1tok and best_100tok:
        print(f"\n  Max 1-token RPS:   {best_1tok['rps_1tok']:.1f} (at c={best_1tok['concurrency']})")
        print(f"  Max 100-token RPS: {best_100tok['rps_100tok']:.1f} (at c={best_100tok['concurrency']})")
        print(f"  Generation speed:  {best_100tok['gen_100tok']:.0f}ms for 100 tokens "
              f"= {100000/best_100tok['gen_100tok']:.0f} tokens/sec")

        ratio = best_1tok['rps_1tok'] / max(best_100tok['rps_100tok'], 0.1)
        print(f"\n  1-token vs 100-token RPS ratio: {ratio:.1f}x")

        if ratio > 5:
            print(f"  🔴 BOTTLENECK: GENERATION SPEED (GPU compute)")
            print(f"     The API can handle {best_1tok['rps_1tok']:.0f} req/s for minimal responses,")
            print(f"     but 100-token generation takes {best_100tok['gen_100tok']:.0f}ms each.")
            print(f"     At {100000/best_100tok['gen_100tok']:.0f} tokens/sec, a 0.5B model should do 200+ tok/s.")
            print(f"     → Server-side fixes needed:")
            print(f"       • Enable continuous batching (vLLM: --enable-batching)")
            print(f"       • Check if model is quantized (INT8/INT4 would be faster)")
            print(f"       • Check if GPU is shared/throttled (multi-tenant)")
            print(f"       • Increase max_num_seqs in vLLM config")
        elif best_1tok['rps_1tok'] < 10:
            print(f"  🔴 BOTTLENECK: API OVERHEAD / RATE LIMIT")
            print(f"     Even with max_tokens=1, RPS is only {best_1tok['rps_1tok']:.1f}")
            print(f"     → Server-side fixes needed:")
            print(f"       • Check for rate limiting (429 responses)")
            print(f"       • Check load balancer config")
            print(f"       • Check if model is cold-starting per request")
        else:
            print(f"  🟡 MIXED BOTTLENECK")
            print(f"     Both API overhead and generation contribute to low RPS.")

        # Theoretical ceiling
        if best_100tok['gen_100tok'] > 0:
            # If we could run c=100 concurrent at this gen speed:
            theo_c100 = 100 / (best_100tok['gen_100tok'] / 1000)
            print(f"\n  💡 If server supported c=100 concurrent:")
            print(f"     Theoretical RPS = 100 / {best_100tok['gen_100tok']/1000:.2f}s = {theo_c100:.1f} RPS")
            print(f"     Gap to 50 RPS target: {50/best_100tok['rps_100tok']:.1f}x")

    print(f"{'='*85}")


@cli.command()
@click.option("--url", default="http://localhost:8000", help="Base URL")
@click.option("--model", default="Qwen/Qwen2.5-0.5B-Instruct", help="Model name")
@click.option("--api-key", default=None, help="API Key (use EMPTY for no auth)")
@click.option("--count", type=int, default=100, help="Number of sequential requests for pattern detection")
@click.option("--max-tokens", type=int, default=10, help="Max tokens per request")
@click.option("--timeout", type=int, default=60, help="Timeout in seconds")
def diagnose(url, model, api_key, count, max_tokens, timeout):
    """Diagnose 95% success rate lock and TTFT outlier root causes.

    Runs three diagnostic phases:
    1. Sequential failure pattern detection (periodic? random?)
    2. Prompt length sensitivity (prompt processing vs queuing)
    3. Burst rate limit detection
    """
    if api_key and api_key.upper() == "EMPTY":
        api_key = None

    bench = LLMBenchmark(
        base_url=url, model=model, api_key=api_key,
        max_connections=10, timeout=timeout,
    )

    connector = bench._build_connector()
    timeout_cfg = bench._build_timeout()

    print(f"🔬 DIAGNOSTIC MODE | Model: {model}")
    print(f"{'='*80}")

    # ==================== Phase 1: Sequential failure pattern ====================
    print(f"\n📋 Phase 1: Sequential failure pattern ({count} requests, c=1)")
    print(f"{'='*80}")

    seq_results = []  # (idx, start_offset_s, ttft_ms, error, error_type)

    async def _phase1():
        async with aiohttp.ClientSession(connector=connector, timeout=timeout_cfg) as session:
            bench._session = session
            bench._prewarmed = False
            await bench._prewarm_connections(session)

            t0 = time.perf_counter()
            for i in range(count):
                r = await bench._stream_request(session, "Say hello.", max_tokens)
                offset = time.perf_counter() - t0
                seq_results.append((i, offset, r.ttft_ms, r.error, r.error_type))
                status = "✅" if r.is_valid else f"❌ {r.error_type or 'invalid'}"
                ttft_str = f"{r.ttft_ms:.0f}ms" if r.ttft_ms > 0 else "N/A"
                if i < 20 or r.error:
                    print(f"  [{i:3d}] t={offset:6.1f}s | TTFT={ttft_str:>8} | {status}"
                          + (f" | {r.error[:80]}" if r.error else ""))
                elif i % 20 == 0:
                    print(f"  [{i:3d}] t={offset:6.1f}s | TTFT={ttft_str:>8} | ...")

    asyncio.run(_phase1())

    # Analyze failure pattern
    failures = [(i, t, e, et) for i, t, _, e, et in seq_results if e]
    success_count = count - len(failures)
    success_rate = success_count / count * 100

    print(f"\n  📊 Phase 1 Results:")
    print(f"     Success: {success_count}/{count} ({success_rate:.1f}%)")
    print(f"     Failures: {len(failures)}")

    if failures:
        # Check for periodic pattern
        fail_indices = [f[0] for f in failures]
        fail_intervals = [fail_indices[i+1] - fail_indices[i] for i in range(len(fail_indices)-1)]

        print(f"\n  🔍 Failure pattern analysis:")
        print(f"     Failure indices: {fail_indices[:20]}{'...' if len(fail_indices) > 20 else ''}")

        if len(fail_intervals) >= 2:
            from collections import Counter
            interval_counts = Counter(fail_intervals)
            most_common_interval = interval_counts.most_common(1)[0]
            print(f"     Most common interval: every {most_common_interval[0]} requests "
                  f"({most_common_interval[1]} times)")

            if most_common_interval[1] >= len(fail_intervals) * 0.5:
                print(f"     ⚠️  PERIODIC FAILURE detected! Failures occur every ~{most_common_interval[0]} requests")
                print(f"     → Likely cause: rate limiter, model reload cycle, or health check eviction")
            else:
                print(f"     → Failures appear RANDOM (no fixed interval)")
                print(f"     → Likely cause: GPU contention, network jitter, or load balancer drops")

        # Error type distribution
        error_types = Counter(f[3] for f in failures)
        print(f"\n  📋 Error type distribution:")
        for et, cnt in error_types.most_common():
            print(f"     {et:15s}  {cnt} ({cnt/len(failures)*100:.0f}%)")

        # Time distribution
        if len(failures) > 1:
            fail_times = [f[1] for f in failures]
            print(f"\n  ⏰ Failure time distribution:")
            print(f"     First: t={fail_times[0]:.1f}s | Last: t={fail_times[-1]:.1f}s")
            print(f"     Mean interval: {statistics.mean(fail_intervals):.1f}s" if fail_intervals else "")

    # ==================== Phase 2: Prompt length sensitivity ====================
    print(f"\n{'='*80}")
    print(f"📋 Phase 2: Prompt length sensitivity (5 short vs 5 long, c=1)")
    print(f"{'='*80}")

    short_prompt = "Hi"
    long_prompt = "Please explain the following concepts in detail: " + ("quantum mechanics, relativity, thermodynamics, electromagnetism, " * 20)

    async def _phase2():
        async with aiohttp.ClientSession(connector=connector, timeout=timeout_cfg) as session:
            bench._session = session
            bench._prewarmed = True

            short_ttfts = []
            long_ttfts = []

            print(f"\n  Short prompt ({len(short_prompt)} chars):")
            for i in range(5):
                r = await bench._stream_request(session, short_prompt, max_tokens)
                if r.is_valid:
                    short_ttfts.append(r.ttft_ms)
                    print(f"    [{i}] TTFT={r.ttft_ms:.0f}ms tokens={r.tokens_output}")
                else:
                    print(f"    [{i}] FAILED: {r.error_type}")

            print(f"\n  Long prompt ({len(long_prompt)} chars):")
            for i in range(5):
                r = await bench._stream_request(session, long_prompt, max_tokens)
                if r.is_valid:
                    long_ttfts.append(r.ttft_ms)
                    print(f"    [{i}] TTFT={r.ttft_ms:.0f}ms tokens={r.tokens_output}")
                else:
                    print(f"    [{i}] FAILED: {r.error_type}")

            return short_ttfts, long_ttfts

    short_ttfts, long_ttfts = asyncio.run(_phase2())

    print(f"\n  📊 Phase 2 Results:")
    if short_ttfts and long_ttfts:
        short_mean = statistics.mean(short_ttfts)
        long_mean = statistics.mean(long_ttfts)
        ratio = long_mean / short_mean if short_mean > 0 else 0

        print(f"     Short prompt TTFT: {short_mean:.0f}ms (mean)")
        print(f"     Long prompt TTFT:  {long_mean:.0f}ms (mean)")
        print(f"     Ratio (long/short): {ratio:.2f}x")

        if ratio > 3:
            print(f"     🔴 TTFT scales strongly with prompt length → PROMPT PROCESSING BOTTLENECK")
            print(f"        Server is spending most time on prefill, not queuing.")
            print(f"        Suggestion: Use prefix caching, shorter prompts, or spec decoding.")
        elif ratio > 1.5:
            print(f"     🟡 TTFT moderately affected by prompt length → mixed bottleneck")
        else:
            print(f"     🟢 TTFT insensitive to prompt length → QUEUING/NETWORK bottleneck")
            print(f"        TTFT is dominated by wait time, not compute.")
            print(f"        Suggestion: Reduce concurrency, check server batch scheduling.")
    else:
        print(f"     ⚠️  Insufficient valid responses for comparison")

    # ==================== Phase 3: Burst rate limit detection ====================
    print(f"\n{'='*80}")
    print(f"📋 Phase 3: Burst rate limit detection (20 rapid sequential requests)")
    print(f"{'='*80}")

    burst_results = []

    async def _phase3():
        async with aiohttp.ClientSession(connector=connector, timeout=timeout_cfg) as session:
            bench._session = session
            bench._prewarmed = True

            t0 = time.perf_counter()
            for i in range(20):
                r = await bench._stream_request(session, "Say ok.", 1)
                offset = time.perf_counter() - t0
                burst_results.append((i, offset, r.is_valid, r.error_type, r.ttft_ms))
                status = "✅" if r.is_valid else "❌"
                print(f"  [{i:2d}] t={offset:5.2f}s | {status} | TTFT={r.ttft_ms:.0f}ms"
                      + (f" | {r.error_type}" if r.error else ""))

    asyncio.run(_phase3())

    burst_success = sum(1 for r in burst_results if r[2])
    burst_failures = [(i, t, et) for i, t, v, et, _ in burst_results if not v]

    print(f"\n  📊 Phase 3 Results:")
    print(f"     Burst success: {burst_success}/20 ({burst_success*5}%)")

    if burst_failures:
        first_fail = burst_failures[0]
        print(f"     First failure at request #{first_fail[0]} (t={first_fail[1]:.2f}s)")

        # Check if failures cluster at the end (rate limit kicked in)
        if all(i >= 10 for i, _, _ in burst_failures):
            print(f"     ⚠️  Failures cluster in second half → RATE LIMITER (bucket-based)")
        elif all(i < 5 for i, _, _ in burst_failures):
            print(f"     ⚠️  Failures at start → COLD START / model not loaded")
        else:
            print(f"     → Failures scattered → not a simple rate limiter")

    # ==================== Summary ====================
    print(f"\n{'='*80}")
    print(f"📋 DIAGNOSTIC SUMMARY")
    print(f"{'='*80}")

    print(f"\n  1. SUCCESS RATE:")
    print(f"     Sequential: {success_rate:.1f}% | Burst: {burst_success*5}%")
    if success_rate > 95 and burst_success >= 18:
        print(f"     → ~5% failure is CONSISTENT across modes → server-side deterministic drop")
        print(f"     → Check: load balancer health check, rate limiter config, model warmup")
    elif success_rate < burst_success * 5 / 20 * 100:
        print(f"     → Burst mode is better → failures are time-based, not count-based")

    print(f"\n  2. TTFT OUTLIERS:")
    if short_ttfts and long_ttfts:
        ratio = statistics.mean(long_ttfts) / max(statistics.mean(short_ttfts), 1)
        if ratio <= 1.5:
            print(f"     → TTFT is QUEUE-DOMINATED (prompt length has little effect)")
            print(f"     → TTFT Max spikes are likely QUEUE DEPTH spikes, not GPU compute")
            print(f"     → Fix: reduce concurrency, use c=2 (your sweep sweet spot)")
        else:
            print(f"     → TTFT is COMPUTE-DOMINATED (prompt length matters {ratio:.1f}x)")
            print(f"     → Fix: enable prefix caching, reduce prompt size")

    print(f"\n  3. RECOMMENDED ACTIONS:")
    print(f"     • Run at c=2 (sweep confirmed W-CV=0.430)")
    print(f"     • Ask your provider: 'Is there a rate limit or health check on this endpoint?'")
    print(f"     • Ask your provider: 'Is continuous batching enabled? What is max_num_seqs?'")
    print(f"     • Ask your provider: 'Is the model kept in GPU memory between requests?'")
    print(f"     • Test with a different endpoint/instance to rule out multi-tenant contention")
    print(f"{'='*80}")


if __name__ == "__main__":
    cli()