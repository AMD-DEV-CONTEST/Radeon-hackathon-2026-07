import hashlib
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

import services.database_registry as database_registry
from services.db import close_connection, init_db
from services.embedding import WorkerEmbeddingProvider
from services.embedding_runtime import EmbeddingRuntimeUnavailable, load_bge_m3_manifest
from services.model_packages.manifest import load_package_manifest
from services.model_packages.registry import sync_catalog, update_installation
from services.model_packages.verifier import package_target, write_verification_record
from services.model_runtime.contracts import (
    ComputeDeviceSnapshot,
    ResourceSnapshot,
    RuntimePolicyUpdate,
    SchedulingPolicy,
    WorkerLoadRequest,
)
from services.model_runtime.manager import (
    WorkerManager,
    WorkerManagerError,
    _safe_worker_environment,
)
from services.model_runtime.scheduler import ResourceScheduler


def package_payload(package_id: str, adapter: str = "test_worker"):
    payload = package_id.encode("utf-8")
    return {
        "schema_version": 1,
        "package_id": package_id,
        "package_version": "1.0.0",
        "display_name": package_id,
        "package_kind": "test_model",
        "core_required": False,
        "model_profile_id": None,
        "model_family": f"test/{package_id}",
        "modalities": ["text"],
        "capabilities": ["embedding"],
        "runtime_adapter": adapter,
        "supported_platforms": ["windows", "linux", "macos"],
        "supported_architectures": ["x86_64", "arm64"],
        "supported_backends": ["rocm_migraphx", "cuda", "cpu"],
        "install_subdir": package_id,
        "install_size_bytes": len(payload),
        "model_size_bytes": len(payload),
        "resource_profile": {
            "minimum_ram_mb": 64,
            "recommended_ram_mb": 128,
            "minimum_vram_mb": 256,
            "recommended_vram_mb": 256,
            "evidence_level": "estimated",
        },
        "embedding": {
            "dimension": 8,
            "normalization": "l2",
            "vector_schema_version": 1,
            "vector_space_id": f"test.{package_id}.v1",
        },
        "residency_policy_default": "shared",
        "runtime_policy": None,
        "offload_capabilities": ["cpu_fallback"],
        "license": {
            "license_id": "TEST",
            "display_name": "Test",
            "url": "https://example.test/license",
            "redistribution_allowed": False,
            "requires_acceptance": False,
            "notice_path": None,
        },
        "source": {
            "kind": "offline_only",
            "base_url": None,
            "trusted_redirect_hosts": [],
            "revision": "test",
        },
        "files": [
            {
                "path": "model.bin",
                "download_path": "model.bin",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "role": "model",
            }
        ],
    }


def device(index: int):
    device_id = f"rocm:test-{index}"
    return ComputeDeviceSnapshot(
        device_id=device_id,
        visible_index=index,
        vendor="AMD",
        name=f"AMD Test GPU {index}",
        backend="rocm_migraphx",
        total_vram_mb=8192,
        used_vram_mb=0,
        free_vram_mb=8192,
        utilization_percent=0,
        driver_version="test",
        device_uuid=f"test-{index}",
        source="rocm-smi",
        fingerprint=hashlib.sha256(device_id.encode()).hexdigest(),
    )


def snapshot_provider(device_count=0):
    devices = tuple(device(index) for index in range(device_count))

    def build():
        return ResourceSnapshot(
            snapshot_id=uuid.uuid4().hex,
            captured_at=datetime.now(timezone.utc).isoformat(),
            platform="Linux",
            architecture="x86_64",
            total_ram_mb=65536,
            available_ram_mb=60000,
            model_disk_total_mb=100000,
            model_disk_free_mb=90000,
            devices=devices,
        )

    return build


def setup_packages(tmp_path, monkeypatch, packages):
    runtime = tmp_path / "runtime"
    catalog = tmp_path / "catalog"
    models = tmp_path / "models"
    catalog.mkdir()
    monkeypatch.setattr(database_registry, "REGISTRY_PATH", str(runtime / "registry.db"))
    monkeypatch.setattr(database_registry, "DATABASES_ROOT", str(runtime / "databases"))
    monkeypatch.setattr(database_registry, "OLD_DB_PATH", str(runtime / "missing.db"))
    monkeypatch.setenv("AETHERDB_MODEL_PACKAGE_CATALOG", str(catalog))
    monkeypatch.setenv("AETHERDB_MODEL_PACKAGE_ROOT", str(models))
    monkeypatch.setenv("AETHERDB_ENV", "test")
    for package_id, adapter in packages:
        path = catalog / f"{package_id}.json"
        path.write_text(
            json.dumps(package_payload(package_id, adapter)),
            encoding="utf-8",
        )
    database_registry.init_registry()
    init_db()
    sync_catalog()
    for package_id, _adapter in packages:
        manifest = load_package_manifest(catalog / f"{package_id}.json")
        target, _ = package_target(manifest)
        target.mkdir(parents=True)
        (target / "model.bin").write_bytes(package_id.encode("utf-8"))
        write_verification_record(manifest, target)
        update_installation(
            package_id,
            status="installed",
            verified_files=1,
            total_files=1,
            installed_size_bytes=len(package_id.encode("utf-8")),
        )


def test_monitor_recovers_if_registry_schema_is_temporarily_missing(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(database_registry, "REGISTRY_PATH", str(runtime / "registry.db"))
    monkeypatch.setattr(database_registry, "DATABASES_ROOT", str(runtime / "databases"))
    monkeypatch.setattr(database_registry, "OLD_DB_PATH", str(runtime / "missing.db"))
    manager = WorkerManager(
        scheduler=ResourceScheduler(snapshot_provider(0)),
        monitor_interval_seconds=0.1,
    )
    try:
        conn = database_registry._get_registry_conn()
        try:
            conn.execute("DROP TABLE model_worker_instances")
            conn.commit()
        finally:
            conn.close()

        deadline = time.monotonic() + 3
        exists = None
        while time.monotonic() < deadline:
            with sqlite3.connect(database_registry.REGISTRY_PATH) as conn:
                exists = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='model_worker_instances'"
                ).fetchone()
            if exists:
                break
            time.sleep(0.05)

        assert exists is not None
        assert manager.list_workers() == []
    finally:
        manager.shutdown()
        close_connection()


def test_worker_process_lifecycle_and_persistent_job(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    manager = WorkerManager(
        scheduler=ResourceScheduler(snapshot_provider(0)),
        monitor_interval_seconds=0.2,
    )
    try:
        worker = manager.start_worker("test.echo-a")
        assert worker["state"] == "COLD"
        assert worker["process_id"] not in {None, 0}
        assert worker["process_id"] != __import__("os").getpid()

        loaded = manager.load_worker(
            worker["id"],
            WorkerLoadRequest(task_id="load-cpu", requested_backend="cpu"),
        )
        assert loaded["worker"]["state"] == "READY"
        assert loaded["worker"]["lease_id"]
        logical_lease = manager.scheduler.list_leases(active_only=True)[0]
        assert logical_lease["resource_class"] == "CPU_PARALLEL"
        assert logical_lease["device_id"] == "logical:cpu"

        execution = manager.execute(
            "test.echo-a",
            task_id="echo-job",
            operation="test",
            payload={"value": "isolated"},
            requested_backend="cpu",
        )
        assert execution["result"]["echo"] == "isolated"
        job = manager.get_job(execution["job_id"])
        assert job["status"] == "completed"
        assert "isolated" not in job["result_metadata_json"]

        assert manager.unload_worker(worker["id"])["state"] == "COLD"
        assert manager.scheduler.list_leases(active_only=True) == []
        assert manager.stop_worker(worker["id"])["state"] == "STOPPED"
    finally:
        manager.shutdown()
        close_connection()


def test_two_model_workers_run_in_parallel_on_separate_devices(tmp_path, monkeypatch):
    setup_packages(
        tmp_path,
        monkeypatch,
        [("test.echo-a", "test_worker"), ("test.echo-b", "test_worker")],
    )
    scheduler = ResourceScheduler(snapshot_provider(2))
    scheduler.update_policy(
        RuntimePolicyUpdate(
            scheduling_policy=SchedulingPolicy.PARALLEL,
            competition_mode=False,
        )
    )
    manager = WorkerManager(scheduler=scheduler, monitor_interval_seconds=0.2)
    try:
        worker_a = manager.start_worker("test.echo-a")
        worker_b = manager.start_worker("test.echo-b")
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    manager.execute,
                    package_id,
                    task_id=f"parallel-{package_id}",
                    operation="test",
                    payload={"value": package_id, "delay_seconds": 0.5},
                    requested_backend="rocm_migraphx",
                )
                for package_id in ("test.echo-a", "test.echo-b")
            ]
            results = [future.result(timeout=5) for future in futures]
        elapsed = time.monotonic() - started
        current_a = manager.get_worker(worker_a["id"])
        current_b = manager.get_worker(worker_b["id"])

        assert elapsed < 0.9
        assert {item["result"]["echo"] for item in results} == {
            "test.echo-a",
            "test.echo-b",
        }
        assert current_a["process_id"] != current_b["process_id"]
        assert current_a["device_id"] != current_b["device_id"]
        assert len(scheduler.list_leases(active_only=True)) == 2
    finally:
        manager.shutdown()
        close_connection()


def test_worker_crash_fails_job_and_releases_gpu_lease(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    scheduler = ResourceScheduler(snapshot_provider(1))
    manager = WorkerManager(scheduler=scheduler, monitor_interval_seconds=0.1)
    try:
        with pytest.raises(WorkerManagerError, match="exited"):
            manager.execute(
                "test.echo-a",
                task_id="crash-job",
                operation="test",
                payload={"crash": True},
                requested_backend="rocm_migraphx",
                timeout=5,
            )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            workers = manager.list_workers()
            if workers and workers[0]["state"] == "FAILED":
                break
            time.sleep(0.05)

        assert manager.list_workers()[0]["state"] == "FAILED"
        assert scheduler.list_leases(active_only=True) == []
        assert manager.list_jobs()[0]["status"] == "failed"
    finally:
        manager.shutdown()
        close_connection()


def test_running_job_can_be_cancelled_without_killing_worker(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    manager = WorkerManager(
        scheduler=ResourceScheduler(snapshot_provider(0)),
        monitor_interval_seconds=0.1,
    )
    captured = {}

    def run():
        try:
            manager.execute(
                "test.echo-a",
                task_id="cancel-job",
                operation="test",
                payload={"value": "cancel", "delay_seconds": 2},
                requested_backend="cpu",
                timeout=5,
            )
        except Exception as exc:
            captured["error"] = exc

    try:
        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 3
        job = None
        while time.monotonic() < deadline:
            jobs = manager.list_jobs()
            if jobs and jobs[0]["status"] == "running":
                job = jobs[0]
                break
            time.sleep(0.02)
        assert job is not None
        manager.cancel_job(job["id"])
        thread.join(timeout=5)

        assert isinstance(captured.get("error"), WorkerManagerError)
        assert captured["error"].code == "CANCELLED"
        assert manager.get_job(job["id"])["status"] == "cancelled"
        assert manager.list_workers()[0]["state"] == "READY"
    finally:
        manager.shutdown()
        close_connection()


def test_heartbeat_updates_measured_vram_and_renews_lease(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    scheduler = ResourceScheduler(snapshot_provider(1))
    manager = WorkerManager(scheduler=scheduler, monitor_interval_seconds=0.1)
    try:
        worker = manager.start_worker("test.echo-a")
        loaded = manager.load_worker(
            worker["id"],
            WorkerLoadRequest(
                task_id="heartbeat",
                requested_backend="rocm_migraphx",
            ),
        )
        lease_id = loaded["worker"]["lease_id"]
        initial_expiry = scheduler.list_leases(active_only=True)[0]["expires_at"]
        time.sleep(2.3)
        lease = next(item for item in scheduler.list_leases() if item["id"] == lease_id)
        current = manager.get_worker(worker["id"])

        assert lease["actual_vram_mb"] == 64
        assert lease["actual_peak_vram_mb"] == 96
        assert lease["expires_at"] > initial_expiry
        assert current["last_heartbeat_at"] is not None
    finally:
        manager.shutdown()
        close_connection()


def test_worker_probe_creates_exact_backend_evidence_and_unloads(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    scheduler = ResourceScheduler(snapshot_provider(1))
    manager = WorkerManager(scheduler=scheduler, monitor_interval_seconds=0.1)
    try:
        worker = manager.start_worker("test.echo-a")
        result = manager.probe_worker(
            worker["id"],
            requested_backend="rocm_migraphx",
        )

        assert result["probe"]["verified"] is True
        assert result["evidence"]["verification_status"] == "VERIFIED_ROCM"
        assert result["evidence"]["device_fingerprint"] == device(0).fingerprint
        assert result["worker"]["state"] == "COLD"
        assert scheduler.list_leases(active_only=True) == []
    finally:
        manager.shutdown()
        close_connection()


def test_worker_probe_recovers_busy_state_before_unload(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    scheduler = ResourceScheduler(snapshot_provider(1))
    manager = WorkerManager(scheduler=scheduler, monitor_interval_seconds=0.1)
    try:
        worker = manager.start_worker("test.echo-a")
        client = manager._clients[worker["id"]]
        original_request = client.request

        def request_with_busy_probe(command, payload=None, **kwargs):
            response = original_request(command, payload, **kwargs)
            if command == "probe":
                manager._update_worker(worker["id"], state="BUSY")
            return response

        monkeypatch.setattr(client, "request", request_with_busy_probe)
        result = manager.probe_worker(
            worker["id"],
            requested_backend="rocm_migraphx",
        )

        assert result["probe"]["verified"] is True
        assert result["worker"]["state"] == "COLD"
        assert scheduler.list_leases(active_only=True) == []
    finally:
        manager.shutdown()
        close_connection()


def test_manager_recovers_orphaned_worker_and_lease(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.echo-a", "test_worker")])
    now = datetime.now(timezone.utc).isoformat()
    conn = database_registry._get_registry_conn()
    try:
        conn.execute(
            "INSERT INTO model_worker_instances "
            "(id,replica_id,package_id,package_version,manifest_digest,runtime_adapter,"
            "residency_mode,state,process_id,python_runtime,idle_unload_seconds,started_at) "
            "VALUES ('orphan','default','test.echo-a','1.0.0',?,'test_worker',"
            "'PREFERRED','READY',999999,'python',300,?)",
            ("a" * 64, now),
        )
        conn.execute(
            "INSERT INTO model_resource_leases "
            "(id,device_id,device_fingerprint,worker_id,model_package_id,task_id,"
            "lease_mode,status,effective_backend,reserved_vram_mb,"
            "estimated_peak_vram_mb,runtime_context_overhead_mb,safety_margin_mb,"
            "priority,snapshot_id,acquired_at,heartbeat_at,expires_at) "
            "VALUES ('lease','rocm:0',?,'orphan','test.echo-a','task','EXCLUSIVE',"
            "'active','rocm_migraphx',1024,256,256,512,50,'snapshot',?,?,?)",
            ("b" * 64, now, now, "2999-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    manager = WorkerManager(
        scheduler=ResourceScheduler(snapshot_provider(1)),
        monitor_interval_seconds=0.1,
    )
    try:
        assert manager.get_worker("orphan")["state"] == "FAILED"
        assert manager.get_worker("orphan")["error_code"] == "PROCESS_LOST"
        assert manager.scheduler.list_leases(active_only=True) == []
    finally:
        manager.shutdown()
        close_connection()


def test_unregistered_adapter_never_starts_arbitrary_package_code(tmp_path, monkeypatch):
    setup_packages(tmp_path, monkeypatch, [("test.unsafe", "custom_python_import")])
    manager = WorkerManager(
        scheduler=ResourceScheduler(snapshot_provider(0)),
        monitor_interval_seconds=0.1,
    )
    try:
        with pytest.raises(WorkerManagerError) as captured:
            manager.start_worker("test.unsafe")
        assert captured.value.code == "UNSUPPORTED_ADAPTER"
        assert manager.list_workers() == []
    finally:
        manager.shutdown()
        close_connection()


def test_worker_environment_does_not_inherit_application_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("REAL_API_KEY", "must-not-cross-process-boundary")
    monkeypatch.setenv("DATABASE_PASSWORD", "must-not-cross-process-boundary")
    monkeypatch.setenv("AUTHORIZATION", "Bearer must-not-cross")

    environment = _safe_worker_environment(tmp_path)

    assert "REAL_API_KEY" not in environment
    assert "DATABASE_PASSWORD" not in environment
    assert "AUTHORIZATION" not in environment
    assert environment["PYTHONPATH"] == str(tmp_path)


class FakeEmbeddingManager:
    def __init__(self):
        self.last_kwargs = None

    def execute(self, package_id, **kwargs):
        assert package_id == "aetherdb.bge-m3"
        assert kwargs["operation"] == "embedding"
        self.last_kwargs = kwargs
        texts = kwargs["payload"]["texts"]
        return {
            "job_id": "job",
            "result": {
                "vectors": [[1.0] + [0.0] * 1023 for _ in texts],
                "execution_provider": "CPUExecutionProvider",
            },
        }


def test_worker_embedding_provider_validates_canonical_vectors():
    manifest = load_bge_m3_manifest()
    provider = WorkerEmbeddingProvider(manifest, manager=FakeEmbeddingManager())

    vectors = provider.embed_batch(["中文", "English"])

    assert len(vectors) == 2
    assert len(vectors[0]) == 1024
    assert provider.status().execution_provider == "CPUExecutionProvider"


def test_worker_embedding_provider_passes_bounded_timeouts(monkeypatch):
    monkeypatch.setenv("AETHERDB_EMBEDDING_LOAD_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("AETHERDB_EMBEDDING_INFER_TIMEOUT_SECONDS", "34")
    manager = FakeEmbeddingManager()
    provider = WorkerEmbeddingProvider(load_bge_m3_manifest(), manager=manager)

    provider.embed("test")

    assert manager.last_kwargs["load_timeout"] == 12
    assert manager.last_kwargs["timeout"] == 34


def test_worker_embedding_provider_surfaces_safe_worker_failure():
    class BrokenManager:
        def execute(self, *_args, **_kwargs):
            raise WorkerManagerError("NO_DEVICE", "No compatible device")

    provider = WorkerEmbeddingProvider(load_bge_m3_manifest(), manager=BrokenManager())
    with pytest.raises(EmbeddingRuntimeUnavailable, match="No compatible device"):
        provider.embed("test")
