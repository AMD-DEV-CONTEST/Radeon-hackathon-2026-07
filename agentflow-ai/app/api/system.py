from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import AppServices, get_services
from app.schemas import BenchmarksResponse, HealthResponse, SystemInfoResponse
from app.services.system_info import collect_system_info

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(services: AppServices = Depends(get_services)) -> HealthResponse:
    status = services.ollama.health()
    return HealthResponse(
        ok=True,
        ollama_running=status.running,
        selected_model=status.selected_model,
        available_models=status.available_models,
        database_ready=True,
        chroma_ready=True,
        message=status.message,
    )


@router.get("/info", response_model=SystemInfoResponse)
def system_info(services: AppServices = Depends(get_services)) -> SystemInfoResponse:
    return SystemInfoResponse(**collect_system_info(services.ollama))


@router.get("/benchmarks", response_model=BenchmarksResponse)
def benchmarks(services: AppServices = Depends(get_services)) -> BenchmarksResponse:
    return BenchmarksResponse(**services.storage.benchmark_summary())
