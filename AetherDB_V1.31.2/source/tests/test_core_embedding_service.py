from pathlib import Path
from types import SimpleNamespace

from services.embedding_runtime import EmbeddingRuntimeStatus
from services.embedding_runtime.manifest import load_bge_m3_manifest
from services.model_packages.manifest import load_package_manifest
from services.model_runtime.contracts import (
    ComputeDeviceSnapshot,
    ResourceSnapshot,
)
from services.model_runtime.core_service import CoreEmbeddingService


MANIFEST_PATH = Path("resources/model_packages/aetherdb-bge-m3.json")


def snapshot(*devices):
    return ResourceSnapshot(
        snapshot_id="core-test",
        captured_at="2026-07-30T00:00:00+00:00",
        platform="Linux",
        architecture="x86_64",
        total_ram_mb=65536,
        available_ram_mb=50000,
        model_disk_total_mb=100000,
        model_disk_free_mb=80000,
        devices=devices,
    )


def gpu(*, free_vram_mb=24000):
    return ComputeDeviceSnapshot(
        device_id="rocm:core-test",
        visible_index=0,
        vendor="AMD",
        name="AMD Core Test GPU",
        backend="rocm_migraphx",
        total_vram_mb=24576,
        used_vram_mb=24576 - free_vram_mb,
        free_vram_mb=free_vram_mb,
        utilization_percent=0,
        driver_version="test",
        device_uuid="core-test",
        source="rocm-smi",
        fingerprint="a" * 64,
    )


class FakeProvider:
    def __init__(self, *, available=True, detail=""):
        self.manifest = load_package_manifest(MANIFEST_PATH)
        self._status = EmbeddingRuntimeStatus(
            available=available,
            model_id="BAAI/bge-m3",
            revision="test",
            dimensions=1024,
            execution_provider=None,
            detail=detail,
        )
        self.executions = []

    def status(self):
        return self._status

    def record_execution(self, result):
        self.executions.append(result)


class FakeRuntimeManifestProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.manifest = load_bge_m3_manifest()


class FakeScheduler:
    def __init__(self, current):
        self.current = current

    def capture_snapshot(self):
        return self.current


class FakeManager:
    def __init__(self, *, fail_load=False):
        self.fail_load = fail_load
        self.worker = None
        self.load_requests = []

    def start_worker(self, package_id, *, residency_mode=None):
        if self.worker is None or self.worker["state"] in {"FAILED", "STOPPED"}:
            self.worker = {
                "id": "core-worker",
                "package_id": package_id,
                "state": "COLD",
                "residency_mode": residency_mode,
                "effective_backend": None,
                "error_code": None,
                "error_message": None,
            }
        else:
            self.worker["residency_mode"] = residency_mode
        return dict(self.worker)

    def load_worker(self, worker_id, request):
        self.load_requests.append(request)
        if self.fail_load:
            self.worker.update(
                state="FAILED",
                error_code="WORKER_LOAD_FAILED",
                error_message="Core test load failed",
            )
            error = RuntimeError("load failed")
            error.code = "WORKER_LOAD_FAILED"
            error.safe_message = "Core test load failed"
            raise error
        self.worker.update(
            state="READY",
            effective_backend=request.requested_backend,
            error_code=None,
            error_message=None,
        )
        return {
            "worker": dict(self.worker),
            "runtime": {
                "effective_backend": request.requested_backend,
                "execution_provider": "MIGraphXExecutionProvider",
            },
        }

    def get_worker(self, worker_id):
        return dict(self.worker) if self.worker and self.worker["id"] == worker_id else None


def test_sufficient_gpu_prewarms_and_pins_core_embedding(monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
    provider = FakeProvider()
    manager = FakeManager()
    service = CoreEmbeddingService()

    status = service.initialize(
        provider,
        manager=manager,
        scheduler=FakeScheduler(snapshot(gpu())),
    )

    assert status["state"] == "ready_warm"
    assert status["residency_state"] == "resident"
    assert status["backend"] == "rocm_migraphx"
    assert manager.worker["residency_mode"] == "PINNED"
    assert manager.load_requests[0].priority == 100
    assert provider.executions[0]["execution_provider"] == "MIGraphXExecutionProvider"


def test_cpu_only_environment_uses_truthful_controlled_loading(monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
    service = CoreEmbeddingService()
    manager = FakeManager()

    status = service.initialize(
        FakeProvider(),
        manager=manager,
        scheduler=FakeScheduler(snapshot()),
    )

    assert status["state"] == "degraded_cpu"
    assert status["residency_state"] == "controlled_cold"
    assert status["backend"] == "cpu"
    assert status["execution_provider"] is None
    assert manager.worker["residency_mode"] == "ON_DEMAND"
    assert manager.load_requests == []


def test_runtime_embedding_manifest_uses_package_scheduling_defaults(monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
    service = CoreEmbeddingService()
    manager = FakeManager()

    status = service.initialize(
        FakeRuntimeManifestProvider(),
        manager=manager,
        scheduler=FakeScheduler(snapshot()),
    )

    assert status["state"] == "degraded_cpu"
    assert status["last_error_code"] is None
    assert manager.worker["residency_mode"] == "ON_DEMAND"


def test_low_vram_environment_reports_controlled_state(monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
    service = CoreEmbeddingService()

    status = service.initialize(
        FakeProvider(),
        manager=FakeManager(),
        scheduler=FakeScheduler(snapshot(gpu(free_vram_mb=4096))),
    )

    assert status["state"] == "ready_controlled"
    assert status["residency_state"] == "controlled_cold"
    assert status["execution_provider"] is None


def test_missing_artifacts_leave_database_capability_state_unavailable():
    service = CoreEmbeddingService()

    status = service.initialize(
        FakeProvider(available=False, detail="BGE-M3 artifacts are missing"),
        manager=SimpleNamespace(),
        scheduler=SimpleNamespace(),
    )

    assert status["state"] == "unavailable"
    assert status["available"] is False
    assert status["last_error_code"] == "EMBEDDING_RUNTIME_UNAVAILABLE"


def test_failed_prewarm_is_recoverable(monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_ACCELERATOR", "rocm")
    service = CoreEmbeddingService()
    manager = FakeManager(fail_load=True)
    provider = FakeProvider()
    scheduler = FakeScheduler(snapshot(gpu()))

    failed = service.initialize(provider, manager=manager, scheduler=scheduler)
    assert failed["state"] == "recovering"
    assert failed["last_error_code"] == "WORKER_LOAD_FAILED"

    manager.fail_load = False
    recovered = service.recover()
    assert recovered["state"] == "ready_warm"
    assert recovered["last_error_code"] is None
