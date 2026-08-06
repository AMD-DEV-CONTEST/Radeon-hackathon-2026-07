"""B601 gravity compensation API."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from runtime_lock import RuntimeLockBusy, RuntimeMode, b601_runtime_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gravity_comp", tags=["b601-gravity-comp"])

DEFAULT_CAN = os.environ.get("BOTVERSEX_B601_CAN", "can0")
_REPO_ROOT = Path(__file__).resolve().parents[3]
_STATE_PORT = 18765

_gc_proc: Optional[subprocess.Popen] = None
_gc_mode: Optional[str] = None
_last_state: Dict[str, Any] = {}


class GravityCompStartRequest(BaseModel):
    mode: str = Field(default="basic", description="basic or lock")
    joint_gains: Dict[int, float] = Field(default_factory=dict)
    can_iface: Optional[str] = None


def _runner_python() -> str:
    for candidate in (
        os.environ.get("BOTVERSEX_LEROBOT_PYTHON"),
        str(Path.home() / "venvs" / "lerobot" / "bin" / "python3"),
        sys.executable,
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return sys.executable


_GC_STATE_PATH = Path("/tmp/b601_gravity_comp_state.json")


def _read_gc_state() -> Dict[str, Any]:
    global _last_state
    try:
        if _GC_STATE_PATH.is_file():
            _last_state = json.loads(_GC_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return _last_state


@router.get("/status")
async def gravity_comp_status() -> Dict[str, Any]:
    running = _gc_proc is not None and _gc_proc.poll() is None
    state = _read_gc_state() if running else _last_state
    return {
        "running": running,
        "mode": _gc_mode,
        "last_state": state,
        **b601_runtime_lock.status_dict(),
    }


@router.post("/start")
async def gravity_comp_start(body: GravityCompStartRequest) -> Dict[str, Any]:
    global _gc_proc, _gc_mode, _last_state

    if body.mode not in ("basic", "lock"):
        raise HTTPException(status_code=400, detail="mode 必须是 basic 或 lock")

    if _gc_proc and _gc_proc.poll() is None:
        raise HTTPException(status_code=409, detail="重力补偿已在运行")

    try:
        await b601_runtime_lock.acquire(RuntimeMode.GRAVITY_COMP, "gravity-comp")
    except RuntimeLockBusy as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc

    from dependencies import b601_kinematics as kin

    h = kin.probe_health()
    if not h.get("pinocchio"):
        await b601_runtime_lock.release(RuntimeMode.GRAVITY_COMP)
        raise HTTPException(
            status_code=503,
            detail="请先运行 scripts/b601_pinocchio_install.sh 安装 Pinocchio SDK",
        )

    runner = _REPO_ROOT / "scripts" / "b601_gravity_comp_runner.py"
    if not runner.is_file():
        await b601_runtime_lock.release(RuntimeMode.GRAVITY_COMP)
        raise HTTPException(status_code=503, detail="gravity comp runner 缺失")

    gains_json = json.dumps({str(k): v for k, v in body.joint_gains.items()})
    cmd = [
        _runner_python(),
        str(runner),
        "--mode",
        body.mode,
        "--gains-json",
        gains_json,
        "--can",
        body.can_iface or DEFAULT_CAN,
        "--state-port",
        str(_STATE_PORT),
    ]
    _gc_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    _gc_mode = body.mode
    _last_state = {}
    await asyncio.sleep(0.5)
    if _gc_proc.poll() is not None:
        out = (_gc_proc.stdout.read() if _gc_proc.stdout else "") or ""
        _gc_proc = None
        _gc_mode = None
        await b601_runtime_lock.release(RuntimeMode.GRAVITY_COMP)
        raise HTTPException(status_code=500, detail=out[-400:] or "重力补偿启动失败")
    return {"ok": True, "running": True, "mode": body.mode}


async def stop_gravity_comp_if_running(can_iface: str = DEFAULT_CAN) -> bool:
    """Stop gravity-comp process and release runtime lock (for teleop handoff)."""
    global _gc_proc, _gc_mode, _last_state

    proc = _gc_proc
    if not proc or proc.poll() is not None:
        if b601_runtime_lock.mode == RuntimeMode.GRAVITY_COMP:
            await b601_runtime_lock.release(RuntimeMode.GRAVITY_COMP)
        return False

    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        except Exception:
            proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, 8)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    _gc_proc = None
    _gc_mode = None
    await b601_runtime_lock.release(RuntimeMode.GRAVITY_COMP)
    return True


@router.post("/stop")
async def gravity_comp_stop(can_iface: str = DEFAULT_CAN) -> Dict[str, Any]:
    global _gc_proc, _gc_mode, _last_state

    stopped = await stop_gravity_comp_if_running(can_iface)
    return {"ok": True, "stopped": True, "message": "已停止重力补偿并卸力"}


@router.websocket("/ws/state")
async def ws_gravity_comp_state(websocket: WebSocket) -> None:
    global _last_state
    await websocket.accept()
    try:
        while True:
            running = _gc_proc is not None and _gc_proc.poll() is None
            state = _read_gc_state() if running else _last_state
            await websocket.send_json(
                {
                    "running": running,
                    "mode": _gc_mode,
                    "state": state,
                    "timestamp": time.time(),
                }
            )
            if not running:
                await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(0.016)
    except WebSocketDisconnect:
        pass
