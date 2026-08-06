"""B601 ROS2 + MoveIt2 bridge API."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from dependencies import b601_ros2 as ros2dep
from runtime_lock import RuntimeLockBusy, RuntimeMode, b601_runtime_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ros2", tags=["b601-ros2"])

DEFAULT_CAN = os.environ.get("BOTVERSEX_B601_CAN", "can0")

_bringup_proc: Optional[subprocess.Popen] = None


class Ros2LaunchRequest(BaseModel):
    use_rviz: bool = False
    channel: str = DEFAULT_CAN


class Ros2MovePoseRequest(BaseModel):
    position: List[float] = Field(..., min_length=3, max_length=3)
    orientation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    duration: float = Field(default=2.0, ge=0.5, le=30.0)


class Ros2JointTrajectoryRequest(BaseModel):
    joint_names: List[str] = Field(default_factory=lambda: [f"joint{i}" for i in range(1, 7)])
    positions: List[float] = Field(..., min_length=6, max_length=6)
    duration: float = Field(default=5.0, ge=0.5, le=60.0)


class Ros2GripperSetRequest(BaseModel):
    position: float = Field(default=5.0, description="Gripper motor position rad")


def _ros_shell_prefix() -> str:
    distro = ros2dep.ros_distro()
    opt = f"/opt/ros/{distro}/setup.bash"
    install = ros2dep.setup_bash()
    if not install or not Path(opt).is_file():
        raise HTTPException(status_code=503, detail="ROS2 工作空间未安装，请运行 scripts/b601_ros2_install.sh")
    return f"source {opt} && source {install} && "


async def _run_ros_cmd(cmd: str, timeout: float = 60.0) -> tuple[int, str]:
    full = _ros_shell_prefix() + cmd

    def _exec() -> tuple[int, str]:
        r = subprocess.run(
            ["bash", "-lc", full],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out

    return await asyncio.to_thread(_exec)


@router.get("/health")
async def ros2_health() -> Dict[str, Any]:
    h = ros2dep.probe_health()
    running = _bringup_proc is not None and _bringup_proc.poll() is None
    return {**h, "bringup_running": running, **b601_runtime_lock.status_dict()}


@router.get("/status")
async def ros2_status() -> Dict[str, Any]:
    code, nodes_out = await _run_ros_cmd("ros2 node list", timeout=15)
    _, topics_out = await _run_ros_cmd("ros2 topic list", timeout=15)
    nodes = [ln.strip() for ln in nodes_out.splitlines() if ln.strip().startswith("/")]
    topics = [ln.strip() for ln in topics_out.splitlines() if ln.strip().startswith("/")]
    return {
        "bringup_running": _bringup_proc is not None and _bringup_proc.poll() is None,
        "nodes": nodes,
        "topics": topics,
        "joint_states_hz": None,
        "ok": code == 0,
    }


@router.post("/launch")
async def ros2_launch(body: Ros2LaunchRequest) -> Dict[str, Any]:
    global _bringup_proc

    h = ros2dep.probe_health()
    if not h.get("ready"):
        raise HTTPException(status_code=503, detail="ROS2 未就绪 — 运行 scripts/b601_ros2_install.sh")

    if _bringup_proc and _bringup_proc.poll() is None:
        return {"ok": True, "running": True, "message": "bringup 已在运行"}

    try:
        await b601_runtime_lock.acquire(RuntimeMode.ROS2, "ros2-bringup")
    except RuntimeLockBusy as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc

    rviz = "true" if body.use_rviz else "false"
    cmd = (
        _ros_shell_prefix()
        + f"ros2 launch rebotarm_bringup bringup.launch.py model:=rs channel:={body.channel} use_rviz:={rviz}"
    )
    _bringup_proc = subprocess.Popen(
        ["bash", "-lc", cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    await asyncio.sleep(3.0)
    if _bringup_proc.poll() is not None:
        out = (_bringup_proc.stdout.read() if _bringup_proc.stdout else "") or ""
        _bringup_proc = None
        await b601_runtime_lock.release(RuntimeMode.ROS2)
        raise HTTPException(status_code=500, detail=out[-500:] or "bringup 启动失败")
    return {"ok": True, "running": True, "pid": _bringup_proc.pid}


@router.post("/stop")
async def ros2_stop() -> Dict[str, Any]:
    global _bringup_proc
    proc = _bringup_proc
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        except Exception:
            proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, 10)
        except Exception:
            proc.kill()
    _bringup_proc = None
    await b601_runtime_lock.release(RuntimeMode.ROS2)
    return {"ok": True, "stopped": True}


@router.post("/move_pose")
async def ros2_move_pose(body: Ros2MovePoseRequest) -> Dict[str, Any]:
    if not (_bringup_proc and _bringup_proc.poll() is None):
        raise HTTPException(status_code=409, detail="请先启动 ROS2 bringup")
    x, y, z = body.position
    ox, oy, oz, ow = (body.orientation + [0, 0, 0, 1])[:4]
    goal = (
        f'{{target_pose: {{position: {{x: {x}, y: {y}, z: {z}}}, '
        f"orientation: {{x: {ox}, y: {oy}, z: {oz}, w: {ow}}}}}, "
        f"duration: {body.duration}}}"
    )
    code, out = await _run_ros_cmd(
        f"ros2 action send_goal /rebotarm/move_to_pose rebotarm_msgs/action/MoveToPose '{goal}'",
        timeout=body.duration + 30,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-400:] or "move_to_pose 失败")
    return {"ok": True, "log": out[-800:]}


@router.post("/follow_joint_trajectory")
async def ros2_follow_joint_trajectory(body: Ros2JointTrajectoryRequest) -> Dict[str, Any]:
    if not (_bringup_proc and _bringup_proc.poll() is None):
        raise HTTPException(status_code=409, detail="请先启动 ROS2 bringup")
    names = ",".join(f"'{n}'" for n in body.joint_names[:6])
    pos = ",".join(str(p) for p in body.positions[:6])
    sec = int(body.duration)
    goal = (
        f"{{trajectory: {{joint_names: [{names}], "
        f"points: [{{positions: [{pos}], time_from_start: {{sec: {sec}}}}}]}}}}"
    )
    code, out = await _run_ros_cmd(
        f"ros2 action send_goal /rebotarm/follow_joint_trajectory "
        f"control_msgs/action/FollowJointTrajectory '{goal}'",
        timeout=body.duration + 30,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-400:] or "轨迹执行失败")
    return {"ok": True, "log": out[-800:]}


@router.post("/gripper/open")
async def ros2_gripper_open() -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        'ros2 service call /rebotarm/gripper/open rebotarm_msgs/srv/GripperCommand "{}"',
        timeout=15,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.post("/gripper/close")
async def ros2_gripper_close() -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        'ros2 service call /rebotarm/gripper/close rebotarm_msgs/srv/GripperCommand "{}"',
        timeout=15,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.post("/gripper/set")
async def ros2_gripper_set(body: Ros2GripperSetRequest) -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        f'ros2 service call /rebotarm/gripper/set rebotarm_msgs/srv/SetGripper "{{position: {body.position}}}"',
        timeout=15,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.post("/gravity_comp/start")
async def ros2_gravity_comp_start() -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        "ros2 service call /rebotarm/gravity_compensation/start std_srvs/srv/Trigger",
        timeout=15,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.post("/gravity_comp/stop")
async def ros2_gravity_comp_stop() -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        "ros2 service call /rebotarm/gravity_compensation/stop std_srvs/srv/Trigger",
        timeout=15,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.post("/safe_home")
async def ros2_safe_home() -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        "ros2 service call /rebotarm/safe_home std_srvs/srv/Trigger",
        timeout=30,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.post("/disable")
async def ros2_disable() -> Dict[str, Any]:
    code, out = await _run_ros_cmd(
        "ros2 service call /rebotarm/disable std_srvs/srv/Trigger",
        timeout=15,
    )
    if code != 0:
        raise HTTPException(status_code=500, detail=out[-300:])
    return {"ok": True}


@router.websocket("/ws/joint_states")
async def ws_ros2_joint_states(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            if not (_bringup_proc and _bringup_proc.poll() is None):
                await websocket.send_json({"ok": False, "message": "bringup not running"})
                await asyncio.sleep(1.0)
                continue
            code, out = await _run_ros_cmd(
                "ros2 topic echo /rebotarm/joint_states --once",
                timeout=5,
            )
            payload: Dict[str, Any] = {"ok": code == 0, "raw": out[-2000:] if out else ""}
            if code == 0 and out:
                m = re.search(r"position:\s*\[([^\]]+)\]", out)
                if m:
                    try:
                        pos = [float(x.strip()) for x in m.group(1).split(",") if x.strip()]
                        payload["positions"] = pos
                    except ValueError:
                        pass
            await websocket.send_json(payload)
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
