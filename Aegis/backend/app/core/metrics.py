"""
Custom Prometheus metrics beyond the generic HTTP metrics Instrumentator
already provides — these are the ones judges specifically care about:
agent execution time, tokens/sec, and inference concurrency, so GPU
utilization has a first-class, dashboardable signal (Phase 14 reads these).
"""
from prometheus_client import Counter, Gauge, Histogram

AGENT_EXECUTION_SECONDS = Histogram(
    "aegis_agent_execution_seconds",
    "Time spent executing a single agent node",
    labelnames=["agent_name"],
)

INFERENCE_TOKENS_PER_SECOND = Gauge(
    "aegis_inference_tokens_per_second",
    "Most recent tokens/sec observed from the local inference engine",
)

INFERENCE_REQUESTS_TOTAL = Counter(
    "aegis_inference_requests_total",
    "Total number of completion requests sent to the local inference engine",
    labelnames=["status"],
)

INFERENCE_CONCURRENT_REQUESTS = Gauge(
    "aegis_inference_concurrent_requests",
    "Number of inference requests currently in flight (proxy for GPU batch occupancy)",
)

INCIDENTS_BY_STATUS = Gauge(
    "aegis_incidents_by_status",
    "Current count of incidents in each status",
    labelnames=["status"],
)

# prometheus_client Gauges are write-only from the app's perspective (by design,
# for the /metrics scrape model); we keep this plain mirror so the benchmarks
# API can answer "what's the current tokens/sec" without reaching into
# prometheus_client internals.
_last_tokens_per_second: float = 0.0


def record_tokens_per_second(value: float) -> None:
    global _last_tokens_per_second
    _last_tokens_per_second = value
    INFERENCE_TOKENS_PER_SECOND.set(value)


def get_last_tokens_per_second() -> float:
    return _last_tokens_per_second
