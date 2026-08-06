"""Skills API — basic functionality line (M7).

Surface:
    GET    /api/v1/skills                              list registry entries
    GET    /api/v1/skills/{skill_id}                   single registry entry
    GET    /api/v1/skills/runtimes                     proxy realtime runtimes (adds compat info)
    GET    /api/v1/skills/installations                my installations (optionally ?runtime_id=)
    POST   /api/v1/skills/{skill_id}/install           install onto a runtime (body: runtime_id, params)
    PATCH  /api/v1/skills/installations/{inst_id}      update enabled / params
    DELETE /api/v1/skills/installations/{inst_id}      uninstall
    POST   /api/v1/skills/{skill_id}/run               trigger a simulated run (body: runtime_id, params?)
    GET    /api/v1/skills/runs                         list my recent runs (optionally filtered)
    GET    /api/v1/skills/runs/{run_id}                single run

Execution:
    `run` now supports REAL dispatch for a subset of verbs:
      - teleop  -> realtime /api/teleop/start
      - record  -> realtime /api/recording/start (+ async status monitor)
    Other verbs keep the simulated fallback path.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.endpoints.auth import get_current_user
from app.core.config import settings
from app.models.skill import SkillInstallation, SkillRun
from app.models.user import User
from app.services import skill_registry
from app.services.entitlement_service import check_skill_run, record_skill_run

log = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────


class InstallRequest(BaseModel):
    runtime_id: str
    runtime_robot_type: Optional[str] = None  # used for compat check if runtimes API unreachable
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PatchInstallRequest(BaseModel):
    enabled: Optional[bool] = None
    params: Optional[dict[str, Any]] = None


class RunRequest(BaseModel):
    runtime_id: str
    params: dict[str, Any] = Field(default_factory=dict)


# ── Helpers ────────────────────────────────────────────────────────────────


async def _fetch_runtimes() -> list[dict[str, Any]]:
    """Fetch runtime list from realtime service. Returns [] on failure."""
    url = settings.REALTIME_SERVICE_URL.rstrip("/") + "/api/runtimes"
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return []
            data = r.json()
            return data.get("runtimes") or []
    except Exception as e:  # noqa: BLE001
        log.warning("skills: runtimes fetch failed: %s", e)
        return []


async def _realtime_post(path: str, payload: dict[str, Any], timeout_s: float = 8.0) -> dict[str, Any]:
    url = settings.REALTIME_SERVICE_URL.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
            r = await client.post(url, json=payload)
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "realtime_dispatch_error",
                        "path": path,
                        "status": r.status_code,
                        "response": data,
                    },
                )
            return data
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={
                "code": "realtime_unreachable",
                "path": path,
                "message": str(e),
            },
        ) from e


async def _realtime_get(path: str, timeout_s: float = 4.0) -> dict[str, Any]:
    url = settings.REALTIME_SERVICE_URL.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
            r = await client.get(url)
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "realtime_dispatch_error",
                        "path": path,
                        "status": r.status_code,
                        "response": data,
                    },
                )
            return data
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={
                "code": "realtime_unreachable",
                "path": path,
                "message": str(e),
            },
        ) from e


def _serialize_installation(inst: SkillInstallation) -> dict[str, Any]:
    return {
        "id": str(inst.id),
        "skill_id": inst.skill_id,
        "runtime_id": inst.runtime_id,
        "enabled": inst.enabled,
        "params": inst.params_json or {},
        "installed_at": inst.installed_at.isoformat() if inst.installed_at else None,
        "updated_at": inst.updated_at.isoformat() if inst.updated_at else None,
    }


def _serialize_run(run: SkillRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "skill_id": run.skill_id,
        "runtime_id": run.runtime_id,
        "verb": run.verb,
        "status": run.status,
        "params": run.params_json or {},
        "result": run.result_json,
        "log_excerpt": run.log_excerpt,
        "error_msg": run.error_msg,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
    }


def _check_compat(skill: dict[str, Any], robot_type: Optional[str]) -> Optional[str]:
    if not robot_type:
        return None  # skip compat check when we can't verify
    compat = skill.get("compatible_types") or []
    if skill.get("robot_type") == robot_type:
        return None
    if robot_type in compat:
        return None
    return f"skill {skill['skill_id']} not compatible with runtime robot_type={robot_type}"


# ── Registry ───────────────────────────────────────────────────────────────


@router.get("")
async def list_skills() -> dict[str, Any]:
    skills = skill_registry.list_skills()
    return {"skills": skills, "count": len(skills)}


@router.get("/runtimes")
async def list_runtimes_with_skills() -> dict[str, Any]:
    """Return realtime runtimes enriched with compatible_skill_ids."""
    runtimes = await _fetch_runtimes()
    out: list[dict[str, Any]] = []
    for rt in runtimes:
        rtype = rt.get("robot_type") or ""
        compat = [s["skill_id"] for s in skill_registry.get_compatible_skills(rtype)]
        out.append({**rt, "compatible_skill_ids": compat})
    return {"runtimes": out, "count": len(out)}


@router.get("/installations")
async def list_my_installations(
    runtime_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    q = db.query(SkillInstallation).filter(SkillInstallation.user_id == user.id)
    if runtime_id:
        q = q.filter(SkillInstallation.runtime_id == runtime_id)
    installs = q.order_by(SkillInstallation.installed_at.desc()).all()
    return {"installations": [_serialize_installation(i) for i in installs]}


@router.get("/runs")
async def list_my_runs(
    skill_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    q = db.query(SkillRun).filter(SkillRun.user_id == user.id)
    if skill_id:
        q = q.filter(SkillRun.skill_id == skill_id)
    runs = q.order_by(SkillRun.started_at.desc()).limit(limit).all()
    return {"runs": [_serialize_run(r) for r in runs]}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    run = (
        db.query(SkillRun)
        .filter(SkillRun.id == run_id, SkillRun.user_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return _serialize_run(run)


@router.get("/{skill_id}")
async def get_skill(skill_id: str) -> dict[str, Any]:
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"skill {skill_id} not found")
    return skill


@router.post("/{skill_id}/install")
async def install_skill(
    skill_id: str,
    body: InstallRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")

    # compat check — prefer explicit robot_type from caller; else resolve via realtime
    robot_type = body.runtime_robot_type
    if not robot_type:
        runtimes = await _fetch_runtimes()
        for rt in runtimes:
            if rt.get("runtime_id") == body.runtime_id:
                robot_type = rt.get("robot_type")
                break
    err = _check_compat(skill, robot_type)
    if err:
        raise HTTPException(status_code=400, detail=err)

    # validate params (only non-required checks when installing with empty params)
    if body.params:
        errors = skill_registry.validate_params(skill, body.params)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})

    existing = (
        db.query(SkillInstallation)
        .filter(
            SkillInstallation.user_id == user.id,
            SkillInstallation.skill_id == skill_id,
            SkillInstallation.runtime_id == body.runtime_id,
        )
        .first()
    )
    if existing:
        existing.enabled = body.enabled
        if body.params is not None:
            existing.params_json = body.params
        db.commit()
        db.refresh(existing)
        return _serialize_installation(existing)

    inst = SkillInstallation(
        user_id=user.id,
        skill_id=skill_id,
        runtime_id=body.runtime_id,
        enabled=body.enabled,
        params_json=body.params or {},
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return _serialize_installation(inst)


@router.patch("/installations/{inst_id}")
async def patch_installation(
    inst_id: str,
    body: PatchInstallRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    inst = (
        db.query(SkillInstallation)
        .filter(SkillInstallation.id == inst_id, SkillInstallation.user_id == user.id)
        .first()
    )
    if not inst:
        raise HTTPException(status_code=404, detail="installation not found")

    if body.params is not None:
        skill = skill_registry.get_skill(inst.skill_id)
        if skill:
            errors = skill_registry.validate_params(skill, body.params)
            if errors:
                raise HTTPException(status_code=400, detail={"errors": errors})
        inst.params_json = body.params

    if body.enabled is not None:
        inst.enabled = body.enabled

    db.commit()
    db.refresh(inst)
    return _serialize_installation(inst)


@router.delete("/installations/{inst_id}")
async def delete_installation(
    inst_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    inst = (
        db.query(SkillInstallation)
        .filter(SkillInstallation.id == inst_id, SkillInstallation.user_id == user.id)
        .first()
    )
    if not inst:
        raise HTTPException(status_code=404, detail="installation not found")
    db.delete(inst)
    db.commit()
    return {"ok": True}


# ── Execution (simulated, Phase 4 basic) ───────────────────────────────────


async def _simulate_run(run_id: str, verb: str) -> None:
    """Flip a skill_run from running → succeeded after a short delay.

    Phase 1 simulator. In a future pass we would dispatch to the realtime
    service here (e.g. POST /api/teleop/replay, /api/record/start, etc.)
    based on `verb`.
    """
    # Import lazily to avoid circular imports during app startup.
    from app.models.database import SessionLocal

    await asyncio.sleep(1.5)
    db = SessionLocal()
    try:
        run = db.query(SkillRun).filter(SkillRun.id == run_id).first()
        if not run:
            return
        if run.status != "running":
            return  # someone cancelled / replaced it
        run.status = "succeeded"
        run.ended_at = datetime.utcnow()
        run.log_excerpt = (
            f"[simulated] verb={verb} executed on {run.runtime_id}. "
            "Skill run completed without error (no hardware dispatch in basic line)."
        )
        run.result_json = {"simulated": True, "verb": verb}
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("skills: simulator failed for run %s: %s", run_id, e)
    finally:
        db.close()


async def _monitor_record_run(run_id: str, timeout_s: int = 60 * 60) -> None:
    from app.models.database import SessionLocal

    deadline = asyncio.get_event_loop().time() + timeout_s
    poll_s = 2.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(poll_s)
        db = SessionLocal()
        try:
            run = db.query(SkillRun).filter(SkillRun.id == run_id).first()
            if not run:
                return
            if run.status not in ("running", "queued"):
                return
            status = await _realtime_get("/api/recording/status", timeout_s=4.0)
            still_running = bool(status.get("running"))
            run.log_excerpt = "\n".join((status.get("log_tail") or [])[-10:]) or run.log_excerpt
            if still_running:
                db.commit()
                continue

            rc = status.get("returncode")
            run.ended_at = datetime.utcnow()
            run.result_json = {
                "recording_status": status,
                "session_id": status.get("session_id"),
            }
            if rc is None or int(rc) == 0:
                run.status = "succeeded"
            else:
                run.status = "failed"
                run.error_msg = status.get("last_error") or f"recording process exited rc={rc}"
            db.commit()
            return
        except Exception as e:  # noqa: BLE001
            log.exception("skills: monitor_record_run failed for run %s: %s", run_id, e)
        finally:
            db.close()

    db = SessionLocal()
    try:
        run = db.query(SkillRun).filter(SkillRun.id == run_id).first()
        if run and run.status in ("running", "queued"):
            run.status = "failed"
            run.ended_at = datetime.utcnow()
            run.error_msg = f"recording monitor timeout after {timeout_s}s"
            db.commit()
    finally:
        db.close()


@router.post("/{skill_id}/run")
async def run_skill(
    skill_id: str,
    body: RunRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    skill = skill_registry.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")

    # resolve effective params: caller params > installation params
    inst = (
        db.query(SkillInstallation)
        .filter(
            SkillInstallation.user_id == user.id,
            SkillInstallation.skill_id == skill_id,
            SkillInstallation.runtime_id == body.runtime_id,
        )
        .first()
    )
    if inst and not inst.enabled:
        raise HTTPException(status_code=400, detail="skill installation is disabled")

    effective_params: dict[str, Any] = {}
    if inst and inst.params_json:
        effective_params.update(inst.params_json)
    if body.params:
        effective_params.update(body.params)

    errors = skill_registry.validate_params(skill, effective_params)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    verb = skill.get("verb", "unknown")
    check_skill_run(db, user, verb)

    run = SkillRun(
        user_id=user.id,
        skill_id=skill_id,
        runtime_id=body.runtime_id,
        verb=verb,
        status="running",
        params_json=effective_params,
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    record_skill_run(db, user)

    # Real dispatch for selected verbs. Anything else keeps simulated fallback.
    try:
        if run.verb == "teleop":
            leader_port = str(effective_params.get("leader_port") or "").strip()
            follower_port = str(effective_params.get("follower_port") or "").strip()
            if not leader_port or not follower_port:
                raise HTTPException(
                    status_code=400,
                    detail="teleop run requires params.leader_port and params.follower_port",
                )
            payload = {
                "leader_port": leader_port,
                "follower_port": follower_port,
                "torque_on_start": bool(effective_params.get("torque_on_start", True)),
                "force": bool(effective_params.get("force", False)),
            }
            rt = await _realtime_post("/api/teleop/start", payload, timeout_s=12.0)
            run.status = "succeeded"
            run.ended_at = datetime.utcnow()
            run.result_json = {
                "dispatched": True,
                "provider": "realtime",
                "path": "/api/teleop/start",
                "response": rt,
            }
            run.log_excerpt = (
                f"[dispatch] teleop started on leader={leader_port} follower={follower_port} "
                f"session={rt.get('session_id')}"
            )
            db.commit()
        elif run.verb == "record":
            leader_port = str(effective_params.get("leader_port") or "").strip()
            follower_port = str(effective_params.get("follower_port") or "").strip()
            dataset_name = str(effective_params.get("dataset_name") or "").strip()
            single_task = str(effective_params.get("single_task") or "").strip()
            if not leader_port or not follower_port or not dataset_name or not single_task:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "record run requires params.leader_port, params.follower_port, "
                        "params.dataset_name, params.single_task"
                    ),
                )
            camera_index = effective_params.get("camera_index")
            fps = int(float(effective_params.get("fps", 30)))
            duration_s = int(float(effective_params.get("duration_s", 30)))
            episode_count = int(float(effective_params.get("episode_count", 1)))
            owner = str(effective_params.get("repo_owner") or "botversex").strip()
            cameras: list[dict[str, Any]] = []
            if camera_index is not None and str(camera_index).strip() != "":
                cameras.append(
                    {
                        "name": str(effective_params.get("camera_name") or "top"),
                        "index_or_path": int(camera_index),
                        "width": int(float(effective_params.get("camera_width", 640))),
                        "height": int(float(effective_params.get("camera_height", 480))),
                        "fps": fps,
                    }
                )
            payload = {
                "leader_port": leader_port,
                "follower_port": follower_port,
                "repo_id": f"{owner}/{dataset_name}",
                "single_task": single_task,
                "num_episodes": episode_count,
                "episode_time_s": duration_s,
                "reset_time_s": int(float(effective_params.get("reset_time_s", 5))),
                "fps": fps,
                "push_to_hub": bool(effective_params.get("push_to_hub", False)),
                "cameras": cameras,
            }
            rt = await _realtime_post("/api/recording/start", payload, timeout_s=20.0)
            run.result_json = {
                "dispatched": True,
                "provider": "realtime",
                "path": "/api/recording/start",
                "response": rt,
            }
            run.log_excerpt = (
                f"[dispatch] recording started repo={payload['repo_id']} "
                f"episodes={episode_count} session={rt.get('session_id')}"
            )
            db.commit()
            background.add_task(_monitor_record_run, str(run.id))
        else:
            background.add_task(_simulate_run, str(run.id), run.verb)
    except HTTPException as exc:
        run.status = "failed"
        run.ended_at = datetime.utcnow()
        run.error_msg = str(exc.detail)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.ended_at = datetime.utcnow()
        run.error_msg = f"{type(exc).__name__}: {exc}"
        db.commit()

    return _serialize_run(run)
