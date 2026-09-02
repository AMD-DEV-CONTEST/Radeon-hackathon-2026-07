"""Persistent, device-aware resource admission and lease scheduler."""

from __future__ import annotations

import json
import hashlib
import ipaddress
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

from services.database_registry import _get_registry_conn
from services.model_packages.registry import get_installation, get_manifest
from services.model_runtime.contracts import (
    AdmissionDecision,
    AdmissionRequest,
    AdmissionStatus,
    ExternalResourceOccupancy,
    LeaseMode,
    LeaseOwnerType,
    ResourceClass,
    ResourceDrift,
    ResourceSnapshot,
    RuntimePolicyUpdate,
    SchedulingPolicy,
    utc_now,
)
from services.model_runtime.hardware import collect_resource_snapshot


ACTIVE_LEASE_STATUSES = {"active", "releasing"}
CORE_EMBEDDING_PACKAGE_ID = "aetherdb.bge-m3"


def _competition_locked_by_environment() -> bool:
    return (
        os.environ.get("AETHERDB_EXECUTION_MODE", "").strip().lower()
        == "competition"
    )


def _rocm_required_by_environment() -> bool:
    return (
        _competition_locked_by_environment()
        and os.environ.get("REQUIRE_ROCM", "").strip().lower() == "true"
    )


class ResourceSchedulerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class ResourceScheduler:
    def __init__(
        self,
        snapshot_provider: Callable[[], ResourceSnapshot] = collect_resource_snapshot,
    ):
        self._snapshot_provider = snapshot_provider
        self._lock = threading.RLock()

    @staticmethod
    def _device_supports_backend(device_backend: str, runtime_backend: str) -> bool:
        if runtime_backend in {"rocm_migraphx", "rocm_pytorch"}:
            return device_backend == "rocm_migraphx"
        return device_backend == runtime_backend

    @staticmethod
    def _local_ollama_runtime_ids() -> set[str]:
        conn = _get_registry_conn()
        try:
            rows = conn.execute(
                "SELECT runtime_id,base_url FROM ollama_runtime_observations "
                "WHERE running=1"
            ).fetchall()
        finally:
            conn.close()
        local_ids = set()
        for row in rows:
            host = (urlparse(row["base_url"]).hostname or "").lower()
            if host == "localhost":
                local_ids.add(row["runtime_id"])
                continue
            try:
                if ipaddress.ip_address(host).is_loopback:
                    local_ids.add(row["runtime_id"])
            except ValueError:
                continue
        return local_ids

    def get_policy(self) -> dict:
        conn = _get_registry_conn()
        try:
            row = conn.execute(
                "SELECT * FROM model_runtime_policy WHERE id='default'"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO model_runtime_policy "
                    "(id,scheduling_policy,competition_mode,lease_ttl_seconds,"
                    "pressure_free_vram_percent) VALUES ('default','CONSERVATIVE',0,30,10)"
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM model_runtime_policy WHERE id='default'"
                ).fetchone()
            payload = dict(row)
            payload["competition_mode"] = bool(
                payload["competition_mode"]
            ) or _competition_locked_by_environment()
            return payload
        finally:
            conn.close()

    def update_policy(self, update: RuntimePolicyUpdate) -> dict:
        conn = _get_registry_conn()
        try:
            conn.execute(
                "INSERT INTO model_runtime_policy "
                "(id,scheduling_policy,competition_mode,lease_ttl_seconds,"
                "pressure_free_vram_percent,updated_at) "
                "VALUES ('default',?,?,?,?,CURRENT_TIMESTAMP) "
                "ON CONFLICT(id) DO UPDATE SET "
                "scheduling_policy=excluded.scheduling_policy,"
                "competition_mode=excluded.competition_mode,"
                "lease_ttl_seconds=excluded.lease_ttl_seconds,"
                "pressure_free_vram_percent=excluded.pressure_free_vram_percent,"
                "updated_at=CURRENT_TIMESTAMP",
                (
                    update.scheduling_policy.value,
                    int(update.competition_mode),
                    update.lease_ttl_seconds,
                    update.pressure_free_vram_percent,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_policy()

    def capture_snapshot(self, *, persist: bool = True) -> ResourceSnapshot:
        snapshot = self._snapshot_provider()
        if persist:
            conn = _get_registry_conn()
            try:
                conn.execute(
                    "INSERT INTO model_compute_snapshots "
                    "(id,captured_at,platform,architecture,total_ram_mb,available_ram_mb,"
                    "model_disk_total_mb,model_disk_free_mb,device_count,snapshot_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        snapshot.snapshot_id,
                        snapshot.captured_at,
                        snapshot.platform,
                        snapshot.architecture,
                        snapshot.total_ram_mb,
                        snapshot.available_ram_mb,
                        snapshot.model_disk_total_mb,
                        snapshot.model_disk_free_mb,
                        len(snapshot.devices),
                        snapshot.model_dump_json(),
                    ),
                )
                conn.execute(
                    "DELETE FROM model_compute_snapshots WHERE id NOT IN "
                    "(SELECT id FROM model_compute_snapshots ORDER BY captured_at DESC LIMIT 100)"
                )
                conn.commit()
            finally:
                conn.close()
        return snapshot

    def observe_external_occupancy(
        self,
        snapshot: ResourceSnapshot | None = None,
    ) -> list[dict]:
        snapshot = snapshot or self.capture_snapshot()
        active = self.list_leases(active_only=True)
        items = []
        for device in snapshot.devices:
            owned = sum(
                max(
                    0,
                    int(
                        lease["actual_vram_mb"]
                        if lease["actual_vram_mb"] is not None
                        else lease["reserved_vram_mb"]
                    ),
                )
                for lease in active
                if lease["device_id"] == device.device_id
            )
            unattributed = max(0, int(device.used_vram_mb) - owned)
            if unattributed <= 0:
                continue
            item = ExternalResourceOccupancy(
                occupancy_id=hashlib.sha256(
                    f"device_unattributed\0{device.fingerprint}".encode("utf-8")
                ).hexdigest()[:32],
                source="device_unattributed",
                device_id=device.device_id,
                observed_vram_mb=unattributed,
                confidence="unattributed",
                observed_at=snapshot.captured_at,
            )
            items.append(item.model_dump(mode="json"))
        try:
            from services.ollama_observability import (
                list_external_resource_occupancy,
            )

            known_ids = {item["occupancy_id"] for item in items}
            items.extend(
                item
                for item in list_external_resource_occupancy()
                if item["occupancy_id"] not in known_ids
            )
        except (OSError, RuntimeError):
            pass
        return items

    def cleanup_expired_leases(self) -> int:
        now = datetime.now(timezone.utc)
        conn = _get_registry_conn()
        try:
            rows = conn.execute(
                "SELECT id,expires_at FROM model_resource_leases WHERE status='active'"
            ).fetchall()
            expired = [row["id"] for row in rows if _parse_time(row["expires_at"]) <= now]
            if expired:
                conn.executemany(
                    "UPDATE model_resource_leases SET status='expired',"
                    "released_at=?,release_reason='HEARTBEAT_TIMEOUT' WHERE id=?",
                    [(now.isoformat(), lease_id) for lease_id in expired],
                )
                conn.commit()
            return len(expired)
        finally:
            conn.close()

    def list_leases(self, *, active_only: bool = False) -> list[dict]:
        self.cleanup_expired_leases()
        conn = _get_registry_conn()
        try:
            where = " WHERE status IN ('active','releasing')" if active_only else ""
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM model_resource_leases"
                    f"{where} ORDER BY acquired_at DESC,id DESC"
                )
            ]
        finally:
            conn.close()

    def detect_resource_drift(
        self,
        *,
        snapshot: ResourceSnapshot | None = None,
        runtime_states: dict[str, str] | None = None,
        persist: bool = True,
    ) -> list[dict]:
        snapshot = snapshot or self.capture_snapshot()
        runtime_states = runtime_states or {}
        active_leases = self.list_leases(active_only=True)
        device_ids = {device.device_id for device in snapshot.devices}
        conn = _get_registry_conn()
        try:
            workers = {
                row["id"]: dict(row)
                for row in conn.execute("SELECT * FROM model_worker_instances")
            }
        finally:
            conn.close()

        issues: list[ResourceDrift] = []
        active_lease_ids = {lease["id"] for lease in active_leases}
        now = utc_now()

        def issue(code, subject_type, subject_id, *, lease=None, **details):
            owner_type = lease.get("owner_type") if lease else None
            drift_id = hashlib.sha256(
                f"{subject_type}\0{subject_id}\0{code}".encode("utf-8")
            ).hexdigest()[:32]
            issues.append(
                ResourceDrift(
                    drift_id=drift_id,
                    code=code,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    lease_id=lease.get("id") if lease else details.pop("lease_id", None),
                    device_id=lease.get("device_id") if lease else details.pop("device_id", None),
                    runtime_id=lease.get("runtime_id") if lease else details.pop("runtime_id", None),
                    owner_type=LeaseOwnerType(owner_type) if owner_type else None,
                    detected_at=now,
                    details=details,
                )
            )

        for lease in active_leases:
            resource_class = ResourceClass(lease["resource_class"])
            if (
                resource_class
                in {
                    ResourceClass.CORE_RESIDENT,
                    ResourceClass.GPU_EXCLUSIVE_HEAVY,
                    ResourceClass.GPU_EXCLUSIVE_MEDIUM,
                    ResourceClass.GPU_SHARED_LIGHT,
                }
                and not snapshot.probe_errors
                and lease["device_id"] not in device_ids
            ):
                issue(
                    "LEASE_DEVICE_MISSING",
                    "lease",
                    lease["id"],
                    lease=lease,
                )
            if lease["owner_type"] == LeaseOwnerType.AETHERDB_WORKER.value:
                worker = workers.get(lease["worker_id"])
                if worker is None or worker["state"] in {"FAILED", "STOPPED"}:
                    issue(
                        "LEASE_OWNER_MISSING",
                        "lease",
                        lease["id"],
                        lease=lease,
                        worker_state=worker["state"] if worker else "missing",
                    )
                elif worker.get("lease_id") not in {None, lease["id"]}:
                    issue(
                        "LEASE_OWNER_MISMATCH",
                        "lease",
                        lease["id"],
                        lease=lease,
                        worker_lease_id=worker.get("lease_id"),
                    )
            runtime_id = lease.get("runtime_id")
            if runtime_id and runtime_states.get(runtime_id) in {
                "unavailable",
                "stopped",
                "failed",
            }:
                issue(
                    "REMOTE_RUNTIME_UNAVAILABLE",
                    "runtime",
                    runtime_id,
                    lease=lease,
                    runtime_state=runtime_states[runtime_id],
                )

        for worker in workers.values():
            if (
                worker["state"] in {"STARTING", "READY", "BUSY", "DRAINING"}
                and worker.get("lease_id")
                and worker["lease_id"] not in active_lease_ids
            ):
                issue(
                    "WORKER_LEASE_MISSING",
                    "worker",
                    worker["id"],
                    lease_id=worker["lease_id"],
                    device_id=worker.get("device_id"),
                )

        if persist:
            self._persist_drift(issues)
        return [item.model_dump(mode="json") for item in issues]

    @staticmethod
    def _persist_drift(issues: list[ResourceDrift]) -> None:
        now = utc_now()
        active_ids = {item.drift_id for item in issues}
        conn = _get_registry_conn()
        try:
            for item in issues:
                conn.execute(
                    "INSERT INTO model_resource_drift_events "
                    "(id,drift_code,subject_type,subject_id,lease_id,device_id,"
                    "runtime_id,owner_type,status,details_json,first_detected_at,"
                    "last_detected_at,resolved_at) "
                    "VALUES (?,?,?,?,?,?,?,?,? ,?,?,?,NULL) "
                    "ON CONFLICT(id) DO UPDATE SET status='active',"
                    "lease_id=excluded.lease_id,device_id=excluded.device_id,"
                    "runtime_id=excluded.runtime_id,owner_type=excluded.owner_type,"
                    "details_json=excluded.details_json,"
                    "last_detected_at=excluded.last_detected_at,resolved_at=NULL",
                    (
                        item.drift_id,
                        item.code,
                        item.subject_type,
                        item.subject_id,
                        item.lease_id,
                        item.device_id,
                        item.runtime_id,
                        item.owner_type.value if item.owner_type else None,
                        "active",
                        json.dumps(item.details, ensure_ascii=True, sort_keys=True),
                        item.detected_at,
                        item.detected_at,
                    ),
                )
            if active_ids:
                placeholders = ",".join("?" for _ in active_ids)
                conn.execute(
                    "UPDATE model_resource_drift_events SET status='resolved',resolved_at=? "
                    f"WHERE status='active' AND id NOT IN ({placeholders})",
                    (now, *sorted(active_ids)),
                )
            else:
                conn.execute(
                    "UPDATE model_resource_drift_events SET status='resolved',resolved_at=? "
                    "WHERE status='active'",
                    (now,),
                )
            conn.commit()
        finally:
            conn.close()

    def list_drift_events(self, *, active_only: bool = False) -> list[dict]:
        conn = _get_registry_conn()
        try:
            where = " WHERE status='active'" if active_only else ""
            rows = conn.execute(
                "SELECT * FROM model_resource_drift_events"
                f"{where} ORDER BY last_detected_at DESC,id"
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["details"] = json.loads(item.pop("details_json") or "{}")
                result.append(item)
            return result
        finally:
            conn.close()

    def reconcile_owned_drift(
        self,
        *,
        snapshot: ResourceSnapshot | None = None,
        runtime_states: dict[str, str] | None = None,
    ) -> dict:
        issues = self.detect_resource_drift(
            snapshot=snapshot,
            runtime_states=runtime_states,
            persist=True,
        )
        releasable_codes = {
            "LEASE_OWNER_MISSING",
            "LEASE_OWNER_MISMATCH",
            "REMOTE_RUNTIME_UNAVAILABLE",
        }
        released = []
        for issue in issues:
            if issue["code"] not in releasable_codes or not issue.get("lease_id"):
                continue
            if issue.get("owner_type") not in {
                LeaseOwnerType.AETHERDB_WORKER.value,
                LeaseOwnerType.AETHERDB_MANAGED_RUNTIME.value,
                LeaseOwnerType.AETHERDB_TASK.value,
            }:
                continue
            lease = self.release_lease(
                issue["lease_id"],
                reason="RESOURCE_STATE_DRIFT",
            )
            released.append(lease["id"])
        self.detect_resource_drift(
            snapshot=snapshot,
            runtime_states=runtime_states,
            persist=True,
        )
        return {"released_lease_ids": released, "released_count": len(released)}

    def release_lease(self, lease_id: str, *, reason: str = "RELEASED") -> dict:
        conn = _get_registry_conn()
        try:
            cursor = conn.execute(
                "UPDATE model_resource_leases SET status='released',released_at=?,"
                "release_reason=? WHERE id=? AND status IN ('active','releasing')",
                (utc_now(), reason[:96], lease_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT * FROM model_resource_leases WHERE id=?", (lease_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(lease_id)
                return dict(row)
            row = conn.execute(
                "SELECT * FROM model_resource_leases WHERE id=?", (lease_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def heartbeat_lease(
        self,
        lease_id: str,
        *,
        actual_vram_mb: int | None = None,
        actual_peak_vram_mb: int | None = None,
    ) -> dict:
        policy = self.get_policy()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=policy["lease_ttl_seconds"])
        conn = _get_registry_conn()
        try:
            cursor = conn.execute(
                "UPDATE model_resource_leases SET heartbeat_at=?,expires_at=?,"
                "actual_vram_mb=COALESCE(?,actual_vram_mb),"
                "actual_peak_vram_mb=MAX(COALESCE(actual_peak_vram_mb,0),COALESCE(?,0)) "
                "WHERE id=? AND status='active'",
                (
                    now.isoformat(),
                    expires.isoformat(),
                    actual_vram_mb,
                    actual_peak_vram_mb,
                    lease_id,
                ),
            )
            conn.commit()
            if cursor.rowcount == 0:
                raise ResourceSchedulerError("LEASE_INACTIVE", "GPU lease is not active")
            row = conn.execute(
                "SELECT * FROM model_resource_leases WHERE id=?", (lease_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def record_coexistence_evidence(
        self,
        *,
        package_a: str,
        package_b: str,
        device_fingerprint: str,
        backend: str,
        benchmark_ref: str,
        verified: bool,
        expires_at: str | None = None,
    ) -> dict:
        if package_a == package_b:
            raise ValueError("coexistence evidence requires two distinct packages")
        left, right = sorted((package_a, package_b))
        evidence_id = uuid.uuid4().hex
        conn = _get_registry_conn()
        try:
            conn.execute(
                "INSERT INTO model_coexistence_evidence "
                "(id,package_a,package_b,device_fingerprint,backend,benchmark_ref,"
                "verified,verified_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    left,
                    right,
                    device_fingerprint,
                    backend,
                    benchmark_ref[:256],
                    int(verified),
                    utc_now() if verified else None,
                    expires_at,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM model_coexistence_evidence WHERE id=?", (evidence_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def record_runtime_evidence(
        self,
        *,
        package_id: str,
        device_fingerprint: str,
        backend: str,
        verification_status: str,
        probe_ref: str,
        benchmark_ref: str | None = None,
        evidence: dict | None = None,
        expires_at: str | None = None,
    ) -> dict:
        allowed = {
            "VERIFIED_ROCM",
            "VERIFIED_CUDA",
            "TESTED",
            "FAILED_PROBE",
            "INCOMPATIBLE",
        }
        if verification_status not in allowed:
            raise ValueError("invalid runtime verification status")
        manifest = get_manifest(package_id, sync=False)
        evidence_id = uuid.uuid4().hex
        conn = _get_registry_conn()
        try:
            conn.execute(
                "INSERT INTO model_runtime_evidence "
                "(id,package_id,package_version,manifest_digest,device_fingerprint,"
                "backend,verification_status,probe_ref,benchmark_ref,evidence_json,"
                "verified_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    package_id,
                    manifest.package_version,
                    manifest.digest(),
                    device_fingerprint,
                    backend,
                    verification_status,
                    probe_ref[:256],
                    benchmark_ref[:256] if benchmark_ref else None,
                    json.dumps(evidence or {}, ensure_ascii=True, sort_keys=True),
                    utc_now()
                    if verification_status in {"VERIFIED_ROCM", "VERIFIED_CUDA"}
                    else None,
                    expires_at,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM model_runtime_evidence WHERE id=?", (evidence_id,)
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    def list_runtime_evidence(self) -> list[dict]:
        conn = _get_registry_conn()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM model_runtime_evidence "
                    "ORDER BY created_at DESC,id DESC"
                )
            ]
        finally:
            conn.close()

    def _runtime_verified(
        self,
        *,
        manifest,
        device_fingerprint: str,
        backend: str,
    ) -> bool:
        required = {
            "rocm_migraphx": "VERIFIED_ROCM",
            "rocm_pytorch": "VERIFIED_ROCM",
            "cuda": "VERIFIED_CUDA",
        }.get(backend)
        if required is None:
            return False
        conn = _get_registry_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM model_runtime_evidence "
                "WHERE package_id=? AND package_version=? AND manifest_digest=? "
                "AND device_fingerprint=? AND backend=? AND verification_status=? "
                "AND (expires_at IS NULL OR expires_at>?) "
                "ORDER BY verified_at DESC LIMIT 1",
                (
                    manifest.package_id,
                    manifest.package_version,
                    manifest.digest(),
                    device_fingerprint,
                    backend,
                    required,
                    utc_now(),
                ),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def list_coexistence_evidence(self) -> list[dict]:
        conn = _get_registry_conn()
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM model_coexistence_evidence "
                    "ORDER BY created_at DESC,id DESC"
                )
            ]
        finally:
            conn.close()

    def _coexistence_verified(
        self,
        package_a: str,
        package_b: str,
        device_fingerprint: str,
        backend: str,
    ) -> bool:
        left, right = sorted((package_a, package_b))
        now = utc_now()
        conn = _get_registry_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM model_coexistence_evidence "
                "WHERE package_a=? AND package_b=? AND device_fingerprint=? "
                "AND backend=? AND verified=1 "
                "AND (expires_at IS NULL OR expires_at>?) "
                "ORDER BY verified_at DESC LIMIT 1",
                (left, right, device_fingerprint, backend, now),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    @staticmethod
    def _resource_class(request: AdmissionRequest, manifest) -> ResourceClass:
        if request.resource_class != "AUTO":
            return ResourceClass(request.resource_class)
        if manifest.core_required:
            return ResourceClass.CORE_RESIDENT
        if manifest.resource_profile.recommended_vram_mb in (None, 0):
            return ResourceClass.CPU_PARALLEL
        if (
            manifest.runtime_policy is not None
            and manifest.runtime_policy.default_lease_mode == "EXCLUSIVE"
        ) or manifest.residency_policy_default == "exclusive":
            return ResourceClass.GPU_EXCLUSIVE_HEAVY
        return ResourceClass.GPU_SHARED_LIGHT

    @staticmethod
    def _shared_gpu_eligible(manifest) -> bool:
        if manifest.runtime_policy is not None:
            return bool(manifest.runtime_policy.shared_gpu_eligible)
        return manifest.residency_policy_default == "shared"

    @staticmethod
    def _default_lease_mode(manifest) -> LeaseMode:
        if manifest.runtime_policy is not None:
            return LeaseMode(manifest.runtime_policy.default_lease_mode)
        return (
            LeaseMode.SHARED
            if manifest.residency_policy_default == "shared"
            else LeaseMode.EXCLUSIVE
        )

    @staticmethod
    def _resource_estimate(manifest, resource_class: ResourceClass) -> tuple[int, int, int, int]:
        if resource_class in {
            ResourceClass.CPU_PARALLEL,
            ResourceClass.IO_BACKGROUND,
            ResourceClass.REMOTE_RUNTIME,
        }:
            return 0, 0, 0, 0
        peak = (
            manifest.resource_profile.recommended_vram_mb
            or manifest.resource_profile.minimum_vram_mb
            or 0
        )
        context = max(256, peak // 10) if peak else 0
        margin = max(512, peak * 15 // 100) if peak else 0
        return peak + context + margin, peak, context, margin

    def _unloaded_core_gpu_budget(
        self,
        *,
        snapshot: ResourceSnapshot,
        active: list[dict],
        request: AdmissionRequest,
        policy: dict,
    ) -> dict[str, int]:
        if (
            request.package_id == CORE_EMBEDDING_PACKAGE_ID
            or request.resource_class == ResourceClass.CORE_RESIDENT
            or os.environ.get("AETHERDB_EMBEDDING_ACCELERATOR", "auto")
            .strip()
            .lower()
            == "cpu"
            or any(
                item["resource_class"] == ResourceClass.CORE_RESIDENT.value
                for item in active
            )
        ):
            return {}
        try:
            manifest = get_manifest(CORE_EMBEDDING_PACKAGE_ID, sync=False)
            installation = get_installation(CORE_EMBEDDING_PACKAGE_ID)
        except (KeyError, RuntimeError):
            return {}
        if (
            not manifest.core_required
            or installation is None
            or installation["status"] != "installed"
        ):
            return {}

        accelerator = os.environ.get(
            "AETHERDB_EMBEDDING_ACCELERATOR", "auto"
        ).strip().lower()
        backend_order = {
            "auto": ("rocm_migraphx", "rocm_pytorch", "cuda"),
            "rocm": ("rocm_migraphx",),
            "migraphx": ("rocm_migraphx",),
            "cuda": ("cuda",),
        }.get(accelerator, ())
        supported = set(manifest.supported_backends)
        reserved, _peak, _context, _margin = self._resource_estimate(
            manifest,
            ResourceClass.CORE_RESIDENT,
        )
        candidates = []
        for device in snapshot.devices:
            if not any(
                backend in supported
                and self._device_supports_backend(device.backend, backend)
                for backend in backend_order
            ):
                continue
            pressure_floor = (
                device.total_vram_mb
                * int(policy["pressure_free_vram_percent"])
                // 100
            )
            if device.free_vram_mb - reserved >= pressure_floor:
                candidates.append(device)
        if not candidates:
            return {}
        chosen = max(
            candidates,
            key=lambda item: (item.free_vram_mb, -item.visible_index),
        )
        return {chosen.device_id: reserved}

    @staticmethod
    def _decision(
        request: AdmissionRequest,
        snapshot: ResourceSnapshot,
        policy: dict,
        resource_class: ResourceClass,
        status: AdmissionStatus,
        code: str,
        message: str,
        **fields,
    ) -> AdmissionDecision:
        return AdmissionDecision(
            status=status,
            reason_code=code,
            message=message,
            package_id=request.package_id,
            task_id=request.task_id,
            resource_class=resource_class,
            requested_backend=request.requested_backend,
            snapshot_id=snapshot.snapshot_id,
            policy=SchedulingPolicy(policy["scheduling_policy"]),
            competition_mode=(
                bool(policy["competition_mode"]) or request.competition_mode is True
            ),
            **fields,
        )

    def evaluate(
        self,
        request: AdmissionRequest,
        *,
        snapshot: ResourceSnapshot | None = None,
        acquire: bool = False,
        worker_id: str | None = None,
        allow_unverified_probe: bool = False,
    ) -> AdmissionDecision:
        with self._lock:
            self.cleanup_expired_leases()
            policy = self.get_policy()
            snapshot = snapshot or self.capture_snapshot()
            if request.resource_class == ResourceClass.REMOTE_RUNTIME:
                active = self.list_leases(active_only=True)
                same_runtime = [
                    lease
                    for lease in active
                    if lease.get("runtime_id") == request.runtime_id
                ]
                if same_runtime:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        ResourceClass.REMOTE_RUNTIME,
                        AdmissionStatus.QUEUED,
                        "REMOTE_RUNTIME_BUSY",
                        "The selected runtime is already serving an AetherDB task",
                        effective_backend="remote",
                        blocking_lease_ids=tuple(
                            lease["id"] for lease in same_runtime
                        ),
                        runtime_id=request.runtime_id,
                        model_id=request.model_id,
                    )
                local_runtime = (
                    request.runtime_id in self._local_ollama_runtime_ids()
                )
                if local_runtime:
                    native_blockers = [
                        lease
                        for lease in active
                        if lease["resource_class"]
                        in {
                            ResourceClass.GPU_EXCLUSIVE_HEAVY.value,
                            ResourceClass.GPU_EXCLUSIVE_MEDIUM.value,
                            ResourceClass.GPU_SHARED_LIGHT.value,
                        }
                    ]
                    if native_blockers:
                        return self._decision(
                            request,
                            snapshot,
                            policy,
                            ResourceClass.REMOTE_RUNTIME,
                            AdmissionStatus.QUEUED,
                            "LOCAL_RUNTIME_GPU_BUSY",
                            "A native GPU task is active; local Ollama admission is queued",
                            effective_backend="remote",
                            blocking_lease_ids=tuple(
                                lease["id"] for lease in native_blockers
                            ),
                            runtime_id=request.runtime_id,
                            model_id=request.model_id,
                        )
                    try:
                        from services.ollama_observability import (
                            list_external_resource_occupancy,
                        )

                        foreign_models = [
                            item
                            for item in list_external_resource_occupancy()
                            if item.get("runtime_id") == request.runtime_id
                            and item.get("model_id") != request.model_id
                        ]
                    except (OSError, RuntimeError):
                        foreign_models = []
                    if foreign_models:
                        return self._decision(
                            request,
                            snapshot,
                            policy,
                            ResourceClass.REMOTE_RUNTIME,
                            AdmissionStatus.QUEUED,
                            "EXTERNAL_RUNTIME_OCCUPIED",
                            "Another externally owned Ollama model is loaded; "
                            "AetherDB will not unload it",
                            effective_backend="remote",
                            runtime_id=request.runtime_id,
                            model_id=request.model_id,
                        )
                lease_id = None
                if acquire:
                    lease_id = self._insert_lease(
                        request=request,
                        worker_id=worker_id or request.runtime_id or f"task:{request.task_id}",
                        device_id=f"remote:{request.runtime_id}",
                        device_fingerprint=f"remote:{request.runtime_id}",
                        backend="remote",
                        mode=LeaseMode.SHARED,
                        resource_class=ResourceClass.REMOTE_RUNTIME,
                        reserved=0,
                        peak=0,
                        context=0,
                        margin=0,
                        estimated_ram_mb=request.estimated_ram_mb,
                        owner_type=LeaseOwnerType.AETHERDB_TASK,
                        runtime_id=request.runtime_id,
                        model_id=request.model_id,
                        ttl_seconds=policy["lease_ttl_seconds"],
                        snapshot_id=snapshot.snapshot_id,
                    )
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    ResourceClass.REMOTE_RUNTIME,
                    AdmissionStatus.ADMITTED,
                    "REMOTE_RUNTIME_ADMITTED",
                    "Remote runtime task admitted with a logical AetherDB lease",
                    effective_backend="remote",
                    lease_mode=LeaseMode.SHARED,
                    device_id=f"remote:{request.runtime_id}",
                    lease_id=lease_id,
                    runtime_id=request.runtime_id,
                    model_id=request.model_id,
                    estimated_ram_mb=request.estimated_ram_mb,
                )
            try:
                manifest = get_manifest(request.package_id, sync=False)
            except KeyError:
                resource_class = (
                    ResourceClass.CPU_PARALLEL
                    if request.resource_class == "AUTO"
                    else ResourceClass(request.resource_class)
                )
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.REQUIRES_INSTALL,
                    "PACKAGE_UNKNOWN",
                    "Model package is not present in the trusted catalog",
                )
            resource_class = self._resource_class(request, manifest)
            installation = get_installation(request.package_id)
            if installation is None or installation["status"] not in {"installed", "disabled"}:
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.REQUIRES_INSTALL,
                    "PACKAGE_NOT_INSTALLED",
                    "Model package must be installed and verified before admission",
                )
            if installation["status"] == "disabled":
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.BLOCKED_BY_POLICY,
                    "PACKAGE_DISABLED",
                    "Disabled model packages cannot receive runtime resources",
                )

            competition = (
                bool(policy["competition_mode"]) or request.competition_mode is True
            )
            require_rocm = competition and _rocm_required_by_environment()
            minimum_ram = manifest.resource_profile.minimum_ram_mb or 0
            if (
                snapshot.total_ram_mb > 0
                and snapshot.available_ram_mb < minimum_ram
            ):
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.INSUFFICIENT_RESOURCES,
                    "INSUFFICIENT_RAM",
                    "Available system RAM is below the package minimum",
                )
            if resource_class in {ResourceClass.CPU_PARALLEL, ResourceClass.IO_BACKGROUND}:
                if require_rocm:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.BLOCKED_BY_POLICY,
                        "COMPETITION_ROCM_REQUIRED",
                        "This competition runtime requires a verified ROCm model path",
                    )
                if request.requested_backend not in {"auto", "cpu"}:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.INSUFFICIENT_RESOURCES,
                        "REQUESTED_BACKEND_UNAVAILABLE",
                        "The requested GPU backend is unavailable for this resource class",
                    )
                if competition and "cpu" not in manifest.supported_backends:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.BLOCKED_BY_POLICY,
                        "COMPETITION_CPU_BLOCKED",
                        "Competition mode does not allow an undeclared CPU execution path",
                    )
                lease_id = None
                if acquire:
                    lease_id = self._insert_lease(
                        request=request,
                        worker_id=worker_id or f"task:{request.task_id}",
                        device_id="logical:cpu",
                        device_fingerprint="logical:cpu",
                        backend="cpu",
                        mode=LeaseMode.SHARED,
                        resource_class=resource_class,
                        reserved=0,
                        peak=0,
                        context=0,
                        margin=0,
                        estimated_ram_mb=(
                            request.estimated_ram_mb
                            or manifest.resource_profile.recommended_ram_mb
                            or manifest.resource_profile.minimum_ram_mb
                            or 0
                        ),
                        owner_type=(
                            LeaseOwnerType.AETHERDB_WORKER
                            if worker_id
                            else LeaseOwnerType.AETHERDB_TASK
                        ),
                        runtime_id=request.runtime_id,
                        model_id=request.model_id,
                        ttl_seconds=policy["lease_ttl_seconds"],
                        snapshot_id=snapshot.snapshot_id,
                    )
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.ADMITTED,
                    "CPU_ADMITTED",
                    "CPU or I/O work admitted with a logical resource lease",
                    effective_backend="cpu",
                    lease_mode=LeaseMode.SHARED,
                    device_id="logical:cpu",
                    lease_id=lease_id,
                    runtime_id=request.runtime_id,
                    model_id=request.model_id,
                    estimated_ram_mb=(
                        request.estimated_ram_mb
                        or manifest.resource_profile.recommended_ram_mb
                        or manifest.resource_profile.minimum_ram_mb
                        or 0
                    ),
                )

            supported = set(manifest.supported_backends)
            requested = request.requested_backend
            backend_order = (
                [requested]
                if requested != "auto"
                else ["rocm_migraphx", "rocm_pytorch", "cuda"]
                + ([] if competition else ["cpu"])
            )
            selected_backend = next(
                (
                    backend
                    for backend in backend_order
                    if backend in supported
                    and (
                        backend == "cpu"
                        or any(
                            self._device_supports_backend(device.backend, backend)
                            for device in snapshot.devices
                        )
                    )
                ),
                None,
            )
            if selected_backend is None:
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.BLOCKED_BY_POLICY
                    if competition
                    else AdmissionStatus.INSUFFICIENT_RESOURCES,
                    "REQUESTED_BACKEND_UNAVAILABLE"
                    if requested != "auto"
                    else "NO_COMPATIBLE_DEVICE",
                    "No compatible server-detected execution backend is available",
                )
            if require_rocm and selected_backend not in {
                "rocm_migraphx",
                "rocm_pytorch",
            }:
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.BLOCKED_BY_POLICY,
                    "COMPETITION_ROCM_REQUIRED",
                    "This competition runtime requires a verified ROCm model path",
                    effective_backend=selected_backend,
                )
            if selected_backend == "cpu":
                if competition and not allow_unverified_probe:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.BLOCKED_BY_POLICY,
                        "COMPETITION_CPU_FALLBACK_BLOCKED",
                        "Competition mode forbids silent CPU fallback",
                    )
                lease_id = None
                if acquire and request.requested_backend in {"auto", "cpu"}:
                    lease_id = self._insert_lease(
                        request=request,
                        worker_id=worker_id or f"task:{request.task_id}",
                        device_id="logical:cpu",
                        device_fingerprint="logical:cpu",
                        backend="cpu",
                        mode=LeaseMode.SHARED,
                        resource_class=ResourceClass.CPU_PARALLEL,
                        reserved=0,
                        peak=0,
                        context=0,
                        margin=0,
                        estimated_ram_mb=(
                            request.estimated_ram_mb
                            or manifest.resource_profile.recommended_ram_mb
                            or manifest.resource_profile.minimum_ram_mb
                            or 0
                        ),
                        owner_type=(
                            LeaseOwnerType.AETHERDB_WORKER
                            if worker_id
                            else LeaseOwnerType.AETHERDB_TASK
                        ),
                        runtime_id=request.runtime_id,
                        model_id=request.model_id,
                        ttl_seconds=policy["lease_ttl_seconds"],
                        snapshot_id=snapshot.snapshot_id,
                    )
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.ADMITTED
                    if request.requested_backend in {"auto", "cpu"}
                    else AdmissionStatus.REQUIRES_CPU_OFFLOAD,
                    "CPU_ADMITTED"
                    if request.requested_backend in {"auto", "cpu"}
                    else "GPU_UNAVAILABLE_CPU_OPTION",
                    "CPU execution admitted as a declared local package backend"
                    if request.requested_backend in {"auto", "cpu"}
                    else "GPU is unavailable; CPU execution requires an explicit caller decision",
                    effective_backend="cpu",
                    lease_mode=LeaseMode.SHARED,
                    device_id="logical:cpu",
                    lease_id=lease_id,
                    runtime_id=request.runtime_id,
                    model_id=request.model_id,
                    estimated_ram_mb=(
                        request.estimated_ram_mb
                        or manifest.resource_profile.recommended_ram_mb
                        or manifest.resource_profile.minimum_ram_mb
                        or 0
                    ),
                )

            if resource_class != ResourceClass.CORE_RESIDENT:
                local_runtime_ids = self._local_ollama_runtime_ids()
                active_runtime_leases = [
                    lease
                    for lease in self.list_leases(active_only=True)
                    if lease.get("runtime_id") in local_runtime_ids
                    and lease["resource_class"]
                    == ResourceClass.REMOTE_RUNTIME.value
                ]
                if active_runtime_leases:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.QUEUED,
                        "LOCAL_OLLAMA_TASK_ACTIVE",
                        "A local Ollama task holds the AetherDB runtime lease",
                        effective_backend=selected_backend,
                        blocking_lease_ids=tuple(
                            lease["id"] for lease in active_runtime_leases
                        ),
                    )
                try:
                    from services.ollama_observability import (
                        list_external_resource_occupancy,
                    )

                    external_runtime_occupancy = (
                        list_external_resource_occupancy()
                    )
                except (OSError, RuntimeError):
                    external_runtime_occupancy = []
                if external_runtime_occupancy:
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.QUEUED,
                        "EXTERNAL_RUNTIME_OCCUPIED",
                        "External Ollama work is using unowned compute resources; "
                        "AetherDB will not interrupt it",
                        effective_backend=selected_backend,
                    )

            reserved, peak, context, margin = self._resource_estimate(manifest, resource_class)
            active = self.list_leases(active_only=True)
            core_budget = self._unloaded_core_gpu_budget(
                snapshot=snapshot,
                active=active,
                request=request,
                policy=policy,
            )
            mode = (
                (
                    self._default_lease_mode(manifest)
                    if SchedulingPolicy(policy["scheduling_policy"])
                    != SchedulingPolicy.CONSERVATIVE
                    else LeaseMode.EXCLUSIVE
                )
                if request.requested_lease_mode == "AUTO"
                else LeaseMode(request.requested_lease_mode)
            )
            if resource_class in {
                ResourceClass.GPU_EXCLUSIVE_HEAVY,
                ResourceClass.GPU_EXCLUSIVE_MEDIUM,
            }:
                mode = LeaseMode.EXCLUSIVE
            elif resource_class == ResourceClass.CORE_RESIDENT:
                mode = LeaseMode.SHARED
            if mode == LeaseMode.SHARED and not self._shared_gpu_eligible(manifest):
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.BLOCKED_BY_POLICY,
                    "PACKAGE_NOT_SHAREABLE",
                    "The model package does not declare shared GPU residency",
                )

            candidates = [
                device
                for device in snapshot.devices
                if self._device_supports_backend(device.backend, selected_backend)
                and device.total_vram_mb > 0
                and device.free_vram_mb >= reserved
            ]
            candidates.sort(key=lambda item: (item.free_vram_mb, -item.visible_index), reverse=True)
            if not candidates:
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.INSUFFICIENT_RESOURCES,
                    "INSUFFICIENT_VRAM",
                    "No compatible device has enough measured free VRAM and safety margin",
                    effective_backend=selected_backend,
                    lease_mode=mode,
                    reserved_vram_mb=reserved,
                    estimated_peak_vram_mb=peak,
                    runtime_context_overhead_mb=context,
                    safety_margin_mb=margin,
                )

            chosen = None
            blockers: list[str] = []
            core_budget_blocked = False
            for device in candidates:
                device_leases = [item for item in active if item["device_id"] == device.device_id]
                committed_unobserved = sum(
                    max(0, int(item["reserved_vram_mb"]) - int(item["actual_vram_mb"] or 0))
                    for item in device_leases
                )
                pressure_floor = (
                    device.total_vram_mb * int(policy["pressure_free_vram_percent"]) // 100
                )
                protected_core_vram = core_budget.get(device.device_id, 0)
                if (
                    device.free_vram_mb
                    - committed_unobserved
                    - reserved
                    - protected_core_vram
                    < pressure_floor
                ):
                    core_budget_blocked = core_budget_blocked or bool(
                        protected_core_vram
                    )
                    blockers.extend(item["id"] for item in device_leases)
                    continue
                if competition and not allow_unverified_probe and not self._runtime_verified(
                    manifest=manifest,
                    device_fingerprint=device.fingerprint,
                    backend=selected_backend,
                ):
                    continue
                if not device_leases:
                    chosen = device
                    break
                blockers.extend(item["id"] for item in device_leases)
                if SchedulingPolicy(policy["scheduling_policy"]) == SchedulingPolicy.CONSERVATIVE:
                    continue
                if mode == LeaseMode.EXCLUSIVE or any(
                    item["lease_mode"] == LeaseMode.EXCLUSIVE.value for item in device_leases
                ):
                    continue
                if all(
                    self._coexistence_verified(
                        request.package_id,
                        item["model_package_id"],
                        device.fingerprint,
                        selected_backend,
                    )
                    for item in device_leases
                ):
                    chosen = device
                    break

            if chosen is None:
                compatible_devices = [
                    item
                    for item in candidates
                    if self._device_supports_backend(item.backend, selected_backend)
                ]
                if competition and not allow_unverified_probe and compatible_devices and not any(
                    self._runtime_verified(
                        manifest=manifest,
                        device_fingerprint=item.fingerprint,
                        backend=selected_backend,
                    )
                    for item in compatible_devices
                ):
                    return self._decision(
                        request,
                        snapshot,
                        policy,
                        resource_class,
                        AdmissionStatus.BLOCKED_BY_POLICY,
                        "MODEL_RUNTIME_UNVERIFIED",
                        "Competition mode requires exact model, device and backend runtime evidence",
                        effective_backend=selected_backend,
                        lease_mode=mode,
                        reserved_vram_mb=reserved,
                        estimated_peak_vram_mb=peak,
                        runtime_context_overhead_mb=context,
                        safety_margin_mb=margin,
                    )
                blocking_rows = [
                    item for item in active if item["id"] in set(blockers)
                ]
                can_request_eviction = (
                    SchedulingPolicy(policy["scheduling_policy"])
                    != SchedulingPolicy.CONSERVATIVE
                    and bool(blocking_rows)
                    and request.priority > max(int(item["priority"]) for item in blocking_rows)
                    and all(
                        item["resource_class"] != ResourceClass.CORE_RESIDENT.value
                        and get_manifest(item["model_package_id"], sync=False)
                        .residency_policy_default != "always"
                        for item in blocking_rows
                    )
                )
                return self._decision(
                    request,
                    snapshot,
                    policy,
                    resource_class,
                    AdmissionStatus.REQUIRES_EVICTION
                    if can_request_eviction
                    else AdmissionStatus.QUEUED,
                    (
                        "LOWER_PRIORITY_RESIDENCY_EVICTION_REQUIRED"
                        if can_request_eviction
                        else "CORE_SERVICE_BUDGET_PROTECTED"
                        if core_budget_blocked
                        else "DEVICE_BUSY_OR_COEXISTENCE_UNVERIFIED"
                    ),
                    "Lower-priority evictable model residency must be drained first"
                    if can_request_eviction
                    else "GPU budget is reserved for the core local vector service"
                    if core_budget_blocked
                    else "Compatible devices are busy or model coexistence is not verified",
                    effective_backend=selected_backend,
                    lease_mode=mode,
                    reserved_vram_mb=reserved,
                    estimated_peak_vram_mb=peak,
                    runtime_context_overhead_mb=context,
                    safety_margin_mb=margin,
                    blocking_lease_ids=tuple(sorted(set(blockers))),
                )

            lease_id = None
            if acquire:
                if not worker_id:
                    raise ValueError("worker_id is required when acquiring a lease")
                lease_id = self._insert_lease(
                    request=request,
                    worker_id=worker_id,
                    device_id=chosen.device_id,
                    device_fingerprint=chosen.fingerprint,
                    backend=selected_backend,
                    mode=mode,
                    resource_class=resource_class,
                    reserved=reserved,
                    peak=peak,
                    context=context,
                    margin=margin,
                    estimated_ram_mb=(
                        request.estimated_ram_mb
                        or manifest.resource_profile.recommended_ram_mb
                        or manifest.resource_profile.minimum_ram_mb
                        or 0
                    ),
                    owner_type=LeaseOwnerType.AETHERDB_WORKER,
                    runtime_id=request.runtime_id,
                    model_id=request.model_id or manifest.model_profile_id,
                    ttl_seconds=policy["lease_ttl_seconds"],
                    snapshot_id=snapshot.snapshot_id,
                )
            return self._decision(
                request,
                snapshot,
                policy,
                resource_class,
                AdmissionStatus.ADMITTED,
                "GPU_LEASE_ADMITTED",
                "GPU resource admission succeeded",
                effective_backend=selected_backend,
                lease_mode=mode,
                device_id=chosen.device_id,
                reserved_vram_mb=reserved,
                estimated_peak_vram_mb=peak,
                runtime_context_overhead_mb=context,
                safety_margin_mb=margin,
                lease_id=lease_id,
            )

    def _insert_lease(
        self,
        *,
        request: AdmissionRequest,
        worker_id: str,
        device_id: str,
        device_fingerprint: str,
        backend: str,
        mode: LeaseMode,
        resource_class: ResourceClass,
        reserved: int,
        peak: int,
        context: int,
        margin: int,
        estimated_ram_mb: int,
        owner_type: LeaseOwnerType,
        runtime_id: str | None,
        model_id: str | None,
        ttl_seconds: int,
        snapshot_id: str,
    ) -> str:
        now = datetime.now(timezone.utc)
        lease_id = uuid.uuid4().hex
        conn = _get_registry_conn()
        try:
            conn.execute(
                "INSERT INTO model_resource_leases "
                "(id,device_id,device_fingerprint,worker_id,model_package_id,task_id,"
                "lease_mode,status,effective_backend,reserved_vram_mb,"
                "estimated_peak_vram_mb,runtime_context_overhead_mb,safety_margin_mb,"
                "priority,snapshot_id,acquired_at,heartbeat_at,expires_at,runtime_id,"
                "model_id,resource_class,estimated_ram_mb,owner_type) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lease_id,
                    device_id,
                    device_fingerprint,
                    worker_id,
                    request.package_id or "runtime.external",
                    request.task_id,
                    mode.value,
                    "active",
                    backend,
                    reserved,
                    peak,
                    context,
                    margin,
                    request.priority,
                    snapshot_id,
                    now.isoformat(),
                    now.isoformat(),
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                    runtime_id,
                    model_id,
                    resource_class.value,
                    estimated_ram_mb,
                    owner_type.value,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return lease_id


_scheduler: ResourceScheduler | None = None
_scheduler_lock = threading.Lock()


def get_resource_scheduler() -> ResourceScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = ResourceScheduler()
        return _scheduler


def reset_resource_scheduler_for_tests() -> None:
    global _scheduler
    with _scheduler_lock:
        _scheduler = None
