"""Admin API for server-owned resource snapshots and model admission."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.auth import require_admin
from services.model_runtime.contracts import (
    AdmissionRequest,
    RuntimePolicyUpdate,
    WorkerLoadRequest,
    WorkerProbeRequest,
    WorkerStartRequest,
)
from services.model_runtime.manager import WorkerManagerError, get_worker_manager
from services.model_runtime.scheduler import (
    ResourceSchedulerError,
    get_resource_scheduler,
)


router = APIRouter(
    prefix="/api/model-runtime",
    tags=["model-runtime"],
    dependencies=[Depends(require_admin)],
)


@router.get("/resources")
def get_resources():
    scheduler = get_resource_scheduler()
    snapshot = scheduler.capture_snapshot()
    return {
        "snapshot": snapshot.model_dump(mode="json"),
        "policy": scheduler.get_policy(),
        "active_leases": scheduler.list_leases(active_only=True),
        "external_occupancy": scheduler.observe_external_occupancy(snapshot),
        "resource_drift": scheduler.detect_resource_drift(snapshot=snapshot),
    }


@router.get("/policy")
def get_policy():
    return get_resource_scheduler().get_policy()


@router.put("/policy")
def update_policy(payload: RuntimePolicyUpdate):
    return get_resource_scheduler().update_policy(payload)


@router.post("/admissions")
def evaluate_admission(payload: AdmissionRequest):
    try:
        decision = get_resource_scheduler().evaluate(payload, acquire=False)
    except ResourceSchedulerError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.safe_message},
        ) from exc
    return decision.model_dump(mode="json")


@router.get("/leases")
def list_leases(active_only: bool = Query(default=False)):
    return {"items": get_resource_scheduler().list_leases(active_only=active_only)}


@router.get("/drift")
def list_resource_drift(active_only: bool = Query(default=True)):
    scheduler = get_resource_scheduler()
    scheduler.detect_resource_drift()
    return {"items": scheduler.list_drift_events(active_only=active_only)}


@router.post("/drift/reconcile")
def reconcile_resource_drift():
    return get_resource_scheduler().reconcile_owned_drift()


@router.get("/coexistence-evidence")
def list_coexistence_evidence():
    return {"items": get_resource_scheduler().list_coexistence_evidence()}


@router.get("/runtime-evidence")
def list_runtime_evidence():
    return {"items": get_resource_scheduler().list_runtime_evidence()}


def _worker_error(exc: WorkerManagerError):
    raise HTTPException(
        status_code=409,
        detail={
            "code": exc.code,
            "message": exc.safe_message,
            **exc.details,
        },
    ) from exc


@router.get("/workers")
def list_workers():
    return {"items": get_worker_manager().list_workers()}


@router.post("/workers", status_code=201)
def start_worker(payload: WorkerStartRequest):
    try:
        worker = get_worker_manager().start_worker(
            payload.package_id,
            replica_id=payload.replica_id,
            residency_mode=payload.residency_mode,
        )
    except WorkerManagerError as exc:
        _worker_error(exc)
    return {"worker": worker}


@router.get("/workers/{worker_id}")
def get_worker(worker_id: str):
    worker = get_worker_manager().get_worker(worker_id)
    if worker is None:
        raise HTTPException(404, "Model Worker not found")
    return {"worker": worker}


@router.post("/workers/{worker_id}/load")
def load_worker(worker_id: str, payload: WorkerLoadRequest):
    try:
        return get_worker_manager().load_worker(worker_id, payload)
    except KeyError:
        raise HTTPException(404, "Model Worker not found")
    except WorkerManagerError as exc:
        _worker_error(exc)


@router.post("/workers/{worker_id}/unload")
def unload_worker(worker_id: str):
    try:
        return {"worker": get_worker_manager().unload_worker(worker_id)}
    except KeyError:
        raise HTTPException(404, "Model Worker not found")
    except WorkerManagerError as exc:
        _worker_error(exc)


@router.post("/workers/{worker_id}/stop")
def stop_worker(worker_id: str):
    try:
        return {"worker": get_worker_manager().stop_worker(worker_id)}
    except KeyError:
        raise HTTPException(404, "Model Worker not found")
    except WorkerManagerError as exc:
        _worker_error(exc)


@router.post("/workers/{worker_id}/probe")
def probe_worker(worker_id: str, payload: WorkerProbeRequest):
    try:
        return get_worker_manager().probe_worker(
            worker_id,
            requested_backend=payload.requested_backend,
            priority=payload.priority,
            keep_loaded=payload.keep_loaded,
        )
    except KeyError:
        raise HTTPException(404, "Model Worker not found")
    except WorkerManagerError as exc:
        _worker_error(exc)


@router.get("/jobs")
def list_jobs(worker_id: str = None, limit: int = Query(default=100, ge=1, le=500)):
    return {"items": get_worker_manager().list_jobs(worker_id=worker_id, limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = get_worker_manager().get_job(job_id)
    if job is None:
        raise HTTPException(404, "Model runtime job not found")
    return {"job": job}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    try:
        return {"job": get_worker_manager().cancel_job(job_id)}
    except KeyError:
        raise HTTPException(404, "Model runtime job not found")
    except WorkerManagerError as exc:
        _worker_error(exc)
