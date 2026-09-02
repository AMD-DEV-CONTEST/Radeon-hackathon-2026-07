"""Stage J — Monitor API: health, metrics, benchmark, cache, queue."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings
from app.schemas.models import (
    BenchmarkCompareResponse,
    BenchmarkSnapshotModel,
    CacheInvalidateRequest,
    CacheStats,
    HealthCheckResponse,
    QueueStatus,
)
from app.services.benchmark import BenchmarkCollector, get_benchmark
from app.services.cache import TTLCache, get_cache
from app.services.monitor import HealthMonitor, get_monitor
from app.services.task_queue import TaskQueue, get_task_queue
from app.security.permissions import require_system_admin

# Operations telemetry includes infrastructure and model metadata.  Keep the
# whole surface behind the system-admin boundary, not merely authentication.
router = APIRouter(
    prefix="/monitor", tags=["monitor"], dependencies=[Depends(require_system_admin)]
)


def _get_monitor(request: Request) -> HealthMonitor:
    return get_monitor(request.app.state.settings)


def _get_benchmark(request: Request) -> BenchmarkCollector:
    return get_benchmark(request.app.state.settings)


def _get_cache(request: Request) -> TTLCache:
    return get_cache(request.app.state.settings)


def _get_queue(request: Request) -> TaskQueue:
    return get_task_queue(request.app.state.settings)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(
    monitor: Annotated[HealthMonitor, Depends(_get_monitor)],
    queue: Annotated[TaskQueue, Depends(_get_queue)],
    cache: Annotated[TTLCache, Depends(_get_cache)],
) -> HealthCheckResponse:
    """Full system health check: GPU, disk, LLM endpoint, error rates."""
    health = await monitor.health_check()
    qs = await queue.status()
    cs = cache.stats

    # Convert latency metrics
    lm = monitor.latency_metrics
    return HealthCheckResponse(
        status=health["status"],
        issues=health.get("issues", []),
        gpu_metrics=[dict(**gm) for gm in health.get("gpu_metrics", [])],
        system_metrics=dict(**health.get("system_metrics", {})),
        model_metadata=dict(**health.get("model_metadata", {})),
        llm_error_rate=monitor.llm_error_rate,
        queue_status=qs,
        cache_stats=cs,
        timestamp=health.get("timestamp", 0),
    )


# ---------------------------------------------------------------------------
# Queue status
# ---------------------------------------------------------------------------


@router.get("/queue", response_model=QueueStatus)
async def queue_status(
    queue: Annotated[TaskQueue, Depends(_get_queue)],
) -> QueueStatus:
    """Current task queue concurrency status."""
    return await queue.status()


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


@router.get("/cache", response_model=CacheStats)
async def cache_stats(
    cache: Annotated[TTLCache, Depends(_get_cache)],
) -> CacheStats:
    """Current cache statistics and hit rate."""
    return cache.stats


@router.post("/cache/invalidate")
async def cache_invalidate(
    body: CacheInvalidateRequest,
    cache: Annotated[TTLCache, Depends(_get_cache)],
) -> dict:
    """Invalidate cache entries by project, category, or key prefix."""
    removed = 0
    if body.key_prefix:
        removed = cache.invalidate(body.key_prefix)
    elif body.project_id:
        removed = cache.invalidate_project(body.project_id)
    elif body.category:
        removed = cache.invalidate_category(body.category)
    else:
        removed = cache.clear()
    return {"removed": removed}


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


@router.get("/benchmark/snapshots", response_model=list[BenchmarkSnapshotModel])
async def benchmark_snapshots(
    bench: Annotated[BenchmarkCollector, Depends(_get_benchmark)],
) -> list[BenchmarkSnapshotModel]:
    """List all benchmark snapshots."""
    return bench._snapshots


@router.get("/benchmark/compare", response_model=BenchmarkCompareResponse)
async def benchmark_compare(
    bench: Annotated[BenchmarkCollector, Depends(_get_benchmark)],
    baseline: str = "baseline",
    optimized: str = "post-optimization",
) -> BenchmarkCompareResponse:
    """Compare two benchmark snapshots."""
    comp = bench.compare(baseline, optimized)
    return comp


@router.get("/benchmark/latest")
async def benchmark_latest(
    bench: Annotated[BenchmarkCollector, Depends(_get_benchmark)],
) -> dict:
    """Get the latest benchmark snapshot."""
    latest = bench.latest
    if latest is None:
        raise HTTPException(status_code=404, detail="No benchmarks recorded")
    return {
        "label": latest.label,
        "first_token_latency_ms": latest.first_token_latency_ms,
        "generation_tokens_per_second": latest.generation_tokens_per_second,
        "embedding_throughput_texts_per_second": latest.embedding_throughput_texts_per_second,
        "end_to_end_latency_ms": latest.end_to_end_latency_ms,
        "vram_used_mb": latest.vram_used_mb,
        "vram_total_mb": latest.vram_total_mb,
        "gpu_utilization_pct": latest.gpu_utilization_pct,
        "gpu_model": latest.gpu_model,
        "quantization": latest.quantization,
        "timestamp": latest.timestamp,
    }


# ---------------------------------------------------------------------------
# GPU metrics
# ---------------------------------------------------------------------------


@router.get("/gpu")
async def gpu_metrics(
    monitor: Annotated[HealthMonitor, Depends(_get_monitor)],
) -> dict:
    """Collect live GPU metrics."""
    gpus = await monitor.collect_gpu_metrics()
    return {
        "gpus": [
            {
                "device_id": g.device_id,
                "name": g.name,
                "vram_total_mb": g.vram_total_mb,
                "vram_used_mb": g.vram_used_mb,
                "vram_free_mb": g.vram_free_mb,
                "utilization_pct": g.utilization_pct,
                "temperature_c": g.temperature_c,
            }
            for g in gpus
        ],
        "backend": monitor._backend,
    }
