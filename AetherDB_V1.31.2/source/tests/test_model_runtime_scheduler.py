import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import services.database_registry as database_registry
from app.dependencies.auth import ADMIN_API_KEY
from main import app
from services.db import close_connection, init_db
from services.model_packages.registry import sync_catalog, update_installation
from services.model_registry import create_provider
from services.ollama_observability import (
    record_model_observation,
    record_runtime_observation,
)
from services.model_runtime.contracts import (
    AdmissionRequest,
    AdmissionStatus,
    ComputeDeviceSnapshot,
    ResourceClass,
    LeaseMode,
    ResourceSnapshot,
    RuntimePolicyUpdate,
    SchedulingPolicy,
)
from services.model_runtime.scheduler import ResourceScheduler
from services.model_runtime.hardware import parse_nvidia_smi_csv, parse_rocm_smi_json
from tests.asgi_client import asgi_request


ADMIN = {"X-API-Key": ADMIN_API_KEY}


def package_manifest(
    package_id: str,
    *,
    residency: str = "shared",
    vram_mb: int = 2048,
):
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
        "runtime_adapter": "test_worker",
        "supported_platforms": ["windows", "linux", "macos"],
        "supported_architectures": ["x86_64", "arm64"],
        "supported_backends": ["rocm_migraphx", "cuda", "cpu"],
        "install_subdir": package_id,
        "install_size_bytes": len(payload),
        "model_size_bytes": len(payload),
        "resource_profile": {
            "minimum_ram_mb": 128,
            "recommended_ram_mb": 256,
            "minimum_vram_mb": vram_mb,
            "recommended_vram_mb": vram_mb,
            "evidence_level": "estimated",
        },
        "embedding": {
            "dimension": 8,
            "normalization": "l2",
            "vector_schema_version": 1,
            "vector_space_id": f"test.{package_id}.v1",
        },
        "residency_policy_default": residency,
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


def gpu(device_id: str, index: int, free: int = 24000):
    return ComputeDeviceSnapshot(
        device_id=device_id,
        visible_index=index,
        vendor="AMD",
        name="AMD Test GPU",
        backend="rocm_migraphx",
        total_vram_mb=24576,
        used_vram_mb=24576 - free,
        free_vram_mb=free,
        utilization_percent=0,
        driver_version="test",
        device_uuid=device_id,
        source="rocm-smi",
        fingerprint=hashlib.sha256(device_id.encode()).hexdigest(),
    )


def snapshot(*devices):
    return ResourceSnapshot(
        snapshot_id="snapshot-test",
        captured_at=datetime.now(timezone.utc).isoformat(),
        platform="Linux",
        architecture="x86_64",
        total_ram_mb=65536,
        available_ram_mb=50000,
        model_disk_total_mb=100000,
        model_disk_free_mb=80000,
        devices=devices,
    )


def setup_runtime(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    for package_id in ("test.embed-a", "test.embed-b"):
        (catalog / f"{package_id}.json").write_text(
            json.dumps(package_manifest(package_id)),
            encoding="utf-8",
        )
    monkeypatch.setattr(database_registry, "REGISTRY_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setattr(database_registry, "DATABASES_ROOT", str(tmp_path / "databases"))
    monkeypatch.setattr(database_registry, "OLD_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("AETHERDB_MODEL_PACKAGE_CATALOG", str(catalog))
    database_registry.init_registry()
    init_db()
    sync_catalog()
    for package_id in ("test.embed-a", "test.embed-b"):
        update_installation(
            package_id,
            status="installed",
            verified_files=1,
            total_files=1,
            installed_size_bytes=len(package_id.encode()),
        )


def test_conservative_policy_queues_second_gpu_model(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    first = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="a"),
        snapshot=current,
        acquire=True,
        worker_id="worker-a",
    )
    second = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-b", task_id="b"),
        snapshot=current,
    )

    assert first.status == AdmissionStatus.ADMITTED
    assert first.lease_id
    assert second.status == AdmissionStatus.QUEUED
    assert second.blocking_lease_ids == (first.lease_id,)


def test_local_ollama_and_native_gpu_tasks_share_one_admission_boundary(
    tmp_path, monkeypatch
):
    setup_runtime(tmp_path, monkeypatch)
    provider = create_provider(
        {
            "id": "ollama-local-scheduler",
            "display_name": "Local Ollama",
            "provider_type": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "api_format": "ollama_chat",
            "enabled": True,
        }
    )
    runtime = record_runtime_observation(
        provider,
        ownership="aetherdb_managed",
        state="ready",
        installed=True,
        running=True,
        api_compatible=True,
        version="0.12.0",
        compatibility="compatible",
    )
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    ollama_request = AdmissionRequest(
        task_id="ollama-task",
        resource_class=ResourceClass.REMOTE_RUNTIME,
        requested_backend="remote",
        runtime_id=runtime["runtime_id"],
        model_id="writer:latest",
    )
    ollama = scheduler.evaluate(
        ollama_request,
        snapshot=current,
        acquire=True,
    )
    assert ollama.status is AdmissionStatus.ADMITTED

    native_blocked = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="native-blocked"),
        snapshot=current,
    )
    assert native_blocked.status is AdmissionStatus.QUEUED
    assert native_blocked.reason_code == "LOCAL_OLLAMA_TASK_ACTIVE"
    scheduler.release_lease(ollama.lease_id)

    native = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="native"),
        snapshot=current,
        acquire=True,
        worker_id="worker-native",
    )
    assert native.status is AdmissionStatus.ADMITTED
    ollama_blocked = scheduler.evaluate(ollama_request, snapshot=current)
    assert ollama_blocked.status is AdmissionStatus.QUEUED
    assert ollama_blocked.reason_code == "LOCAL_RUNTIME_GPU_BUSY"


def test_parallel_policy_assigns_exclusive_models_to_different_devices(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0), gpu("rocm:1", 1))
    scheduler = ResourceScheduler(lambda: current)
    scheduler.update_policy(
        RuntimePolicyUpdate(
            scheduling_policy=SchedulingPolicy.PARALLEL,
            competition_mode=False,
        )
    )
    first = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="a",
            requested_lease_mode=LeaseMode.EXCLUSIVE,
        ),
        snapshot=current,
        acquire=True,
        worker_id="worker-a",
    )
    second = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-b",
            task_id="b",
            requested_lease_mode=LeaseMode.EXCLUSIVE,
        ),
        snapshot=current,
        acquire=True,
        worker_id="worker-b",
    )

    assert first.status == second.status == AdmissionStatus.ADMITTED
    assert first.device_id != second.device_id


def test_shared_requires_pair_benchmark_before_same_device_parallelism(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    scheduler.update_policy(
        RuntimePolicyUpdate(
            scheduling_policy=SchedulingPolicy.PARALLEL,
            competition_mode=True,
        )
    )
    for package_id in ("test.embed-a", "test.embed-b"):
        scheduler.record_runtime_evidence(
            package_id=package_id,
            device_fingerprint=current.devices[0].fingerprint,
            backend="rocm_migraphx",
            verification_status="VERIFIED_ROCM",
            probe_ref="isolated-runtime-probe",
        )
    first = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="a",
            requested_lease_mode=LeaseMode.SHARED,
        ),
        snapshot=current,
        acquire=True,
        worker_id="worker-a",
    )
    blocked = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-b",
            task_id="b",
            requested_lease_mode=LeaseMode.SHARED,
        ),
        snapshot=current,
    )
    scheduler.record_coexistence_evidence(
        package_a="test.embed-a",
        package_b="test.embed-b",
        device_fingerprint=current.devices[0].fingerprint,
        backend="rocm_migraphx",
        benchmark_ref="isolated-test-benchmark",
        verified=True,
    )
    admitted = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-b",
            task_id="b",
            requested_lease_mode=LeaseMode.SHARED,
        ),
        snapshot=current,
        acquire=True,
        worker_id="worker-b",
    )

    assert first.status == AdmissionStatus.ADMITTED
    assert blocked.status == AdmissionStatus.QUEUED
    assert admitted.status == AdmissionStatus.ADMITTED
    assert admitted.device_id == first.device_id


def test_explicit_gpu_request_never_silently_falls_back_to_cpu(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot()
    scheduler = ResourceScheduler(lambda: current)
    decision = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="gpu-required",
            requested_backend="rocm_migraphx",
        ),
        snapshot=current,
    )
    competition = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="competition",
            competition_mode=True,
        ),
        snapshot=current,
    )

    assert decision.status == AdmissionStatus.INSUFFICIENT_RESOURCES
    assert decision.effective_backend is None
    assert competition.status == AdmissionStatus.BLOCKED_BY_POLICY


def test_global_competition_mode_cannot_be_disabled_by_a_request(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    scheduler.update_policy(
        RuntimePolicyUpdate(
            scheduling_policy=SchedulingPolicy.CONSERVATIVE,
            competition_mode=True,
        )
    )
    decision = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="cannot-disable",
            competition_mode=False,
        ),
        snapshot=current,
    )

    assert decision.competition_mode is True
    assert decision.status == AdmissionStatus.BLOCKED_BY_POLICY
    assert decision.reason_code == "MODEL_RUNTIME_UNVERIFIED"


def test_competition_rocm_environment_blocks_explicit_cpu(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("AETHERDB_EXECUTION_MODE", "competition")
    monkeypatch.setenv("REQUIRE_ROCM", "true")
    scheduler = ResourceScheduler(lambda: snapshot(gpu("rocm:0", 0)))

    decision = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="competition-explicit-cpu",
            requested_backend="cpu",
            competition_mode=False,
        )
    )

    assert decision.status == AdmissionStatus.BLOCKED_BY_POLICY
    assert decision.reason_code == "COMPETITION_ROCM_REQUIRED"
    assert decision.competition_mode is True


def test_insufficient_vram_does_not_create_a_lease(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0, free=1024))
    scheduler = ResourceScheduler(lambda: current)
    decision = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="too-large"),
        snapshot=current,
        acquire=True,
        worker_id="worker-a",
    )

    assert decision.status == AdmissionStatus.INSUFFICIENT_RESOURCES
    assert scheduler.list_leases(active_only=True) == []


def test_ordinary_gpu_task_cannot_consume_unloaded_core_vector_budget(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    catalog = tmp_path / "catalog"
    core_payload = json.loads(
        Path("resources/model_packages/aetherdb-bge-m3.json").read_text(
            encoding="utf-8"
        )
    )
    (catalog / "aetherdb-bge-m3.json").write_text(
        json.dumps(core_payload),
        encoding="utf-8",
    )
    sync_catalog()
    update_installation(
        "aetherdb.bge-m3",
        status="installed",
        verified_files=len(core_payload["files"]),
        total_files=len(core_payload["files"]),
        installed_size_bytes=core_payload["install_size_bytes"],
    )
    current = snapshot(gpu("rocm:0", 0, free=13000))
    scheduler = ResourceScheduler(lambda: current)

    decision = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="ordinary-model"),
        snapshot=current,
    )

    assert decision.status == AdmissionStatus.QUEUED
    assert decision.reason_code == "CORE_SERVICE_BUDGET_PROTECTED"
    assert scheduler.list_leases(active_only=True) == []


def test_external_ollama_occupancy_is_observed_but_never_claimed_as_a_lease(
    tmp_path,
    monkeypatch,
):
    setup_runtime(tmp_path, monkeypatch)
    provider = {
        "id": "external-ollama",
        "base_url": "http://127.0.0.1:11434",
    }
    record_runtime_observation(
        provider,
        ownership="external",
        state="ready",
        installed=True,
        running=True,
        api_compatible=True,
        version="0.32.0",
        compatibility="tested_target",
    )
    record_model_observation(
        provider,
        "user-model:latest",
        tag_payload={
            "name": "user-model:latest",
            "size": 6 * 1024 * 1024 * 1024,
            "digest": "user-owned-digest",
        },
        loaded_payload={
            "name": "user-model:latest",
            "size": 6 * 1024 * 1024 * 1024,
            "size_vram": 4 * 1024 * 1024 * 1024,
        },
    )
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)

    occupancy = scheduler.observe_external_occupancy(current)

    external = next(
        item for item in occupancy if item["source"] == "external_runtime"
    )
    assert external["runtime_id"].startswith("ollama:")
    assert external["model_id"] == "user-model:latest"
    assert external["observed_vram_mb"] == 4096
    assert external["ownership"] == "external"
    assert scheduler.list_leases(active_only=True) == []

    decision = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="wait-for-external-work",
        ),
        snapshot=current,
    )
    assert decision.status == AdmissionStatus.QUEUED
    assert decision.reason_code == "EXTERNAL_RUNTIME_OCCUPIED"
    assert scheduler.list_leases(active_only=True) == []


def test_uninstalled_package_requires_install_without_a_lease(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    update_installation("test.embed-a", status="install_available")
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    decision = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="not-installed"),
        snapshot=current,
        acquire=True,
        worker_id="worker-a",
    )

    assert decision.status == AdmissionStatus.REQUIRES_INSTALL
    assert scheduler.list_leases(active_only=True) == []


def test_expired_lease_is_reclaimed(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    decision = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="expiring"),
        snapshot=current,
        acquire=True,
        worker_id="worker-a",
    )
    conn = database_registry._get_registry_conn()
    try:
        conn.execute(
            "UPDATE model_resource_leases SET expires_at=? WHERE id=?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                decision.lease_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert scheduler.cleanup_expired_leases() == 1
    assert scheduler.list_leases(active_only=True) == []


def test_cpu_and_remote_work_receive_logical_aetherdb_leases(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot()
    scheduler = ResourceScheduler(lambda: current)

    cpu = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="cpu-task",
            requested_backend="cpu",
            estimated_ram_mb=512,
        ),
        snapshot=current,
        acquire=True,
        worker_id="worker-cpu",
    )
    remote = scheduler.evaluate(
        AdmissionRequest(
            package_id=None,
            task_id="remote-task",
            resource_class=ResourceClass.REMOTE_RUNTIME,
            requested_backend="remote",
            runtime_id="ollama-external",
            model_id="writer:latest",
        ),
        snapshot=current,
        acquire=True,
    )

    assert cpu.lease_id and cpu.device_id == "logical:cpu"
    assert remote.lease_id and remote.device_id == "remote:ollama-external"
    leases = {item["id"]: item for item in scheduler.list_leases(active_only=True)}
    assert leases[cpu.lease_id]["resource_class"] == "CPU_PARALLEL"
    assert leases[cpu.lease_id]["estimated_ram_mb"] == 512
    assert leases[remote.lease_id]["owner_type"] == "aetherdb_task"
    assert leases[remote.lease_id]["runtime_id"] == "ollama-external"


def test_unattributed_device_usage_is_external_occupancy_not_a_lease(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0, free=20000))
    scheduler = ResourceScheduler(lambda: current)

    occupancy = scheduler.observe_external_occupancy(current)

    assert occupancy[0]["ownership"] == "external"
    assert occupancy[0]["source"] == "device_unattributed"
    assert occupancy[0]["observed_vram_mb"] == 4576
    assert scheduler.list_leases(active_only=True) == []


def test_terminal_worker_drift_releases_only_owned_lease(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    decision = scheduler.evaluate(
        AdmissionRequest(package_id="test.embed-a", task_id="owned"),
        snapshot=current,
        acquire=True,
        worker_id="worker-owned",
    )
    conn = database_registry._get_registry_conn()
    try:
        conn.execute(
            """INSERT INTO model_worker_instances(
                id,replica_id,package_id,package_version,manifest_digest,
                runtime_adapter,residency_mode,state,python_runtime,lease_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "worker-owned",
                "default",
                "test.embed-a",
                "1.0.0",
                "digest",
                "test_worker",
                "ON_DEMAND",
                "STOPPED",
                "python",
                decision.lease_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    issues = scheduler.detect_resource_drift(snapshot=current)
    assert any(item["code"] == "LEASE_OWNER_MISSING" for item in issues)
    result = scheduler.reconcile_owned_drift(snapshot=current)
    assert result["released_lease_ids"] == [decision.lease_id]
    assert scheduler.list_leases(active_only=True) == []


def test_core_resident_lease_cannot_be_selected_for_eviction(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    current = snapshot(gpu("rocm:0", 0))
    scheduler = ResourceScheduler(lambda: current)
    core = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-a",
            task_id="core",
            resource_class=ResourceClass.CORE_RESIDENT,
        ),
        snapshot=current,
        acquire=True,
        worker_id="core-worker",
    )
    challenger = scheduler.evaluate(
        AdmissionRequest(
            package_id="test.embed-b",
            task_id="challenger",
            priority=100,
        ),
        snapshot=current,
    )

    assert core.resource_class == ResourceClass.CORE_RESIDENT
    assert challenger.status == AdmissionStatus.QUEUED
    assert challenger.reason_code == "DEVICE_BUSY_OR_COEXISTENCE_UNVERIFIED"


def test_resource_api_is_admin_only_and_rejects_client_hardware_claims(tmp_path, monkeypatch):
    setup_runtime(tmp_path, monkeypatch)
    status, _ = asgi_request(app, "GET", "/api/model-runtime/policy")
    invalid_status, invalid = asgi_request(
        app,
        "POST",
        "/api/model-runtime/admissions",
        headers=ADMIN,
        json_body={
            "package_id": "test.embed-a",
            "task_id": "api",
            "devices": [{"device_id": "fake"}],
        },
    )

    assert status == 401
    assert invalid_status == 422
    assert any(item["loc"][-1] == "devices" for item in invalid["detail"])


def test_hardware_parsers_preserve_device_identity_and_vram():
    rocm_devices = parse_rocm_smi_json(
        json.dumps(
            {
                "card0": {
                    "Card Series": "AMD Radeon PRO W7900",
                    "Unique ID": "amd-0",
                    "VRAM Total Memory (B)": 48 * 1024 * 1024 * 1024,
                    "VRAM Total Used Memory (B)": 8 * 1024 * 1024 * 1024,
                    "GPU use (%)": "25",
                }
            }
        )
    )
    cuda_devices = parse_nvidia_smi_csv(
        "0, GPU-test, NVIDIA Test, 24576, 1024, 23552, 5, 999.1\n"
    )

    assert rocm_devices[0].device_id == "rocm:amd-0"
    assert rocm_devices[0].total_vram_mb == 49152
    assert rocm_devices[0].free_vram_mb == 40960
    assert cuda_devices[0].device_id == "cuda:GPU-test"
    assert cuda_devices[0].free_vram_mb == 23552
