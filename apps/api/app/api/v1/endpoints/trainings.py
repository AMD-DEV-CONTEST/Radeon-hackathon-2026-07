"""Training jobs REST (M3.1 骨架 + M7.3 Qualia cloud training)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.models.training import TrainingJob
from app.models.user import User
from app.services import training_service as svc
from app.services import qualia_service as qualia_svc
from app.services.entitlement_service import (
    check_training_create,
    effective_tier,
    get_plan_limits,
    record_training_created,
)

router = APIRouter()

_COURSE_TEMPLATES = Path(__file__).resolve().parents[3] / "data" / "course_templates.yaml"


@router.get("/course-templates")
async def list_course_templates() -> dict[str, Any]:
    """Pre-built lab tasks for Training wizard (pick / place / pour)."""
    if not _COURSE_TEMPLATES.is_file():
        return {"schema_version": "botversex.course_templates.v1", "templates": []}
    data = yaml.safe_load(_COURSE_TEMPLATES.read_text(encoding="utf-8")) or {}
    return {
        "schema_version": data.get("schema_version", "botversex.course_templates.v1"),
        "templates": data.get("templates") or [],
    }


class CreateTrainingRequest(BaseModel):
    dataset_id: str = Field(min_length=1)
    algo: str = "mlp_baseline"
    train_backend: str = Field("local", pattern="^(local|qualia)$")
    epochs: int = Field(10, ge=1, le=1000)
    batch_size: int = Field(32, ge=1, le=1024)
    lr: float = Field(1e-3, gt=0, le=1.0)
    hidden: int = Field(64, ge=8, le=1024)
    # ── Qualia-only fields (ignored when train_backend=local) ───────────────
    dataset_hf_id: str | None = Field(None, description="HF dataset repo for Qualia")
    instance_type: str | None = Field(None, description="Qualia GPU instance type")
    hours: float | None = Field(None, ge=0.1, le=48.0, description="Qualia budget")
    model_id: str | None = Field(None, description="Qualia base VLA model (smolvla/pi0)")
    camera_keys: list[str] | None = Field(None, description="Dataset camera columns")
    region: str | None = Field(None, description="Qualia datacenter region")


@router.get("/algorithms")
async def list_algorithms(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List all available training algorithms (local + Qualia cloud)."""
    algos = qualia_svc.list_algorithms()
    return {
        "algorithms": algos,
        "qualia_configured": qualia_svc.is_configured(),
    }


@router.get("/qualia/instances")
async def qualia_instances(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """M9.4: list GPU instance types visible to the configured Qualia key."""
    if not qualia_svc.is_configured():
        return {"ok": False, "error": "Qualia token not configured", "instances": []}
    try:
        return {"ok": True, "instances": qualia_svc.list_instances()}
    except Exception as e:
        return {"ok": False, "error": str(e), "instances": []}


@router.post("/qualia/validate")
async def qualia_validate(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """M9.4: health-check the Qualia key that's currently in the env."""
    return qualia_svc.validate_key()


@router.get("/qualia/jobs/{job_id}")
async def qualia_job_status(
    job_id: str,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Live Qualia job status by upstream job id (no local DB row required)."""
    if not qualia_svc.is_configured():
        return {"ok": False, "error": "Qualia token not configured", "job_id": job_id}
    live = qualia_svc.get_training_status(job_id)
    status = (live.get("status") or "").lower()
    return {
        "ok": True,
        "job_id": job_id,
        "status": status or live.get("status"),
        "phase": live.get("phase"),
        "output_model_id": live.get("output_model_id"),
        "qualia_status": live,
    }


@router.get("/qualia/defaults")
async def qualia_defaults(
    algorithm: str,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """M9.4: return suggested Qualia job params for a given algorithm."""
    d = qualia_svc.defaults_for(algorithm)
    cost = qualia_svc.estimate_cost(d["instance_type"], float(d["hours"]))
    return {"algorithm": algorithm, "defaults": d, "cost_estimate": cost}


@router.get("/qualia/dataset_probe")
async def qualia_dataset_probe(
    dataset_hf_id: str = "",
    local_dataset_id: str = "",
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """M9.4 helper: probe HF repo and/or local dataset for image columns."""
    return qualia_svc.probe_training_dataset(
        dataset_hf_id=dataset_hf_id or None,
        local_dataset_id=local_dataset_id or None,
    )


class AugmentationRequest(BaseModel):
    dataset_hf_id: str = Field(min_length=1)
    transforms: list[str] = Field(default_factory=lambda: ["lighting", "noise"])
    copies: int = Field(3, ge=1, le=50)
    mode: str = Field("stacked", pattern="^(stacked|independent)$")
    dataset_mode: str = Field("copy", pattern="^(copy|inplace)$")
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/qualia/augmentation")
async def create_augmentation(
    req: AugmentationRequest,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit a deterministic data augmentation job to Qualia.

    Only 'deterministic' augmentation types are allowed (lighting, noise, blur,
    occlusion). Generative augmentation (world model, URDF inpaint) is not
    supported by the current Qualia API and will be rejected.
    """
    ALLOWED_TRANSFORMS = {"lighting", "noise", "blur", "occlusion"}
    invalid = [t for t in req.transforms if t not in ALLOWED_TRANSFORMS]
    if invalid:
        raise HTTPException(
            400,
            f"Generative transforms not supported: {invalid}. "
            f"Only deterministic transforms allowed: {sorted(ALLOWED_TRANSFORMS)}",
        )

    if not qualia_svc.is_configured():
        raise HTTPException(503, "Qualia API token not configured")

    result = qualia_svc.create_augmentation_job(
        dataset_hf_id=req.dataset_hf_id,
        transforms=req.transforms,
        copies=req.copies,
        mode=req.mode,
        dataset_mode=req.dataset_mode,
        params=req.params,
    )
    if result.get("status") == "error":
        raise HTTPException(502, result.get("error", "Augmentation failed"))
    return result


@router.get("/qualia/augmentation/{job_id}")
async def get_augmentation_status(
    job_id: str,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll status of a Qualia augmentation job."""
    if not qualia_svc.is_configured():
        raise HTTPException(503, "Qualia API token not configured")
    return qualia_svc.get_augmentation_status(job_id)


@router.post("/qualia/augmentation/{job_id}/cancel")
async def cancel_augmentation(
    job_id: str,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a running Qualia augmentation job."""
    if not qualia_svc.is_configured():
        raise HTTPException(503, "Qualia API token not configured")
    return qualia_svc.cancel_augmentation_job(job_id)


@router.get("/dataset_readiness")
async def dataset_readiness(
    dataset_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Zero-friction: check if a dataset is ready for cloud training.

    Returns a simple status the UI can display without exposing internals.
    """
    result = qualia_svc.resolve_dataset_for_training(dataset_id, db)
    if result.get("ok"):
        return {
            "ready": True,
            "status": "cloud_ready",
            "label": "可直接训练",
            "dataset_hf_id": result["dataset_hf_id"],
            "camera_keys": result["camera_keys"],
        }
    return {
        "ready": False,
        "status": "not_ready",
        "label": result.get("error", "无法训练"),
    }


@router.get("/algorithms/recommend")
async def recommend_algorithm(
    has_camera: bool = False,
    episode_count: int | None = None,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """M9.3: server-side algorithm recommender.

    Used by the M9.2 onboarding wizard (Step 5) and any CLI tooling so the
    rule — vision + large dataset → SmolVLA, vision + few demos → local
    vision MLP, no camera + long trajectories → ACT, else → MLP baseline —
    lives in exactly one place.
    """
    return {
        "recommended": qualia_svc.recommend_algorithm(
            has_camera=has_camera,
            episode_count=episode_count,
        ),
        "qualia_configured": qualia_svc.is_configured(),
    }


@router.get("")
async def list_trainings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    svc.reconcile_user_training_jobs(db, user.id)
    q = db.query(TrainingJob)
    if user.role != "admin":
        q = q.filter(TrainingJob.created_by == user.id)
    rows = q.order_by(TrainingJob.created_at.desc()).limit(200).all()
    return {"total": len(rows), "items": [svc.job_to_dict(r) for r in rows]}


@router.post("/reconcile")
async def reconcile_trainings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Sync stale queued/running jobs with Qualia / local worker before quota checks."""
    return svc.reconcile_user_training_jobs(db, user.id)


@router.get("/entitlements/usage")
async def training_usage(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    from app.services.entitlement_service import (
        METRIC_TRAINING_LOCAL,
        METRIC_TRAINING_QUALIA,
        current_period,
        get_counter,
    )

    tier = effective_tier(user)
    limits = get_plan_limits(tier)
    period = current_period()
    return {
        "tier": tier,
        "period": period,
        "usage": {
            "training_local": get_counter(db, user.id, METRIC_TRAINING_LOCAL, period),
            "training_qualia": get_counter(db, user.id, METRIC_TRAINING_QUALIA, period),
        },
        "limits": {
            "training_local_monthly": limits.training_local_monthly,
            "training_qualia_monthly": limits.training_qualia_monthly,
            "training_concurrent_max": limits.training_concurrent_max,
        },
    }


@router.get("/{job_id}")
async def get_training(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not row:
        raise HTTPException(404, f"training job '{job_id}' not found")
    if user.role != "admin" and row.created_by != user.id:
        raise HTTPException(404, f"training job '{job_id}' not found")
    data = svc.job_to_dict(row)
    # M9.4: for cloud jobs, enrich with live Qualia status + sync DB state.
    hp = row.hparams_json or {}
    qualia_id = hp.get("qualia_job_id")
    if row.train_backend == "qualia" and qualia_id:
        live = qualia_svc.get_training_status(qualia_id)
        data["qualia_status"] = live
        upstream = (live.get("status") or "").lower()
        if upstream in ("succeeded", "completed", "done", "success") and row.status != "succeeded":
            row.status = "succeeded"
            if live.get("output_model_id"):
                row.hparams_json = {**hp, "output_model_id": live["output_model_id"]}
            db.commit()
        elif upstream in ("failed", "cancelled", "error") and row.status not in ("failed", "cancelled"):
            row.status = upstream if upstream in ("failed", "cancelled") else "failed"
            db.commit()
        data = svc.job_to_dict(row) | {"qualia_status": live}
    return data


@router.post("", status_code=201)
async def create_training(
    req: CreateTrainingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    svc.reconcile_user_training_jobs(db, user.id)
    check_training_create(
        db,
        user,
        train_backend=req.train_backend,
        hours=req.hours,
    )
    job = TrainingJob(
        dataset_id=req.dataset_id,
        algo=req.algo,
        train_backend=req.train_backend,
        hparams_json={
            "epochs": req.epochs,
            "batch_size": req.batch_size,
            "lr": req.lr,
            "hidden": req.hidden,
        },
        total_epochs=req.epochs,
        status="queued",
        created_by=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if req.train_backend == "qualia":
        # Zero-friction: auto-resolve HF repo + camera keys when not provided
        resolved_hf_id = req.dataset_hf_id
        resolved_camera_keys = req.camera_keys
        if not resolved_hf_id or not resolved_camera_keys:
            resolution = qualia_svc.resolve_dataset_for_training(req.dataset_id, db)
            if not resolution.get("ok"):
                job.status = "failed"
                job.error_msg = resolution.get("error", "数据集无法用于训练")
                db.commit()
                db.refresh(job)
                return svc.job_to_dict(job)
            if not resolved_hf_id:
                resolved_hf_id = resolution["dataset_hf_id"]
            if not resolved_camera_keys:
                resolved_camera_keys = resolution["camera_keys"]

        qualia_result = qualia_svc.create_training_job(
            dataset_hf_id=resolved_hf_id,
            algorithm=req.algo,
            params={
                "batch_size": req.batch_size,
                "instance_type": req.instance_type,
                "hours": req.hours,
                "model_id": req.model_id,
                "camera_keys": resolved_camera_keys,
                "region": req.region,
                "project_name": f"botversex-{req.algo}-{req.dataset_id[:8]}",
                "job_description": f"{req.algo} on {resolved_hf_id}",
            },
        )
        # Persist everything we sent/got so worker polling + UI have enough
        # context without a second DB round trip.
        job.hparams_json = {
            **(job.hparams_json or {}),
            "qualia_job_id": qualia_result.get("job_id", ""),
            "qualia_project_id": qualia_result.get("project_id"),
            "instance_type": qualia_result.get("instance_type"),
            "hours": qualia_result.get("hours"),
            "dataset_hf_id": resolved_hf_id,
        }
        if qualia_result.get("status") == "error":
            job.status = "failed"
            job.error_msg = qualia_result.get("error", "Qualia submission failed")
        elif qualia_result.get("status") == "pending_config":
            job.status = "failed"
            job.error_msg = qualia_result.get("message", "Qualia not configured")
        else:
            # Cloud runs don't have local epochs — mark as running; a poller
            # will flip this to succeeded/failed once Qualia reports back.
            job.status = "running"
            job.error_msg = None
        db.commit()
        db.refresh(job)
    else:
        from app.services import worker as worker_svc
        try:
            worker_svc.spawn_job(str(job.id))
        except Exception as e:
            job.status = "failed"
            job.error_msg = f"spawn failed: {e}"
            db.commit()
            db.refresh(job)

    record_training_created(db, user, req.train_backend)
    return svc.job_to_dict(job)


@router.post("/{job_id}/cancel")
async def cancel_training(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    row = db.query(TrainingJob).filter(TrainingJob.id == job_id).first()
    if not row:
        raise HTTPException(404, f"training job '{job_id}' not found")
    if user.role != "admin" and row.created_by != user.id:
        raise HTTPException(404, f"training job '{job_id}' not found")
    if row.status in ("succeeded", "failed", "cancelled"):
        return svc.job_to_dict(row)

    # M9.4: route cloud cancels through the Qualia SDK; local cancels keep
    # using the existing worker subprocess path.
    hp = row.hparams_json or {}
    if row.train_backend == "qualia" and hp.get("qualia_job_id"):
        result = qualia_svc.cancel_training_job(hp["qualia_job_id"])
        if result.get("status") == "error":
            return {**svc.job_to_dict(row), "cancel_error": result.get("error")}
        row.status = "cancelled"
        db.commit()
        db.refresh(row)
        return {**svc.job_to_dict(row), "qualia_cancel": result}

    from app.services import worker as worker_svc
    try:
        worker_svc.cancel_job(str(row.id))
    except Exception as e:
        return {**svc.job_to_dict(row), "cancel_error": str(e)}
    row.status = "cancelled"
    db.commit()
    db.refresh(row)
    return svc.job_to_dict(row)
