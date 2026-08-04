"""
LaunchKart AI 2.0 — GPU Monitoring API Routes

Endpoints for AMD Radeon GPU status, benchmarks, and ROCm metrics.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.dependencies import AdminOnlyDep, DbSessionDep, SellerOrAdminDep

router = APIRouter()


# ---- Response Schemas ----


class GPUInfo(BaseModel):
    gpu_name: str
    driver_version: str | None
    rocm_version: str | None
    vram_total_gb: float
    vram_used_gb: float
    vram_free_gb: float
    gpu_utilization_percent: float
    gpu_temperature_celsius: float | None
    power_draw_watts: float | None
    compute_units: int | None
    is_rocm_available: bool
    active_agents: int = 0


class GPUStatusResponse(BaseModel):
    gpu_detected: bool
    gpus: list[GPUInfo]
    ollama_status: str
    models_loaded: list[str]
    inference_backend: str


class BenchmarkResult(BaseModel):
    model_name: str
    tokens_per_second: float
    inference_latency_ms: float
    vram_usage_gb: float
    prompt_eval_rate: float
    eval_rate: float


class BenchmarkResponse(BaseModel):
    gpu_name: str
    rocm_version: str | None
    benchmarks: list[BenchmarkResult]
    cpu_comparison: dict | None
    timestamp: str


# ---- Endpoints ----


@router.get("/status", response_model=GPUStatusResponse)
async def get_gpu_status(_auth: SellerOrAdminDep) -> GPUStatusResponse:
    """Get real-time AMD GPU status and metrics."""
    from app.services.gpu_monitor_service import GPUMonitorService

    service = GPUMonitorService()
    return await service.get_status()


@router.get("/benchmarks", response_model=list[BenchmarkResponse])
async def get_benchmarks(
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> list[BenchmarkResponse]:
    """Get historical GPU benchmark results."""
    from app.services.gpu_monitor_service import GPUMonitorService

    service = GPUMonitorService()
    return await service.get_benchmarks(db=db)


@router.post("/benchmark", response_model=BenchmarkResponse)
async def run_benchmark(
    _auth: SellerOrAdminDep,
    db: DbSessionDep,
) -> BenchmarkResponse:
    """Run a GPU benchmark (admin only)."""
    from app.services.gpu_monitor_service import GPUMonitorService

    service = GPUMonitorService()
    return await service.run_benchmark(db=db)
