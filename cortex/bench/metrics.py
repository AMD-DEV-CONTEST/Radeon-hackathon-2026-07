from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cortex.core.envelope import Envelope, EnvelopeType


@dataclass(frozen=True)
class BenchMetrics:
    node: str
    embeds_per_sec_radeon: float
    embeds_per_sec_cpu: float
    queries_per_sec_radeon: float
    queries_per_sec_cpu: float
    gpu_mem_util_pct: float
    p95_query_latency_ms: float
    ts: datetime


def to_dict(metrics: BenchMetrics) -> dict[str, Any]:
    return {
        "node": metrics.node,
        "embeds_per_sec_radeon": metrics.embeds_per_sec_radeon,
        "embeds_per_sec_cpu": metrics.embeds_per_sec_cpu,
        "queries_per_sec_radeon": metrics.queries_per_sec_radeon,
        "queries_per_sec_cpu": metrics.queries_per_sec_cpu,
        "gpu_mem_util_pct": metrics.gpu_mem_util_pct,
        "p95_query_latency_ms": metrics.p95_query_latency_ms,
    }


def to_envelope(metrics: BenchMetrics) -> Envelope:
    from uuid import uuid4

    return Envelope(
        type=EnvelopeType.METRICS,
        msg_id=str(uuid4()),
        src=metrics.node,
        dst="*",
        ts=metrics.ts,
        payload=to_dict(metrics),
    )
