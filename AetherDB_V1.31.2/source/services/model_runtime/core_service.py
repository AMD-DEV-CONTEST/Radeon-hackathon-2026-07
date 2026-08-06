"""Lifecycle and truthful status for AetherDB's core embedding capability."""

from __future__ import annotations

import os
import threading
from typing import Any

from services.model_runtime.contracts import LeaseMode, WorkerLoadRequest, utc_now


CORE_EMBEDDING_PACKAGE_ID = "aetherdb.bge-m3"
CORE_SERVICE_STATES = {
    "initializing",
    "ready_warm",
    "ready_controlled",
    "degraded_cpu",
    "recovering",
    "unavailable",
}


def _requested_backend() -> str:
    value = os.environ.get("AETHERDB_EMBEDDING_ACCELERATOR", "auto").strip().lower()
    backend = {
        "auto": "auto",
        "rocm": "rocm_migraphx",
        "migraphx": "rocm_migraphx",
        "cuda": "cuda",
        "cpu": "cpu",
    }.get(value)
    if backend is None:
        raise ValueError(f"Unsupported embedding accelerator: {value}")
    return backend


def _prewarm_enabled() -> bool:
    return os.environ.get("AETHERDB_CORE_PREWARM", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _required_vram_mb(manifest) -> int:
    peak = (
        manifest.resource_profile.recommended_vram_mb
        or manifest.resource_profile.minimum_vram_mb
        or 0
    )
    context = max(256, peak // 10) if peak else 0
    margin = max(512, peak * 15 // 100) if peak else 0
    return peak + context + margin


def _scheduling_manifest(manifest):
    if hasattr(manifest, "supported_backends") and hasattr(manifest, "resource_profile"):
        return manifest
    from app.config import get_resource_path
    from services.model_packages.manifest import load_package_manifest

    return load_package_manifest(
        get_resource_path("resources", "model_packages", "aetherdb-bge-m3.json")
    )


def _compatible_gpu(snapshot, manifest, requested_backend: str):
    supported = set(manifest.supported_backends)
    backend_order = (
        [requested_backend]
        if requested_backend != "auto"
        else ["rocm_migraphx", "rocm_pytorch", "cuda"]
    )
    required = _required_vram_mb(manifest)
    pressure_percent = 10
    candidates = []
    for backend in backend_order:
        if backend not in supported:
            continue
        for device in snapshot.devices:
            compatible = (
                device.backend == backend
                or backend == "rocm_pytorch"
                and device.backend == "rocm_migraphx"
            )
            pressure_floor = device.total_vram_mb * pressure_percent // 100
            if compatible and device.free_vram_mb - required >= pressure_floor:
                candidates.append((device.free_vram_mb, device, backend))
    if not candidates:
        return None
    _, device, backend = max(candidates, key=lambda item: (item[0], -item[1].visible_index))
    return device, backend


class CoreEmbeddingService:
    """Owns core embedding readiness without making database startup depend on it."""

    def __init__(self):
        self._lock = threading.RLock()
        self._provider = None
        self._manager = None
        self._scheduler = None
        self._state = "initializing"
        self._residency_state = "not_initialized"
        self._backend = None
        self._execution_provider = None
        self._worker_id = None
        self._detail = "Core embedding service has not been initialized"
        self._last_error_code = None
        self._updated_at = utc_now()

    def _set(self, state: str, **updates) -> None:
        if state not in CORE_SERVICE_STATES:
            raise ValueError(f"Invalid core service state: {state}")
        with self._lock:
            self._state = state
            for key, value in updates.items():
                setattr(self, f"_{key}", value)
            self._updated_at = utc_now()

    def initialize(self, provider, *, manager=None, scheduler=None) -> dict[str, Any]:
        self._provider = provider
        self._manager = manager
        self._scheduler = scheduler
        self._set(
            "initializing",
            residency_state="initializing",
            detail="Inspecting the core embedding runtime",
            last_error_code=None,
        )
        provider_status = provider.status()
        if not provider_status.available:
            self._set(
                "unavailable",
                residency_state="unavailable",
                backend=None,
                execution_provider=None,
                worker_id=None,
                detail=provider_status.detail or "Core embedding runtime is unavailable",
                last_error_code="EMBEDDING_RUNTIME_UNAVAILABLE",
            )
            return self.status()

        manifest = getattr(provider, "manifest", None)
        if manifest is None:
            execution_provider = provider_status.execution_provider
            self._set(
                "ready_warm" if execution_provider else "ready_controlled",
                residency_state="resident" if execution_provider else "controlled",
                backend="in_process" if execution_provider else None,
                execution_provider=execution_provider,
                detail=provider_status.detail or "",
                last_error_code=None,
            )
            return self.status()

        if self._manager is None:
            from services.model_runtime.manager import get_worker_manager

            self._manager = get_worker_manager()
        if self._scheduler is None:
            self._scheduler = self._manager.scheduler

        try:
            requested_backend = _requested_backend()
        except ValueError as exc:
            self._set(
                "unavailable",
                residency_state="configuration_error",
                backend=None,
                execution_provider=None,
                detail=str(exc),
                last_error_code="INVALID_EMBEDDING_ACCELERATOR",
            )
            return self.status()

        try:
            scheduling_manifest = _scheduling_manifest(manifest)
            snapshot = self._scheduler.capture_snapshot()
            gpu_target = (
                _compatible_gpu(snapshot, scheduling_manifest, requested_backend)
                if requested_backend != "cpu" and _prewarm_enabled()
                else None
            )
            if gpu_target is not None:
                _device, selected_backend = gpu_target
                worker = self._manager.start_worker(
                    CORE_EMBEDDING_PACKAGE_ID,
                    residency_mode="PINNED",
                )
                self._worker_id = worker["id"]
                loaded = self._manager.load_worker(
                    worker["id"],
                    WorkerLoadRequest(
                        task_id="core-embedding-prewarm",
                        requested_backend=selected_backend,
                        requested_lease_mode=LeaseMode.SHARED,
                        priority=100,
                    ),
                )
                runtime = loaded.get("runtime") or {}
                effective_backend = (
                    runtime.get("effective_backend")
                    or loaded["worker"].get("effective_backend")
                    or selected_backend
                )
                execution_provider = runtime.get("execution_provider")
                if hasattr(provider, "record_execution"):
                    provider.record_execution(
                        {
                            "effective_backend": effective_backend,
                            "execution_provider": execution_provider,
                        }
                    )
                self._set(
                    "ready_warm",
                    residency_state="resident",
                    backend=effective_backend,
                    execution_provider=execution_provider,
                    worker_id=worker["id"],
                    detail="Core BGE-M3 Worker is prewarmed and protected",
                    last_error_code=None,
                )
                return self.status()

            worker = self._manager.start_worker(
                CORE_EMBEDDING_PACKAGE_ID,
                residency_mode="ON_DEMAND",
            )
            no_gpu = not snapshot.devices or requested_backend == "cpu"
            self._set(
                "degraded_cpu" if no_gpu else "ready_controlled",
                residency_state="controlled_cold",
                backend="cpu",
                execution_provider=None,
                worker_id=worker["id"],
                detail=(
                    "Core BGE-M3 is available through controlled CPU loading"
                    if no_gpu
                    else "GPU budget is insufficient; core BGE-M3 uses controlled loading"
                ),
                last_error_code=None,
            )
        except Exception as exc:
            self.record_failure(exc)
        return self.status()

    def before_request(self) -> None:
        with self._lock:
            if self._state == "unavailable":
                return
        self._set(
            "recovering",
            residency_state="loading",
            detail="Core BGE-M3 is loading for a vector request",
            last_error_code=None,
        )

    def record_execution(self, result: dict[str, Any]) -> None:
        backend = result.get("effective_backend")
        execution_provider = result.get("execution_provider")
        worker = (
            self._manager.get_worker(self._worker_id)
            if self._manager is not None and self._worker_id
            else None
        )
        if backend == "cpu":
            state = "degraded_cpu"
        elif worker and worker.get("residency_mode") == "PINNED":
            state = "ready_warm"
        else:
            state = "ready_controlled"
        self._set(
            state,
            residency_state=(
                "resident"
                if worker and worker.get("state") in {"READY", "BUSY"}
                else "controlled_cold"
            ),
            backend=backend,
            execution_provider=execution_provider,
            detail="" if state == "ready_warm" else "Core BGE-M3 uses controlled loading",
            last_error_code=None,
        )

    def record_failure(self, exc: Exception) -> None:
        self._set(
            "recovering",
            residency_state="recovery_required",
            execution_provider=None,
            detail=getattr(
                exc,
                "safe_message",
                f"Core embedding runtime failed: {type(exc).__name__}",
            ),
            last_error_code=getattr(exc, "code", "CORE_EMBEDDING_RUNTIME_FAILED"),
        )

    def recover(self) -> dict[str, Any]:
        if self._provider is None:
            return self.status()
        return self.initialize(
            self._provider,
            manager=self._manager,
            scheduler=self._scheduler,
        )

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            residency_state = self._residency_state
            backend = self._backend
            execution_provider = self._execution_provider
            worker_id = self._worker_id
            detail = self._detail
            last_error_code = self._last_error_code
            updated_at = self._updated_at
            manager = self._manager

        worker = manager.get_worker(worker_id) if manager is not None and worker_id else None
        if worker:
            worker_state = worker.get("state")
            if worker_state in {"FAILED", "STOPPED"} and state != "unavailable":
                state = "recovering"
                residency_state = "recovery_required"
                detail = worker.get("error_message") or "Core embedding Worker requires recovery"
                last_error_code = worker.get("error_code") or "CORE_WORKER_NOT_RUNNING"
            elif worker_state == "COLD":
                residency_state = "controlled_cold"
            elif worker_state in {"READY", "BUSY"}:
                residency_state = "resident"
        else:
            worker_state = None

        return {
            "service": "core_embedding",
            "package_id": CORE_EMBEDDING_PACKAGE_ID,
            "state": state,
            "available": state not in {"unavailable"},
            "residency_state": residency_state,
            "backend": backend,
            "execution_provider": execution_provider,
            "worker_id": worker_id,
            "worker_state": worker_state,
            "detail": detail,
            "last_error_code": last_error_code,
            "updated_at": updated_at,
        }


_core_embedding_service = CoreEmbeddingService()


def get_core_embedding_service() -> CoreEmbeddingService:
    return _core_embedding_service
