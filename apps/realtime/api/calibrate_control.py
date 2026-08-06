"""Calibration endpoints for SO-101.

This module provides three layers:
1) Auto calibration process control (`/api/calibrate/auto/*`)
2) Manual calibration minimal WS flow (`/api/calibrate/manual/ws`)
3) Calibration governance (`/api/calibrate/files|status|missing`)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ._cli_process import CLIProcess
from .port_lock import PortInUseError, port_lock_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calibrate", tags=["calibration"])

CALIB_ROOT = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"
SO101_MOTOR_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]
SO101_MOTOR_IDS = {name: i + 1 for i, name in enumerate(SO101_MOTOR_NAMES)}


class AutoCalStartRequest(BaseModel):
    port: str = Field(..., description="Serial port, e.g. /dev/ttyACM1")
    robot_id: str = Field("single_follower", description="Calibration id to save")


class AutoCalStatus(BaseModel):
    running: bool
    session_id: Optional[str] = None
    pid: Optional[int] = None
    returncode: Optional[int] = None
    started_at: Optional[float] = None
    port: Optional[str] = None
    robot_id: Optional[str] = None
    synced_to_so101: bool = False
    log_tail: list[str] = Field(default_factory=list)
    last_error: Optional[str] = None


class AutoCalIdsResponse(BaseModel):
    follower_so101_ids: list[str] = Field(default_factory=list)
    follower_so_ids: list[str] = Field(default_factory=list)
    leader_so101_ids: list[str] = Field(default_factory=list)


class DependencyStatus(BaseModel):
    name: str
    ok: bool
    error: Optional[str] = None


class CalibrationFileListResponse(BaseModel):
    category: str
    robot_type: str
    ids: list[str] = Field(default_factory=list)


class CalibrationDeviceStatus(BaseModel):
    device_type: str
    robot_type: str
    expected_id: Optional[str] = None
    exists: bool
    file_path: Optional[str] = None
    available_ids: list[str] = Field(default_factory=list)
    missing_reason: Optional[str] = None


class CalibrationStatusResponse(BaseModel):
    devices: list[CalibrationDeviceStatus] = Field(default_factory=list)


class _AutoCalCLI(CLIProcess):
    role = "lerobot-auto-calibrate"

    def __init__(self, *, port: str, robot_id: str) -> None:
        super().__init__(log_tail_lines=200)
        self.port = port
        self.robot_id = robot_id
        self.synced_to_so101 = False

    def build_cmd(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "lerobot.scripts.lerobot_auto_calibrate_feetech",
            "--port",
            self.port,
            "--save",
            "--robot-id",
            self.robot_id,
        ]

    def build_env(self) -> dict:
        env = super().build_env()
        lerobot_src = env.get("BOTVERSEX_LEROBOT_PATH")
        if lerobot_src and os.path.isdir(lerobot_src):
            old_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{lerobot_src}:{old_pp}" if old_pp else lerobot_src
        return env


_session: Optional[_AutoCalCLI] = None
_held_ports: list[str] = []
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _sync_so_follower_to_so101(robot_id: str) -> bool:
    src = CALIB_ROOT / "robots" / "so_follower" / f"{robot_id}.json"
    dst = CALIB_ROOT / "robots" / "so101_follower" / f"{robot_id}.json"
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


async def _reap_if_dead() -> None:
    global _session, _held_ports
    if _session is None or _session.is_alive():
        return
    if _session.returncode == 0 and not _session.synced_to_so101:
        _session.synced_to_so101 = _sync_so_follower_to_so101(_session.robot_id)
    if _held_ports:
        await port_lock_manager.release(_held_ports)
        _held_ports = []


def _snapshot() -> AutoCalStatus:
    if _session is None:
        return AutoCalStatus(running=False)
    return AutoCalStatus(
        running=_session.is_alive(),
        session_id=_session.session_id,
        pid=_session.pid,
        returncode=_session.returncode,
        started_at=_session.started_at,
        port=_session.port,
        robot_id=_session.robot_id,
        synced_to_so101=_session.synced_to_so101,
        log_tail=_session.log_tail,
        last_error=_session.last_error,
    )


def _list_ids(subdir: Path) -> list[str]:
    if not subdir.is_dir():
        return []
    return sorted(p.stem for p in subdir.glob("*.json"))


def _list_ids_by(category: str, robot_type: str) -> list[str]:
    return _list_ids(CALIB_ROOT / category / robot_type)


def _check_auto_dependencies() -> list[DependencyStatus]:
    checks: list[DependencyStatus] = []
    for dep in ("draccus",):
        try:
            __import__(dep)
            checks.append(DependencyStatus(name=dep, ok=True))
        except Exception as exc:  # pragma: no cover - env dependent
            checks.append(DependencyStatus(name=dep, ok=False, error=str(exc)))
    return checks


def _calibration_path(device_type: str, device_id: str) -> Path:
    if device_type == "follower":
        return CALIB_ROOT / "robots" / "so101_follower" / f"{device_id}.json"
    if device_type == "leader":
        return CALIB_ROOT / "teleoperators" / "so101_leader" / f"{device_id}.json"
    raise ValueError(f"invalid device_type={device_type!r}")


def _resolve_device_id(device_type: str) -> Optional[str]:
    env_key = "BOTVERSEX_FOLLOWER_DEVICE_ID" if device_type == "follower" else "BOTVERSEX_LEADER_DEVICE_ID"
    env = os.environ.get(env_key)
    if env:
        return env
    if device_type == "follower":
        folder = CALIB_ROOT / "robots" / "so101_follower"
    elif device_type == "leader":
        folder = CALIB_ROOT / "teleoperators" / "so101_leader"
    else:
        return None
    if not folder.is_dir():
        return None
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    return files[0].stem


def _build_device_status(device_type: str) -> CalibrationDeviceStatus:
    if device_type == "follower":
        robot_type = "so101_follower"
        category = "robots"
    elif device_type == "leader":
        robot_type = "so101_leader"
        category = "teleoperators"
    else:
        raise ValueError(f"invalid device_type={device_type!r}")

    ids = _list_ids_by(category, robot_type)
    expected_id = _resolve_device_id(device_type)
    if not expected_id:
        return CalibrationDeviceStatus(
            device_type=device_type,
            robot_type=robot_type,
            exists=False,
            available_ids=ids,
            missing_reason="no_calibration_id_selected",
        )

    p = _calibration_path(device_type, expected_id)
    exists = p.is_file()
    return CalibrationDeviceStatus(
        device_type=device_type,
        robot_type=robot_type,
        expected_id=expected_id,
        exists=exists,
        file_path=str(p),
        available_ids=ids,
        missing_reason=None if exists else "calibration_file_not_found",
    )


@router.post("/auto/start", response_model=AutoCalStatus)
async def start_auto_calibration(req: AutoCalStartRequest) -> AutoCalStatus:
    global _session, _held_ports
    async with _get_lock():
        await _reap_if_dead()
        if _session and _session.is_alive():
            raise HTTPException(
                status_code=409,
                detail={"code": "auto_calibration_running", "message": "Auto calibration already running."},
            )

        checks = _check_auto_dependencies()
        missing = [x for x in checks if not x.ok]
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "missing_dependency",
                    "message": "Auto calibration runtime dependency is missing.",
                    "missing": [x.name for x in missing],
                    "checks": [x.model_dump() for x in checks],
                    "fix_hint": (
                        "source apps/realtime/.venv/bin/activate && "
                        "pip install -r apps/realtime/requirements.txt"
                    ),
                },
            )

        sess = _AutoCalCLI(port=req.port, robot_id=req.robot_id)
        try:
            await port_lock_manager.acquire([req.port], owner="auto_calibration", mode="subprocess")
        except PortInUseError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "port_in_use", "message": str(exc), "port": exc.port, "owner": exc.owner},
            ) from exc

        try:
            await asyncio.to_thread(sess.start, 10.0)
        except Exception as exc:
            await port_lock_manager.release([req.port])
            raise HTTPException(status_code=500, detail=f"auto calibration start failed: {exc}") from exc

        _session = sess
        _held_ports = [req.port]
        await port_lock_manager.register_process(sess.session_id, [req.port])
        return _snapshot()


@router.get("/auto/ids", response_model=AutoCalIdsResponse)
async def list_calibration_ids() -> AutoCalIdsResponse:
    return AutoCalIdsResponse(
        follower_so101_ids=_list_ids(CALIB_ROOT / "robots" / "so101_follower"),
        follower_so_ids=_list_ids(CALIB_ROOT / "robots" / "so_follower"),
        leader_so101_ids=_list_ids(CALIB_ROOT / "teleoperators" / "so101_leader"),
    )


@router.get("/auto/status", response_model=AutoCalStatus)
async def get_auto_calibration_status() -> AutoCalStatus:
    async with _get_lock():
        await _reap_if_dead()
        return _snapshot()


@router.post("/auto/stop", response_model=AutoCalStatus)
async def stop_auto_calibration() -> AutoCalStatus:
    global _session, _held_ports
    async with _get_lock():
        if _session is None:
            return AutoCalStatus(running=False)
        await asyncio.to_thread(_session.stop, 6.0)
        await asyncio.sleep(0.3)
        if _held_ports:
            await port_lock_manager.release(_held_ports)
            _held_ports = []
        return _snapshot()


@router.get("/files", response_model=CalibrationFileListResponse)
async def list_calibration_files(category: str, robot_type: str) -> CalibrationFileListResponse:
    if category not in {"robots", "teleoperators"}:
        raise HTTPException(status_code=400, detail="category must be robots or teleoperators")
    return CalibrationFileListResponse(
        category=category,
        robot_type=robot_type,
        ids=_list_ids_by(category, robot_type),
    )


@router.get("/status", response_model=CalibrationStatusResponse)
async def get_calibration_status() -> CalibrationStatusResponse:
    return CalibrationStatusResponse(devices=[_build_device_status("follower"), _build_device_status("leader")])


@router.get("/missing", response_model=CalibrationStatusResponse)
async def get_missing_calibrations() -> CalibrationStatusResponse:
    all_status = await get_calibration_status()
    return CalibrationStatusResponse(devices=[d for d in all_status.devices if not d.exists])


@router.websocket("/manual/ws")
async def manual_calibration_ws(websocket: WebSocket) -> None:
    """Manual calibration minimal WS flow."""
    await websocket.accept()

    bus = None
    port: Optional[str] = None
    locked = False
    device_type = "follower"
    device_id: Optional[str] = None
    recording = False
    homing_offsets: Optional[dict[str, int]] = None
    mins: dict[str, int] = {}
    maxes: dict[str, int] = {}

    try:
        while True:
            if recording and bus is not None:
                try:
                    msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.12)
                except asyncio.TimeoutError:
                    positions = await asyncio.to_thread(
                        bus.sync_read, "Present_Position", list(bus.motors.keys()), False
                    )
                    for motor, pos in positions.items():
                        mins[motor] = min(pos, mins.get(motor, pos))
                        maxes[motor] = max(pos, maxes.get(motor, pos))
                    await websocket.send_json(
                        {
                            "type": "positions",
                            "motors": {
                                m: {"pos": positions[m], "min": mins[m], "max": maxes[m]}
                                for m in positions
                            },
                        }
                    )
                    continue
            else:
                msg = await websocket.receive_json()

            action = str(msg.get("action", "")).strip().lower()

            if action == "start":
                if bus is not None:
                    await websocket.send_json({"type": "error", "message": "session_already_started"})
                    continue
                port = str(msg.get("port") or "").strip()
                device_type = str(msg.get("device_type") or "follower").strip().lower()
                device_id = str(msg.get("device_id") or "").strip() or None
                if device_type not in {"follower", "leader"}:
                    await websocket.send_json({"type": "error", "message": "device_type must be follower or leader"})
                    continue
                if not port:
                    await websocket.send_json({"type": "error", "message": "port is required"})
                    continue

                try:
                    await port_lock_manager.acquire([port], owner="manual_calibration", mode="direct")
                    locked = True
                except PortInUseError as exc:
                    await websocket.send_json(
                        {"type": "error", "message": str(exc), "code": "port_in_use", "owner": exc.owner}
                    )
                    continue

                try:
                    from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode
                    from sender.lerobot_calibration import build_motors_dict

                    bus = await asyncio.to_thread(FeetechMotorsBus, port, build_motors_dict())
                    await asyncio.to_thread(bus.connect)
                    await asyncio.to_thread(bus.disable_torque)
                    for name in SO101_MOTOR_NAMES:
                        await asyncio.to_thread(bus.write, "Operating_Mode", name, OperatingMode.POSITION.value)
                except Exception as exc:
                    if locked and port:
                        await port_lock_manager.release([port])
                        locked = False
                    bus = None
                    await websocket.send_json({"type": "error", "message": f"manual_start_failed: {exc}"})
                    continue
                await websocket.send_json({"type": "connected", "motors": list(SO101_MOTOR_NAMES)})

            elif action == "set_homing":
                if bus is None:
                    await websocket.send_json({"type": "error", "message": "not_connected"})
                    continue
                homing_offsets = await asyncio.to_thread(bus.set_half_turn_homings)
                await websocket.send_json({"type": "homing_done", "offsets": homing_offsets})

            elif action == "start_recording":
                if bus is None:
                    await websocket.send_json({"type": "error", "message": "not_connected"})
                    continue
                positions = await asyncio.to_thread(bus.sync_read, "Present_Position", list(bus.motors.keys()), False)
                mins = dict(positions)
                maxes = dict(positions)
                recording = True
                await websocket.send_json({"type": "recording_started"})

            elif action == "stop_recording":
                recording = False
                await websocket.send_json({"type": "recording_done", "mins": mins, "maxes": maxes})

            elif action == "save":
                if not mins or not maxes:
                    await websocket.send_json({"type": "error", "message": "no_recording_data"})
                    continue
                if homing_offsets is None:
                    await websocket.send_json({"type": "error", "message": "set_homing_required"})
                    continue
                if not device_id:
                    device_id = "single_follower" if device_type == "follower" else "single_leader"

                payload = {}
                for motor in SO101_MOTOR_NAMES:
                    payload[motor] = {
                        "id": SO101_MOTOR_IDS[motor],
                        "drive_mode": 0,
                        "homing_offset": int(homing_offsets[motor]),
                        "range_min": int(mins[motor]),
                        "range_max": int(maxes[motor]),
                    }

                path = _calibration_path(device_type, device_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=4), encoding="utf-8")

                if bus is not None:
                    try:
                        from lerobot.motors import MotorCalibration

                        cal_dict = {
                            k: MotorCalibration(
                                id=v["id"],
                                drive_mode=v["drive_mode"],
                                homing_offset=v["homing_offset"],
                                range_min=v["range_min"],
                                range_max=v["range_max"],
                            )
                            for k, v in payload.items()
                        }
                        await asyncio.to_thread(bus.write_calibration, cal_dict)
                    except Exception as exc:
                        logger.warning("manual save wrote file but failed bus EEPROM write: %s", exc)

                await websocket.send_json({"type": "saved", "path": str(path), "device_id": device_id})

            elif action == "disconnect":
                break
            else:
                await websocket.send_json({"type": "error", "message": f"unknown_action: {action}"})

    except WebSocketDisconnect:
        pass
    finally:
        if bus is not None:
            try:
                await asyncio.to_thread(bus.disable_torque)
            except Exception:
                pass
            try:
                await asyncio.to_thread(bus.disconnect)
            except Exception:
                pass
        if locked and port:
            await port_lock_manager.release([port])
