from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import GpuLeaseMirrorRecord


_GPU_CLAIM_LOCK_NAMESPACE = 0x43524750


class GpuWorkerError(RuntimeError):
    pass


def _dependencies_released(session: Session, payload: dict) -> bool:
    for value in payload.get("dependency_request_ids") or ():
        try:
            dependency_id = UUID(str(value))
        except (TypeError, ValueError):
            raise GpuWorkerError("GPU lease dependency id is invalid") from None
        dependency = session.scalar(
            select(GpuLeaseMirrorRecord).where(
                GpuLeaseMirrorRecord.request_id == dependency_id
            )
        )
        if dependency is None or dependency.status != "released":
            return False
    return True


def _matches_worker_observation(
    payload: dict,
    *,
    gpu_index: int,
    free_vram_mib: int,
    device_type: str,
    model_digests: frozenset[str],
    workflow_digests: frozenset[str],
    custom_node_environment_digest: str | None,
    implementation_manifest_digests: frozenset[str],
    worker_id: str | None,
) -> bool:
    requirement = payload.get("resource_requirement")
    if requirement is None:
        return int(payload.get("estimated_vram_mib") or 0) <= free_vram_mib
    if not isinstance(requirement, dict):
        raise GpuWorkerError("GPU resource requirement is invalid")
    try:
        minimum_vram = int(requirement["minimum_vram_mb"])
        required_device = str(requirement["device_type"])
        model_digest = str(requirement["model_digest"])
        workflow_digest = str(requirement["workflow_digest"])
        environment_digest = str(
            requirement["custom_node_environment_digest"]
        )
    except (KeyError, TypeError, ValueError):
        raise GpuWorkerError("GPU resource requirement is incomplete") from None
    if minimum_vram <= 0:
        raise GpuWorkerError("GPU minimum VRAM requirement is invalid")
    pin = requirement.get("gpu_pin")
    if pin is not None and str(pin) not in {
        str(gpu_index),
        f"gpu-{gpu_index}",
        f"cuda:{gpu_index}",
        worker_id,
    }:
        return False
    implementation_digest = payload.get("implementation_manifest_digest")
    if not implementation_digest:
        raise GpuWorkerError(
            "GPU implementation manifest evidence is incomplete"
        )
    return (
        required_device == device_type
        and free_vram_mib >= minimum_vram
        and model_digest in model_digests
        and workflow_digest in workflow_digests
        and environment_digest == custom_node_environment_digest
        and str(implementation_digest) in implementation_manifest_digests
    )


def claim_gpu_lease(
    session: Session,
    *,
    gpu_index: int,
    total_vram_mib: int,
    free_vram_mib: int | None = None,
    device_type: str = "cuda",
    model_digests: tuple[str, ...] = (),
    workflow_digests: tuple[str, ...] = (),
    custom_node_environment_digest: str | None = None,
    implementation_manifest_digests: tuple[str, ...] = (),
    worker_id: str | None = None,
    now: datetime | None = None,
) -> GpuLeaseMirrorRecord | None:
    moment = now or datetime.now(timezone.utc)
    available_vram_mib = (
        total_vram_mib if free_vram_mib is None else free_vram_mib
    )
    if (
        gpu_index < 0
        or total_vram_mib <= 0
        or available_vram_mib < 0
        or available_vram_mib > total_vram_mib
        or not device_type
    ):
        raise GpuWorkerError("GPU worker observation is invalid")
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # Serialize the check-and-activate transition per physical device.
        # Row SKIP LOCKED alone cannot protect two different queued rows.
        session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :gpu_index)"),
            {
                "namespace": _GPU_CLAIM_LOCK_NAMESPACE,
                "gpu_index": gpu_index,
            },
        )
    active = session.scalar(
        select(GpuLeaseMirrorRecord).where(
            GpuLeaseMirrorRecord.status == "active",
            GpuLeaseMirrorRecord.gpu_index == gpu_index,
        )
    )
    if active is not None:
        return None
    statement = (
        select(GpuLeaseMirrorRecord)
        .where(
            GpuLeaseMirrorRecord.status == "queued",
        )
        .order_by(
            GpuLeaseMirrorRecord.effective_priority.desc(),
            GpuLeaseMirrorRecord.requested_at.asc(),
            GpuLeaseMirrorRecord.id.asc(),
        )
    )
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    for lease in session.scalars(statement).all():
        pinned = lease.payload.get("pinned_gpu_index")
        if pinned is not None and int(pinned) != gpu_index:
            continue
        if not _matches_worker_observation(
            {
                "estimated_vram_mib": lease.estimated_vram_mib,
                **lease.payload,
            },
            gpu_index=gpu_index,
            free_vram_mib=available_vram_mib,
            device_type=device_type,
            model_digests=frozenset(model_digests),
            workflow_digests=frozenset(workflow_digests),
            custom_node_environment_digest=(
                custom_node_environment_digest
            ),
            implementation_manifest_digests=frozenset(
                implementation_manifest_digests
            ),
            worker_id=worker_id,
        ):
            continue
        if not _dependencies_released(session, lease.payload):
            continue
        lease.status = "active"
        lease.gpu_index = gpu_index
        lease.expires_at = moment + timedelta(
            seconds=int(lease.payload.get("max_runtime_seconds") or 3600)
        )
        lease.payload = {
            **lease.payload,
            "worker_started_at": moment.isoformat(),
            "worker_gpu_index": gpu_index,
            "worker_device_type": device_type,
            "worker_free_vram_mib": available_vram_mib,
            "worker_model_digests": sorted(model_digests),
            "worker_workflow_digests": sorted(workflow_digests),
            "worker_custom_node_environment_digest": (
                custom_node_environment_digest
            ),
            "worker_implementation_manifest_digests": sorted(
                implementation_manifest_digests
            ),
        }
        session.flush()
        return lease
    return None


class LocalGpuWorker:
    """Retired compatibility name that can only delegate to the atomic DAG.

    The former implementation claimed a mirror lease and executed the legacy
    Wan provider against Factory V3 files directly.  That path
    bypassed the operation registry, durable Attempt identity and cutover
    fence.  Keeping the import name avoids surprising old diagnostics, but no
    legacy executor can be constructed: callers must inject the unified
    registry-backed worker explicitly.
    """

    def __init__(
        self,
        *,
        atomic_worker: object | None = None,
        **legacy_configuration,
    ) -> None:
        del legacy_configuration
        run_once = getattr(atomic_worker, "run_once", None)
        if not callable(run_once):
            raise GpuWorkerError(
                "LocalGpuWorker is retired; use the unified durable DAG worker"
            )
        self._atomic_worker = atomic_worker

    def run_once(self) -> bool:
        tick = self._atomic_worker.run_once()
        outcome = getattr(tick, "outcome", None)
        return getattr(outcome, "value", outcome) != "idle"


def main() -> None:
    raise SystemExit(
        "Local GPU worker entrypoint is retired; "
        "use creative-hub-dag-worker with the video-local profile"
    )


if __name__ == "__main__":
    main()
