"""B601-RS Pinocchio FK/IK + Cartesian move API."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from dependencies import b601_kinematics as kin
from runtime_lock import RuntimeLockBusy, RuntimeMode, b601_runtime_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kinematics", tags=["b601-kinematics"])

DEFAULT_CAN = os.environ.get("BOTVERSEX_B601_CAN", "can0")
_REPO_ROOT = Path(__file__).resolve().parents[3]

_move_proc: Optional[subprocess.Popen] = None


class FkRequest(BaseModel):
    joints: Dict[str, float]


class IkRequest(BaseModel):
    position: List[float] = Field(..., min_length=3, max_length=3)
    orientation: Optional[List[float]] = Field(default=None, description="roll pitch yaw radians")
    q_seed: Optional[Dict[str, float]] = None


class MovePoseRequest(BaseModel):
    position: List[float] = Field(..., min_length=3, max_length=3)
    orientation: Optional[List[float]] = None
    q_seed: Optional[Dict[str, float]] = None
    duration: float = Field(default=2.0, ge=0.5, le=30.0)
    dry_run: bool = True
    can_iface: Optional[str] = None


class MoveJointsRequest(BaseModel):
    joints: Dict[str, float]
    duration: float = Field(default=2.0, ge=0.5, le=30.0)
    dry_run: bool = True
    can_iface: Optional[str] = None


def _read_live_joints() -> Dict[str, float]:
    from .b601 import LIVE_JOINTS_PATH, poll_follower_joints

    try:
        if LIVE_JOINTS_PATH.exists():
            age = time.time() - LIVE_JOINTS_PATH.stat().st_mtime
            if age < 5.0:
                data = json.loads(LIVE_JOINTS_PATH.read_text(encoding="utf-8"))
                joints = data.get("joints") or {}
                if isinstance(joints, dict) and joints:
                    return {str(k): float(v) for k, v in joints.items()}
    except Exception:
        pass
    return {}


async def _ensure_pinocchio() -> None:
    h = kin.probe_health()
    if not h.get("pinocchio"):
        raise HTTPException(
            status_code=503,
            detail="Pinocchio 未安装。请运行 scripts/b601_pinocchio_install.sh",
        )
    if not h.get("urdf_exists"):
        raise HTTPException(status_code=503, detail="B601 URDF 缺失")


async def _assert_can_acquire_kinematics() -> None:
    try:
        await b601_runtime_lock.acquire(RuntimeMode.KINEMATICS, "kinematics-move")
    except RuntimeLockBusy as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


@router.get("/health")
async def kinematics_health() -> Dict[str, Any]:
    h = kin.probe_health()
    h["ready_pose"] = kin.ready_pose()
    return h


@router.get("/ready_pose")
async def kinematics_ready_pose() -> Dict[str, Any]:
    await _ensure_pinocchio()
    rp = kin.ready_pose()
    return {"ok": True, **rp}


@router.post("/fk")
async def kinematics_fk(body: FkRequest) -> Dict[str, Any]:
    await _ensure_pinocchio()
    try:
        pose = await asyncio.to_thread(kin.compute_fk, body.joints)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "pose": pose, "joints": body.joints}


@router.post("/ik")
async def kinematics_ik(body: IkRequest) -> Dict[str, Any]:
    await _ensure_pinocchio()
    try:
        if body.q_seed is not None:
            result = await asyncio.to_thread(
                kin.compute_ik, body.position, body.orientation, body.q_seed
            )
        else:
            result = await asyncio.to_thread(
                kin.compute_ik_multi_seed, body.position, body.orientation, None
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": result.get("success", False), **result}


@router.get("/ee_pose")
async def kinematics_ee_pose(can_iface: str = DEFAULT_CAN) -> Dict[str, Any]:
    await _ensure_pinocchio()
    from .b601 import poll_follower_joints

    joints = _read_live_joints()
    if not joints:
        joints = await poll_follower_joints(can_iface)
    if not joints:
        return {"ok": False, "message": "无关节数据", "joints": {}, "pose": None}
    pose = await asyncio.to_thread(kin.compute_fk, joints)
    return {"ok": True, "joints": joints, "pose": pose, "timestamp": time.time()}


@router.websocket("/ws/ee_pose")
async def ws_ee_pose(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            try:
                payload = await kinematics_ee_pose()
                await websocket.send_json(payload)
            except HTTPException:
                await websocket.send_json({"ok": False, "message": "pinocchio unavailable"})
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass


def _runner_python() -> str:
    py = os.environ.get("BOTVERSEX_LEROBOT_PYTHON")
    if py and Path(py).is_file():
        return py
    for candidate in (
        Path.home() / "venvs" / "lerobot" / "bin" / "python3",
        Path(sys.executable),
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


async def _run_kinematics_subprocess(args: List[str], timeout: float = 120.0) -> Dict[str, Any]:
    global _move_proc
    runner = _REPO_ROOT / "scripts" / "b601_kinematics_runner.py"
    if not runner.is_file():
        raise HTTPException(status_code=503, detail=f"Runner missing: {runner}")

    py = _runner_python()
    cmd = [py, str(runner), *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    _move_proc = proc

    def _wait() -> Dict[str, Any]:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"ok": False, "message": "运动超时", "log": ""}
        text = out or ""
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        return {
            "ok": proc.returncode == 0,
            "message": text[-500:] if text else f"exit {proc.returncode}",
            "log": text[-2000:],
        }

    try:
        return await asyncio.to_thread(_wait)
    finally:
        _move_proc = None


@router.post("/move_pose")
async def kinematics_move_pose(body: MovePoseRequest) -> Dict[str, Any]:
    await _ensure_pinocchio()
    from .b601 import poll_follower_joints

    seed = body.q_seed or _read_live_joints() or await poll_follower_joints(body.can_iface or DEFAULT_CAN)
    ik = await asyncio.to_thread(
        kin.compute_ik_multi_seed, body.position, body.orientation, seed or None
    )
    if not ik.get("success"):
        raise HTTPException(
            status_code=422,
            detail=ik.get("message") or f"IK 失败 (error={ik.get('error')})",
        )

    if body.dry_run:
        fk = await asyncio.to_thread(kin.compute_fk, ik["joints"])
        return {
            "ok": True,
            "dry_run": True,
            "joints": ik["joints"],
            "pose": fk,
            "ik_iterations": ik.get("iterations"),
        }

    await _assert_can_acquire_kinematics()
    try:
        payload = json.dumps(
            {
                "mode": "move_pose",
                "position": body.position,
                "orientation": body.orientation,
                "joints": ik["joints"],
                "duration": body.duration,
                "can": body.can_iface or DEFAULT_CAN,
            }
        )
        result = await _run_kinematics_subprocess(["--json", payload])
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result.get("message", "move failed"))
        return {"ok": True, "dry_run": False, "joints": ik["joints"], **result}
    finally:
        await b601_runtime_lock.release(RuntimeMode.KINEMATICS)


@router.post("/move_joints")
async def kinematics_move_joints(body: MoveJointsRequest) -> Dict[str, Any]:
    await _ensure_pinocchio()
    if body.dry_run:
        fk = await asyncio.to_thread(kin.compute_fk, body.joints)
        return {"ok": True, "dry_run": True, "joints": body.joints, "pose": fk}

    await _assert_can_acquire_kinematics()
    try:
        payload = json.dumps(
            {
                "mode": "move_joints",
                "joints": body.joints,
                "duration": body.duration,
                "can": body.can_iface or DEFAULT_CAN,
            }
        )
        result = await _run_kinematics_subprocess(["--json", payload])
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result.get("message", "move failed"))
        return {"ok": True, "dry_run": False, **result}
    finally:
        await b601_runtime_lock.release(RuntimeMode.KINEMATICS)


@router.post("/stop")
async def kinematics_stop() -> Dict[str, Any]:
    global _move_proc
    proc = _move_proc
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    _move_proc = None
    await b601_runtime_lock.release(RuntimeMode.KINEMATICS)
    return {"ok": True, "stopped": True}
