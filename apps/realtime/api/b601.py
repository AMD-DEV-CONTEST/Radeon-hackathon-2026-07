"""B601 Local Agent API — thin wrapper around official LeRobot + MotorBridge CLI.

Supports both B601-RS (RobStride over SocketCAN/PCAN) and B601-DM (Damiao over
USB-CAN serial bridge). Adds setup, motor recovery, and gateway lifecycle so the
web UI stays one-click.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from runtime_lock import RuntimeLockBusy, RuntimeMode, b601_runtime_lock
from ._cli_process import CLIProcess, resolve_cli_argv
from .port_lock import port_lock_manager, PortInUseError
from .remote_compute import (
    get_node,
    resolve_model_path,
    resolve_remote_dir,
    resolve_sidecar_url,
    resolve_ssh_jump,
    resolve_ssh_target,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/b601", tags=["b601"])

DEFAULT_CAN = os.environ.get("BOTVERSEX_B601_CAN", "can0")
DEFAULT_DM_PORT = os.environ.get("BOTVERSEX_B601_DM_PORT", "/dev/ttyACM2")
DEFAULT_ARM_VARIANT = os.environ.get("BOTVERSEX_B601_VARIANT", "auto").strip().lower()
DEFAULT_LEADER = os.environ.get("BOTVERSEX_B601_LEADER", "/dev/leader_stararm102")
FALLBACK_LEADER = "/dev/ttyUSB0"
ROBOT_ID = os.environ.get("BOTVERSEX_B601_ROBOT_ID", "follower1")
LEADER_ID = os.environ.get("BOTVERSEX_B601_LEADER_ID", "rebot_arm_102_leader")
CAN_BITRATE = 1_000_000
DM_SERIAL_BAUD = int(os.environ.get("BOTVERSEX_B601_DM_BAUD", "921600"))
# LeRobot teleoperate loop rate. 60 is upstream default; 100 feels more responsive for DM.
DEFAULT_TELEOP_FPS = int(os.environ.get("BOTVERSEX_B601_TELEOP_FPS", "100"))
TELEOP_FPS_MIN = 30
TELEOP_FPS_MAX = 200

_MOTOR_MODELS: Dict[int, str] = {1: "rs-06", 2: "rs-06", 3: "rs-06", 4: "rs-00", 5: "rs-00", 6: "rs-00", 7: "rs-00"}
_DM_MOTOR_MODELS: Dict[int, str] = {1: "4340P", 2: "4340P", 3: "4340P", 4: "4310", 5: "4310", 6: "4310", 7: "4310"}

# Last per-ID ping snapshot (used when teleop owns CAN — never fabricate 7/7).
_last_motor_scan: List[MotorScanItem] = []
_last_motor_scan_ts: float = 0.0

# Minimum online motors to allow teleop (demo: arm can move even if gripper etc. offline).
B601_MIN_MOTORS_TELEOP = int(os.environ.get("BOTVERSEX_B601_MIN_MOTORS", "4"))

# URDF joint names (joint1..joint7) ↔ lerobot semantic names
_B601_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
    "gripper",
]
_MOTOR_TO_URDF = {i + 1: f"joint{i + 1}" for i in range(7)}
_URDF_TO_SEMANTIC = {f"joint{i + 1}": name for i, name in enumerate(_B601_JOINT_NAMES)}

# Per-joint alignment tolerance before teleop (degrees). SO-101 uses ~15% normalized ≈ ~15–20°.
B601_ALIGN_TOLERANCE_DEG = float(os.environ.get("BOTVERSEX_B601_ALIGN_TOL_DEG", "18"))

B601_JOINT_LABELS_ZH: Dict[str, str] = {
    "shoulder_pan": "底座旋转",
    "shoulder_lift": "大臂",
    "elbow_flex": "小臂",
    "wrist_flex": "腕部1",
    "wrist_yaw": "腕部2",
    "wrist_roll": "腕部3",
    "gripper": "夹爪",
}

FOLLOWER_CALIB_TYPE_RS = "seeed_b601_rs_follower"
FOLLOWER_CALIB_TYPE_DM = "seeed_b601_dm_follower"
LEADER_CALIB_TYPE = "rebot_arm_102_leader"
_PREFS_DIR = Path.home() / ".cache" / "botversex"
_PREFS_FILE = _PREFS_DIR / "b601_prefs.json"

_POS_RE = re.compile(r"pos=([+-]?\d+(?:\.\d+)?)")
# LeRobot: ``Recording episode N`` — N is 0-based. UI shows 1-based「第几条」.
_RECORDING_EPISODE_LINE_RE = re.compile(r"Recording episode\s+(\d+)\b", re.I)
_RECORD_EPISODE_SLASH_RE = re.compile(
    r"\bepisode\s+(\d+)\s*/\s*(\d+)\b",
    re.I,
)

_URDF_ROOT = Path(__file__).parent.parent / "static" / "urdf" / "b601_rs"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MotorScanItem(BaseModel):
    motor_id: int
    model: str
    online: bool
    faulted: bool = False
    label: str = ""


class MotorDiagnoseResponse(BaseModel):
    """Per-ID ping (read-only) — same idea as Seeed getting-started + b601-hw-diagnose.sh."""

    ok: bool
    can_iface: str
    can_up: bool
    motors: List[MotorScanItem]
    motors_online: int
    motors_total: int = 7
    message: str
    issues: List[str] = []
    read_only: bool = True


class HealthResponse(BaseModel):
    ok: bool
    """Hardware link detected (CAN + leader + follower motors). Not the same as calibrated."""
    ready_for_teleop: bool = False
    """Official lerobot-teleoperate ready: hardware + follower/leader calibration files."""
    arm_variant: str = "rs"
    follower_type: str = FOLLOWER_CALIB_TYPE_RS
    follower_transport: str = "socketcan"
    follower_port: str = DEFAULT_CAN
    can_up: bool
    can_iface: str
    can_present: bool = False
    leader_present: bool
    leader_port: str
    motors_online: int
    motors_total: int = 7
    motors: List[MotorScanItem] = []
    motors_scan_stale: bool = False
    calibration_follower: bool
    calibration_leader: bool
    robot_id: str = ROBOT_ID
    leader_id: str = LEADER_ID
    motorbridge_cli: bool
    lerobot_teleoperate: bool
    gateway_running: bool
    cameras_available: int = 0
    power_hint: str | None = None
    issues: List[str] = []


class CanUpResponse(BaseModel):
    ok: bool
    message: str
    iface: str


class RecoverResponse(BaseModel):
    ok: bool
    message: str
    motors_enabled: int


class TeleopStartRequest(BaseModel):
    leader_port: Optional[str] = None
    can_iface: Optional[str] = None
    follower_port: Optional[str] = None
    arm_variant: Optional[str] = None
    robot_id: Optional[str] = None
    leader_id: Optional[str] = None
    display_data: bool = False
    use_cameras: bool = False
    camera_indices: List[int] = Field(default_factory=lambda: [4, 6])
    fps: Optional[int] = Field(default=None, ge=TELEOP_FPS_MIN, le=TELEOP_FPS_MAX)
    restart: bool = True
    force: bool = False
    check_alignment: bool = False


class RecordStartRequest(BaseModel):
    leader_port: Optional[str] = None
    can_iface: Optional[str] = None
    follower_port: Optional[str] = None
    arm_variant: Optional[str] = None
    robot_id: Optional[str] = None
    leader_id: Optional[str] = None
    # HF/LeRobot style: exactly one slash → ~/.cache/huggingface/lerobot/<owner>/<name>/
    repo_id: str = Field(..., description="LeRobot dataset id, e.g. local/b601-dm-demo01")
    single_task: str = "Pick and place the object"
    num_episodes: int = Field(5, ge=1, le=200)
    episode_time_s: int = Field(30, ge=5, le=600)
    reset_time_s: int = Field(30, ge=0, le=120)
    camera_indices: List[int] = Field(default_factory=lambda: [4, 6])

    @field_validator("repo_id")
    @classmethod
    def _repo_id_hf_style(cls, v: str) -> str:
        rid = (v or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", rid):
            raise ValueError(
                "repo_id 必须是 LeRobot/HF 风格 owner/name（两段、一个斜杠），"
                "例如 local/b601-dm-pick01；不要用 local/b601/xxx 三段路径"
            )
        return rid


class InferenceStartRequest(BaseModel):
    policy_path: str = ""
    leader_port: Optional[str] = None
    can_iface: Optional[str] = None
    follower_port: Optional[str] = None
    arm_variant: Optional[str] = None
    robot_id: Optional[str] = None
    leader_id: Optional[str] = None
    single_task: str = "冰球游戏，将对方击过来的红色圆盘击回去"
    episode_time_s: int = 60
    # Laptop dual-cam (front+side). Indices renumber after replug — UI should pass explicit prefs.
    camera_indices: List[int] = Field(default_factory=lambda: [4, 6])
    # remote = laptop cams/joints → LAN → remote sidecar → actions (recommended)
    # local = lerobot-record --policy.path on this machine (heavy; may OOM)
    backend: str = "remote"
    sidecar_url: Optional[str] = None
    node_id: Optional[str] = None


class SidecarLoadRequest(BaseModel):
    model_key: str = Field(..., min_length=1, description="Remote path or HF model id")
    task_prompt: str = "冰球游戏，将对方击过来的红色圆盘击回去"
    sidecar_url: Optional[str] = None
    node_id: Optional[str] = None
    prefer_device: str = "cuda"


class SidecarSyncRequest(BaseModel):
    """Pull Qualia/HF model to a remote compute node and optionally hot-load sidecar.

    node_id selects a configured RemoteComputeNode (see /api/remote_compute/nodes).
    If omitted, the default node is used. For backward compatibility, callers may
    still pass remote_dir / sidecar_url explicitly to override node settings.
    """
    model_id: Optional[str] = None
    job_id: Optional[str] = None
    node_id: Optional[str] = None
    remote_dir: Optional[str] = None
    sidecar_url: Optional[str] = None
    load: bool = True
    task_prompt: str = "冰球游戏，将对方击过来的红色圆盘击回去"


class SessionStatus(BaseModel):
    running: bool
    role: str
    healthy: bool = True
    starting: bool = False
    last_error: Optional[str] = None
    session_id: Optional[str] = None
    pid: Optional[int] = None
    started_at: Optional[float] = None
    uptime_s: Optional[float] = None
    log_tail: List[str] = []
    episode_current: Optional[int] = None
    episode_total: Optional[int] = None
    calibrate_target: Optional[str] = None
    robot_id: Optional[str] = None
    leader_id: Optional[str] = None
    follower_cal_path: Optional[str] = None
    leader_cal_path: Optional[str] = None
    returncode: Optional[int] = None
    repo_id: Optional[str] = None
    dataset_dir: Optional[str] = None
    # recording | resetting | saving | starting | done | error | idle
    record_phase: Optional[str] = None
    phase_hint: Optional[str] = None
    episode_time_s: Optional[int] = None
    reset_time_s: Optional[int] = None
    phase_elapsed_s: Optional[float] = None


class TeleopPreflightResponse(BaseModel):
    ok: bool
    robot_id: str
    leader_id: str
    follower_cal_path: Optional[str] = None
    leader_cal_path: Optional[str] = None
    calibration_follower: bool = False
    calibration_leader: bool = False
    follower_joints: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class B601AlignMismatch(BaseModel):
    motor: str
    label: str
    delta_deg: float
    leader_deg: float
    follower_deg: float
    hint: str


class B601AlignmentResponse(BaseModel):
    ok: bool
    tolerance_deg: float
    skipped: bool = False
    skip_reason: Optional[str] = None
    mismatches: List[B601AlignMismatch] = Field(default_factory=list)
    robot_id: str = ""
    leader_id: str = ""


class CalibrateStartRequest(BaseModel):
    target: str = Field(..., description="follower or leader")
    leader_port: Optional[str] = None
    can_iface: Optional[str] = None
    follower_port: Optional[str] = None
    arm_variant: Optional[str] = None
    robot_id: Optional[str] = None
    leader_id: Optional[str] = None


class JointsResponse(BaseModel):
    ok: bool
    teleop_running: bool
    joints: Dict[str, float] = {}
    units: str = "rad"


class UrdfHealthResponse(BaseModel):
    ok: bool
    mesh_total: int
    mesh_present: int
    missing: List[str] = []


class CameraDevice(BaseModel):
    index: int
    path: str
    name: Optional[str] = None
    readable: bool = False
    busy: bool = False
    usb_bus: Optional[str] = None


class GatewayStatus(BaseModel):
    running: bool
    pid: Optional[int] = None


class CalibrationStatus(BaseModel):
    follower: bool
    leader: bool
    arm_variant: str = "rs"
    follower_type: str = FOLLOWER_CALIB_TYPE_RS
    follower_path: Optional[str] = None
    leader_path: Optional[str] = None
    robot_id: str = ROBOT_ID
    leader_id: str = LEADER_ID
    follower_ids: List[str] = Field(default_factory=list)
    leader_ids: List[str] = Field(default_factory=list)


class B601ConfigResponse(BaseModel):
    arm_variant: str
    follower_port: str
    follower_type: str
    follower_transport: str
    robot_id: str
    leader_id: str
    follower_ids: List[str] = Field(default_factory=list)
    leader_ids: List[str] = Field(default_factory=list)
    calibration_follower: bool = False
    calibration_leader: bool = False


class B601ConfigUpdate(BaseModel):
    arm_variant: Optional[str] = None
    follower_port: Optional[str] = None
    robot_id: Optional[str] = None
    leader_id: Optional[str] = None


class CalibrationDeleteRequest(BaseModel):
    side: str = Field(..., description="follower or leader")
    cal_id: str = Field(..., description="calibration file stem without .json")


# ---------------------------------------------------------------------------
# Session holders
# ---------------------------------------------------------------------------


_teleop_proc: Optional[CLIProcess] = None
_teleop_start_task: Optional[asyncio.Task] = None
_teleop_start_error: Optional[str] = None
_record_proc: Optional[CLIProcess] = None
_record_phase_started_at: Optional[float] = None
_record_phase_last: Optional[str] = None
# Sticky 1-based episode for UI — SVT encode logs flood the tail and would
# otherwise wipe episode_current to null → coach shows「— / 10」.
_record_episode_sticky: Optional[int] = None
_inference_proc: Optional[CLIProcess] = None
_remote_infer_proc: Optional[subprocess.Popen] = None
_remote_infer_started_at: Optional[float] = None
_calibrate_proc: Optional[CLIProcess] = None
_calibrate_target: Optional[str] = None
_dataset_viz_proc: Optional[CLIProcess] = None
_gateway_proc: Optional[subprocess.Popen] = None
_b601_can_lock = asyncio.Lock()


def _require_runtime_idle(requested: RuntimeMode) -> None:
    if b601_runtime_lock.is_busy() and b601_runtime_lock.mode != requested:
        raise HTTPException(
            status_code=409,
            detail=b601_runtime_lock.conflict_message(requested),
        )


@asynccontextmanager
async def _b601_can_exclusive():
    """Serialize motorbridge access — wait for prior op instead of instant 503."""
    await _b601_can_lock.acquire()
    try:
        await asyncio.to_thread(_kill_gateway)
        await asyncio.sleep(0.12)
        yield
    finally:
        _b601_can_lock.release()


def _parse_record_episode(tail: List[str]) -> tuple[Optional[int], Optional[int]]:
    """Return (current_1based, total) for the UI「当前条数」.

    Always means the episode being recorded / just finished / being saved —
    never the *next* one.
    """
    current: Optional[int] = None
    total: Optional[int] = None
    for line in reversed(tail):
        m_rec = _RECORDING_EPISODE_LINE_RE.search(line)
        if m_rec:
            # 0-based log → 1-based「第 N 条」
            current = int(m_rec.group(1)) + 1
            break
        m_slash = _RECORD_EPISODE_SLASH_RE.search(line)
        if m_slash:
            # Already "N/M" human form if present
            current = int(m_slash.group(1))
            total = int(m_slash.group(2))
            break
    return current, total


def _parse_record_phase(
    tail: List[str],
    *,
    alive: bool,
    returncode: Optional[int],
    ep_cur: Optional[int],
    ep_total: Optional[int],
) -> tuple[str, str]:
    """Return (phase, Chinese hint) for the record UI banner.

    Important: use the *most recent* high-signal marker. Do **not** treat
    ``Svt[info]`` alone as「保存中」— with ``streaming_encoding=true`` the
    encoder prints those lines as soon as episode 0 starts, which falsely
    looks like "already saving episode 1" before the user has taught anything.
    """
    if not alive:
        if returncode == 0:
            return (
                "done",
                f"采集完成（共 {ep_cur or ep_total or '?'} 条）。可预览视频或去训练页。",
            )
        if returncode is not None:
            return "error", "录制异常结束 — 请看下方日志；修完后可重新开始采集。"
        return "idle", "尚未开始采集。"

    # Scan newest → oldest for semantic markers only (ignore encoder chatter).
    kind: Optional[str] = None
    for line in reversed(list(tail)):
        low = line.lower()
        if "stop recording" in low or re.search(r"\bexiting\b", low):
            kind = "stop"
            break
        if "re-record episode" in low or "rerecord" in low:
            kind = "rerecord"
            break
        if "reset the environment" in low:
            kind = "reset"
            break
        if re.search(r"recording episode\s+\d+", low):
            kind = "record"
            break
        # True between-episode / finalize encode — not streaming init banners.
        if (
            "save_episode" in low
            or "starting second pass" in low
            or re.search(r"\bmap:\s+\d+%", low)
            or "using video codec" in low
        ):
            # "Using video codec" also fires at streaming start — only count it
            # as saving if we already saw a reset after the latest record.
            # Handled below via kind == "encode_hint" + context.
            if "using video codec" in low:
                kind = "codec"
            else:
                kind = "save"
            break
        if "connecting" in low or "spawn:" in low:
            kind = "start"
            break

    ep = (
        f"第 {ep_cur}/{ep_total} 条"
        if ep_cur and ep_total
        else (f"第 {ep_cur} 条" if ep_cur else "示教中")
    )

    if kind == "stop":
        return "saving", "收尾中：正在停止并写盘，请稍等…"
    if kind == "rerecord":
        return "recording", "重录本条：上一条已丢弃，请重新示范。"
    if kind == "reset":
        return (
            "resetting",
            "复位：把场景摆回起点。摆好可点「复位完成·下一条」或按 →，不必等满倒计时。",
        )
    if kind == "record":
        return (
            "recording",
            f"正在录 · {ep}：用主臂完整示范（编码在后台跑，不是在「保存」）。提前结束 →；重录 ←。",
        )
    if kind == "save":
        if ep_cur and ep_total:
            nxt = (
                f"保存完进入第 {ep_cur + 1} 条"
                if ep_cur < ep_total
                else "保存完即全部完成"
            )
            return (
                "saving",
                f"正在保存第 {ep_cur}/{ep_total} 条（刚录完的这一条）· {nxt}。请勿拔线。",
            )
        if ep_cur:
            return "saving", f"正在保存第 {ep_cur} 条（刚录完的这一条）。请勿拔线。"
        return "saving", "保存中：正在写视频/parquet；请勿拔线。"
    if kind == "codec":
        # Streaming encoder init right after "Recording episode N" — still recording.
        if ep_cur:
            return (
                "recording",
                f"正在录 · {ep}：编码器已启动（后台），请开始用主臂示范。",
            )
        return "starting", "请准备：编码器启动中，马上开录…"
    if kind == "start":
        return "starting", "请准备：正在连接主臂/从臂/相机…"

    # Default while alive: recording (don't invent「保存中」from silence / FPS warnings).
    if ep_cur:
        return "recording", f"正在录 · {ep}：看教练板倒计时，用主臂示范。"
    return "recording", "采集运行中：看上方教练板；复位时可点「下一条」。"


def _resolve_motorbridge_python() -> Optional[str]:
    """Python with motorbridge SDK (for follower joint probe)."""
    for bin_dir in _venv_bin_dirs():
        py = _python_in_bin(bin_dir)
        if py is None:
            continue
        try:
            subprocess.run(
                [str(py), "-c", "import motorbridge"],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return str(py)
        except (subprocess.SubprocessError, OSError):
            continue
    return None


async def poll_follower_joints(can: str = DEFAULT_CAN) -> Dict[str, float]:
    """Read all 7 follower joints; keys are URDF names (joint1..joint7)."""
    if not _can_is_up(can):
        return {}
    if _teleop_proc and _teleop_proc.is_alive():
        return {}

    async with _b601_can_exclusive():
        return await _poll_follower_joints_unlocked(can)


async def _poll_follower_joints_unlocked(can: str) -> Dict[str, float]:
    py = _resolve_motorbridge_python()
    if not py:
        logger.warning("follower joint read: no motorbridge python")
        return {}
    script = Path(__file__).with_name("b601_follower_probe.py")
    try:
        r = await _run_shell([py, str(script), "--channel", can], timeout=4)
        data = json.loads((r.stdout or "").strip() or "{}")
        if data.get("ok") and isinstance(data.get("joints_rad"), dict):
            out: Dict[str, float] = {}
            for key, val in data["joints_rad"].items():
                try:
                    pos = float(val)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(pos):
                    out[str(key)] = pos
            return out
    except Exception as exc:
        logger.warning("follower probe failed: %s", exc)
    return {}


def _resolve_lerobot_python() -> Optional[str]:
    """Python interpreter that has B601 leader/follower lerobot plugins."""
    probe = Path(__file__).with_name("b601_leader_probe.py")
    for bin_dir in _venv_bin_dirs():
        py = _python_in_bin(bin_dir)
        if py is None:
            continue
        try:
            subprocess.run(
                [str(py), "-c", "import motorbridge_smart_servo"],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return str(py)
        except (subprocess.SubprocessError, OSError):
            continue
    return None


def _venv_bin_dirs() -> List[Path]:
    from ._cli_process import _venv_bin_dirs as _bins

    return _bins()


def _python_in_bin(bin_dir: Path) -> Optional[Path]:
    from ._cli_process import _python_in_bin as _py

    return _py(bin_dir)


async def _read_leader_joints_deg(leader_port: str, leader_id: str) -> Dict[str, float]:
    py = _resolve_lerobot_python()
    if not py:
        return {}
    script = Path(__file__).with_name("b601_leader_probe.py")
    try:
        r = await _run_shell(
            [py, str(script), "--port", leader_port, "--id", leader_id],
            timeout=12,
        )
        data = json.loads((r.stdout or "").strip() or "{}")
        if data.get("ok") and isinstance(data.get("joints_deg"), dict):
            return {str(k): float(v) for k, v in data["joints_deg"].items()}
    except Exception as exc:
        logger.warning("leader joint read failed: %s", exc)
    return {}


async def _b601_alignment_report(
    *,
    can: str,
    leader_port: str,
    robot_id: str,
    leader_id: str,
) -> B601AlignmentResponse:
    """Compare leader vs follower joint angles (degrees) — same idea as SO-101 preflight."""
    cal = _calibration_status(robot_id=robot_id, leader_id=leader_id)
    if not cal.follower or not cal.leader:
        return B601AlignmentResponse(
            ok=False,
            tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
            skipped=True,
            skip_reason="标定文件缺失",
            robot_id=robot_id,
            leader_id=leader_id,
        )

    if _teleop_proc and _teleop_proc.is_alive():
        return B601AlignmentResponse(
            ok=True,
            tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
            skipped=True,
            skip_reason="遥操运行中，无法独占 CAN/串口做对齐检查",
            robot_id=robot_id,
            leader_id=leader_id,
        )

    if not _can_is_up(can):
        return B601AlignmentResponse(
            ok=False,
            tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
            skipped=True,
            skip_reason="CAN 未就绪 — 请先点「重新连接」（若提示 sudo，见下方终端命令）",
            robot_id=robot_id,
            leader_id=leader_id,
        )

    follower_rad, leader_deg = await asyncio.gather(
        poll_follower_joints(can),
        _read_leader_joints_deg(leader_port, leader_id),
    )

    if not follower_rad:
        return B601AlignmentResponse(
            ok=False,
            tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
            skipped=True,
            skip_reason="暂时读不到从臂角度（可选：先直接开始遥操，官方程序会自行连接从臂）",
            robot_id=robot_id,
            leader_id=leader_id,
        )
    if not leader_deg:
        return B601AlignmentResponse(
            ok=True,
            tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
            skipped=True,
            skip_reason="读不到主臂角度（USB 占用或未连接）",
            robot_id=robot_id,
            leader_id=leader_id,
        )

    mismatches: List[B601AlignMismatch] = []
    for jkey, semantic in _URDF_TO_SEMANTIC.items():
        f_rad = follower_rad.get(jkey)
        l_deg = leader_deg.get(semantic)
        if f_rad is None or l_deg is None:
            continue
        f_deg = math.degrees(f_rad)
        delta = l_deg - f_deg
        if abs(delta) <= B601_ALIGN_TOLERANCE_DEG:
            continue
        direction = "正向" if delta > 0 else "反向"
        mismatches.append(
            B601AlignMismatch(
                motor=semantic,
                label=B601_JOINT_LABELS_ZH.get(semantic, semantic),
                delta_deg=round(delta, 1),
                leader_deg=round(l_deg, 1),
                follower_deg=round(f_deg, 1),
                hint=f"请把主臂「{B601_JOINT_LABELS_ZH.get(semantic, semantic)}」向{direction}约 {abs(delta):.0f}°，靠近从臂",
            )
        )

    mismatches.sort(key=lambda m: abs(m.delta_deg), reverse=True)
    return B601AlignmentResponse(
        ok=not mismatches,
        tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
        skipped=False,
        mismatches=mismatches,
        robot_id=robot_id,
        leader_id=leader_id,
    )


def _resolve_leader(explicit: Optional[str] = None) -> str:
    """Resolve leader USB path; tolerate ttyUSB0↔ttyUSB1 renumber after unplug."""
    if explicit and Path(explicit).exists():
        return explicit
    candidates: List[str] = []
    for p in (DEFAULT_LEADER, FALLBACK_LEADER, "/dev/ttyUSB1", "/dev/ttyUSB2", "/dev/ttyUSB3"):
        if p and p not in candidates:
            candidates.append(p)
    # Prefer stable symlink / known names first, then any live ttyUSB*.
    for p in candidates:
        if Path(p).exists():
            return p
    try:
        usb = sorted(str(p) for p in Path("/dev").glob("ttyUSB*") if p.exists())
        if usb:
            return usb[0]
    except Exception:
        pass
    return explicit or DEFAULT_LEADER


def _calibration_root() -> Path:
    explicit = os.environ.get("HF_LEROBOT_CALIBRATION")
    if explicit:
        return Path(explicit).expanduser()
    hf = os.environ.get("HF_LEROBOT_HOME") or os.environ.get("HF_HOME")
    if hf:
        base = Path(hf).expanduser()
        if base.name == "lerobot":
            return base / "calibration"
        return base / "lerobot" / "calibration"
    return Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"


def _load_prefs() -> Dict[str, str]:
    try:
        if _PREFS_FILE.is_file():
            data = json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:
        logger.debug("load b601 prefs: %s", exc)
    return {}


def _save_prefs(
    *,
    arm_variant: Optional[str] = None,
    follower_port: Optional[str] = None,
    robot_id: Optional[str] = None,
    leader_id: Optional[str] = None,
) -> Dict[str, str]:
    cur = _load_prefs()
    if arm_variant:
        cur["arm_variant"] = _normalize_arm_variant(arm_variant)
    if follower_port:
        cur["follower_port"] = follower_port.strip()
    if robot_id:
        cur["robot_id"] = robot_id.strip()
    if leader_id:
        cur["leader_id"] = leader_id.strip()
    _PREFS_DIR.mkdir(parents=True, exist_ok=True)
    _PREFS_FILE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    return cur


def _normalize_arm_variant(value: Optional[str]) -> str:
    raw = (value or "").strip().lower().replace("b601-", "").replace("b601_", "")
    if raw in ("dm", "damiao"):
        return "dm"
    if raw in ("rs", "robstride"):
        return "rs"
    if raw in ("auto", ""):
        if DEFAULT_ARM_VARIANT in ("dm", "damiao"):
            return "dm"
        if DEFAULT_ARM_VARIANT in ("rs", "robstride"):
            return "rs"
        return "dm" if _detect_dm_port() else "rs"
    raise HTTPException(status_code=400, detail="arm_variant 必须是 dm 或 rs")


def _resolve_arm_variant(explicit: Optional[str] = None) -> str:
    if explicit:
        return _normalize_arm_variant(explicit)
    prefs = _load_prefs()
    if prefs.get("arm_variant"):
        return _normalize_arm_variant(prefs["arm_variant"])
    return _normalize_arm_variant(DEFAULT_ARM_VARIANT)


def _follower_calib_type(arm_variant: Optional[str] = None) -> str:
    return FOLLOWER_CALIB_TYPE_DM if _resolve_arm_variant(arm_variant) == "dm" else FOLLOWER_CALIB_TYPE_RS


def _follower_transport(arm_variant: Optional[str] = None) -> str:
    """LeRobot ``--robot.can_adapter`` value (not motorbridge-cli ``--transport``).

    DM serial bridge must be ``damiao`` so ``MotorBridgeController.from_dm_serial``
    is used. ``dm-serial`` is only the motorbridge-cli transport flag.
    """
    return "damiao" if _resolve_arm_variant(arm_variant) == "dm" else "socketcan"


def _detect_dm_port() -> Optional[str]:
    candidates: List[str] = []
    prefs = _load_prefs()
    for raw in (prefs.get("follower_port"), DEFAULT_DM_PORT, "/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyACM2", "/dev/ttyACM3"):
        if raw and raw not in candidates:
            candidates.append(raw)
    for raw in candidates:
        try:
            if Path(raw).exists():
                return raw
        except Exception:
            continue
    return None


def _resolve_follower_port(
    *,
    arm_variant: Optional[str] = None,
    explicit: Optional[str] = None,
    can_iface: Optional[str] = None,
) -> str:
    variant = _resolve_arm_variant(arm_variant)
    if variant == "rs":
        return explicit or can_iface or DEFAULT_CAN
    if explicit and explicit.strip():
        return explicit.strip()
    # Backward-compatible API: older callers still pass can_iface; for DM it is
    # interpreted as the serial bridge path.
    if can_iface and can_iface.strip() and can_iface.startswith("/dev/"):
        return can_iface.strip()
    return _detect_dm_port() or DEFAULT_DM_PORT


def _resolve_robot_id(explicit: Optional[str] = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return _load_prefs().get("robot_id") or ROBOT_ID


def _resolve_leader_id(explicit: Optional[str] = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    return _load_prefs().get("leader_id") or LEADER_ID


def _list_cal_ids(category: str, robot_type: str) -> List[str]:
    root = _calibration_root() / category / robot_type
    if not root.is_dir():
        return []
    return sorted(p.stem for p in root.glob("*.json"))


def _calibration_status(
    robot_id: Optional[str] = None,
    leader_id: Optional[str] = None,
    arm_variant: Optional[str] = None,
) -> CalibrationStatus:
    variant = _resolve_arm_variant(arm_variant)
    follower_type = _follower_calib_type(variant)
    rid = _resolve_robot_id(robot_id)
    lid = _resolve_leader_id(leader_id)
    root = _calibration_root()
    follower = root / "robots" / follower_type / f"{rid}.json"
    leader = root / "teleoperators" / LEADER_CALIB_TYPE / f"{lid}.json"
    follower_ids = _list_cal_ids("robots", follower_type)
    leader_ids = _list_cal_ids("teleoperators", LEADER_CALIB_TYPE)
    return CalibrationStatus(
        follower=follower.is_file(),
        leader=leader.is_file(),
        arm_variant=variant,
        follower_type=follower_type,
        follower_path=str(follower) if follower.is_file() else None,
        leader_path=str(leader) if leader.is_file() else None,
        robot_id=rid,
        leader_id=lid,
        follower_ids=follower_ids,
        leader_ids=leader_ids,
    )


def _config_response() -> B601ConfigResponse:
    cal = _calibration_status()
    port = _resolve_follower_port(arm_variant=cal.arm_variant)
    return B601ConfigResponse(
        arm_variant=cal.arm_variant,
        follower_port=port,
        follower_type=cal.follower_type,
        follower_transport=_follower_transport(cal.arm_variant),
        robot_id=cal.robot_id,
        leader_id=cal.leader_id,
        follower_ids=cal.follower_ids,
        leader_ids=cal.leader_ids,
        calibration_follower=cal.follower,
        calibration_leader=cal.leader,
    )


def _can_iface_present(iface: str) -> bool:
    return Path(f"/sys/class/net/{iface}").exists()


def _can_is_up(iface: str) -> bool:
    try:
        out = subprocess.run(
            ["ip", "-br", "link", "show", iface],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode != 0:
            return False
        parts = out.stdout.strip().split()
        # ip -br: "can0  UP  <NOARP,UP,...>" — state is the 2nd field
        return len(parts) >= 2 and parts[1].upper() == "UP"
    except Exception:
        return False


_cli_on_path_cache: Dict[str, bool] = {}


def _cli_on_path(name: str) -> bool:
    """Cached CLI presence — health polls must not re-run subprocess probes."""
    cached = _cli_on_path_cache.get(name)
    if cached is not None:
        return cached
    try:
        resolve_cli_argv(name)
        ok = True
    except Exception:
        ok = False
    _cli_on_path_cache[name] = ok
    return ok


def _pgrep_running(pattern: str) -> bool:
    """Return True if a process matching *pattern* is running.

    ``pgrep`` is Linux-only; on Windows (demo laptop without CAN) always False.
    Never raises — used from health endpoints that must stay 200.
    """
    if sys.platform == "win32":
        return False
    try:
        return subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            timeout=3,
        ).returncode == 0
    except Exception:
        return False


def _kill_gateway() -> None:
    global _gateway_proc
    for pattern in ("motorbridge-gateway", "ws_gateway"):
        try:
            if sys.platform == "win32":
                break
            subprocess.run(["pkill", "-f", pattern], timeout=5)
        except Exception:
            pass
    if _gateway_proc and _gateway_proc.poll() is None:
        try:
            _gateway_proc.terminate()
            _gateway_proc.wait(timeout=3)
        except Exception:
            pass
    _gateway_proc = None


def _reap_zombie_teleop_procs() -> None:
    """Kill any leftover lerobot-teleoperate / b601_teleop_launcher processes
    that may still hold /dev/ttyUSB0 or can0 after a crash (e.g. motor overcurrent).
    These are not tracked by our _teleop_proc and would otherwise cause
    'Device or resource busy' on the next start.
    """
    if sys.platform == "win32":
        return
    for pattern in (
        "b601_teleop_launcher",
        "lerobot-teleoperate",
        "lerobot_robot_seeed_b601",
    ):
        try:
            subprocess.run(["pkill", "-9", "-f", pattern], timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("pkill -f %s timed out", pattern)
        except Exception:
            pass


async def _run_shell(cmd: List[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def _run_privileged(
    argv: List[str],
    *,
    sudo_password: Optional[str] = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[str]:
    """Run ``sudo …``; optionally feed password via stdin (localhost agent only)."""
    if argv and argv[0] == "sudo":
        rest = argv[1:]
    else:
        rest = argv
    if sudo_password is not None:
        return await asyncio.to_thread(
            subprocess.run,
            ["sudo", "-S", "-p", ""] + rest,
            input=sudo_password + "\n",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    return await _run_shell(["sudo"] + rest, timeout=timeout)


def _sudo_friendly_error(raw: str) -> str:
    err = (raw or "CAN 配置失败").strip()
    low = err.lower()
    if "sorry" in low or "incorrect password" in low or "authentication failure" in low:
        return "sudo 密码不对，请重新输入。"
    if "password" in low or "sudo" in low or "terminal is required" in low:
        return "需要本机 sudo 密码 — 请在下方输入电脑登录密码，或展开复制终端命令。"
    return err


async def can_up(iface: str = DEFAULT_CAN, *, sudo_password: Optional[str] = None) -> CanUpResponse:
    """Bring CAN interface up @ 1 Mbps (matches Seeed getting-started wiki)."""
    try:
        await _run_privileged(["modprobe", "peak_usb"], sudo_password=sudo_password, timeout=10)
    except Exception as exc:
        logger.warning("modprobe peak_usb: %s", exc)

    if not Path(f"/sys/class/net/{iface}").exists():
        return CanUpResponse(ok=False, message=f"{iface} 未找到，请插入 PCAN-USB", iface=iface)

    for cmd in (
        ["ip", "link", "set", iface, "down"],
        ["ip", "link", "set", iface, "type", "can", "bitrate", str(CAN_BITRATE), "restart-ms", "100"],
        ["ip", "link", "set", iface, "up"],
    ):
        try:
            r = await _run_privileged(cmd, sudo_password=sudo_password, timeout=15)
            if r.returncode != 0 and cmd[-1] != "down":
                return CanUpResponse(
                    ok=False,
                    message=_sudo_friendly_error(r.stderr or r.stdout or ""),
                    iface=iface,
                )
        except subprocess.TimeoutExpired:
            return CanUpResponse(ok=False, message="CAN 配置超时", iface=iface)

    up = _can_is_up(iface)
    return CanUpResponse(
        ok=up,
        message="CAN 已就绪" if up else "CAN 仍未 UP",
        iface=iface,
    )


async def _recover_one_motor(can: str, mid: int, *, timeout_ms: str = "800") -> bool:
    """clear-error + enable one motor. Returns True if both commands succeed."""
    cli = resolve_cli_argv("motorbridge-cli")
    model = _MOTOR_MODELS[mid]
    ok = True
    for mode in ("clear-error", "enable"):
        try:
            await _run_shell(
                [
                    *cli,
                    "run",
                    "--vendor",
                    "robstride",
                    "--channel",
                    can,
                    "--transport",
                    "socketcan",
                    "--motor-id",
                    str(mid),
                    "--feedback-id",
                    "0xFD",
                    "--model",
                    model,
                    "--mode",
                    mode,
                    "--timeout-ms",
                    timeout_ms,
                ],
                timeout=max(5, int(timeout_ms) // 200 + 3),
            )
        except Exception as exc:
            logger.debug("motor %s %s: %s", mid, mode, exc)
            ok = False
    return ok


async def recover_follower(can: str = DEFAULT_CAN, *, arm_variant: Optional[str] = None) -> RecoverResponse:
    """Clear faults + enable all 7 RobStride motors (rebot-recover-follower.sh logic).

    Gripper (ID 7) gets extra retries — it is the joint that most often drops offline.
    """
    variant = _resolve_arm_variant(arm_variant)
    if variant == "dm":
        motors = await scan_motors(can, arm_variant="dm")
        online = sum(1 for m in motors if m.online)
        return RecoverResponse(
            ok=online >= B601_MIN_MOTORS_TELEOP,
            message=f"DM 从臂扫描完成：{online}/7 电机在线",
            motors_enabled=online,
        )

    _kill_gateway()
    await asyncio.sleep(0.5)
    if not _can_is_up(can):
        await can_up(can)

    enabled = 0
    for mid in _MOTOR_MODELS:
        # Gripper (ID7) is the joint that most often drops off CAN; give it one
        # slightly longer attempt but do NOT burn 3×2000ms every wake.
        attempts = 2 if mid == 7 else 1
        timeout_ms = "1000" if mid == 7 else "800"
        ok = False
        for attempt in range(attempts):
            ok = await _recover_one_motor(can, mid, timeout_ms=timeout_ms)
            if ok:
                break
            await asyncio.sleep(0.3 + attempt * 0.4)
        if ok:
            enabled += 1
        elif mid == 7:
            logger.warning("[b601] recover: gripper (motor 7) still not responding")

    return RecoverResponse(
        ok=enabled >= 6,
        message=(
            "机械臂已恢复，请尽快开始遥操"
            if enabled >= 7
            else f"已唤醒 {enabled}/7 电机 — 若夹爪无响应，请关闭从臂 48V 电源 5 秒再打开，然后重试"
        ),
        motors_enabled=enabled,
    )


async def _ensure_motors_online_for_teleop(
    can: str,
    *,
    min_motors: int = B601_MIN_MOTORS_TELEOP,
    arm_variant: Optional[str] = None,
) -> List[MotorScanItem]:
    """Fast check: if enough motors online, start teleop and skip offline joints."""
    # Shorter ping during teleop boot (gripper fails fast at 350ms).
    variant = _resolve_arm_variant(arm_variant)
    last = await scan_motors(can, ping_timeout_ms=350 if variant == "rs" else 600, arm_variant=variant)
    online = {m.motor_id for m in last if m.online}
    missing = [i for i in range(1, 8) if i not in online]

    if len(online) >= min_motors:
        if missing:
            labels = [
                B601_JOINT_LABELS_ZH.get(_B601_JOINT_NAMES[i - 1], f"ID{i}") for i in missing
            ]
            logger.warning(
                "[b601] teleop with %s/7 motors (offline: %s)",
                len(online),
                ", ".join(labels),
            )
        return last

    # Below minimum — one quick recover pass then rescan
    logger.warning("[b601] only %s/7 online — recover once before teleop", len(online))
    for mid in missing:
        if variant == "rs":
            await _recover_one_motor(can, mid, timeout_ms="1500")
    await recover_follower(can, arm_variant=variant)
    await asyncio.sleep(0.4)
    last = await scan_motors(can, ping_timeout_ms=600, arm_variant=variant)
    online = {m.motor_id for m in last if m.online}
    if len(online) < min_motors:
        missing = [i for i in range(1, 8) if i not in online]
        names = [
            B601_JOINT_LABELS_ZH.get(_B601_JOINT_NAMES[i - 1], f"电机{i}") for i in missing
        ]
        raise RuntimeError(
            f"在线电机不足（{len(online)}/7，至少需要 {min_motors} 个）— "
            f"掉线：{', '.join(names)}。请检查 48V 与 CAN 线。"
        )
    return last


async def disable_follower(can: str = DEFAULT_CAN, *, arm_variant: Optional[str] = None) -> RecoverResponse:
    """Disable torque on all 7 joints (motorbridge-cli disable + LeRobot disconnect).

    Same as ``scripts/rebot-disable-follower.sh`` and ``SeeedB601Follower.disconnect()``.
    """
    variant = _resolve_arm_variant(arm_variant)
    if variant == "dm":
        logger.info("[b601] disable_follower: releasing DM torque on %s", can)
        cli = resolve_cli_argv("motorbridge-cli")

        async def _disable_dm_one(mid: int, model: str) -> None:
            try:
                await _run_shell(
                    [
                        *cli,
                        "run",
                        "--vendor",
                        "damiao",
                        "--transport",
                        "dm-serial",
                        "--serial-port",
                        can,
                        "--serial-baud",
                        str(DM_SERIAL_BAUD),
                        "--motor-id",
                        str(mid),
                        "--feedback-id",
                        hex(mid + 0x10),
                        "--model",
                        model,
                        "--mode",
                        "disable",
                        "--timeout-ms",
                        "400",
                    ],
                    timeout=5,
                )
            except Exception as exc:
                logger.debug("dm motor %s disable: %s", mid, exc)

        await asyncio.gather(*(_disable_dm_one(mid, model) for mid, model in _DM_MOTOR_MODELS.items()))
        return RecoverResponse(ok=True, message="DM 从臂已卸力，可手推关节", motors_enabled=7)

    logger.info("[b601] disable_follower: releasing torque on %s", can)
    _kill_gateway()
    if not _can_is_up(can):
        await can_up(can)

    cli = resolve_cli_argv("motorbridge-cli")

    async def _disable_one(mid: int, model: str) -> None:
        try:
            await _run_shell(
                [
                    *cli,
                    "run",
                    "--vendor",
                    "robstride",
                    "--channel",
                    can,
                    "--transport",
                    "socketcan",
                    "--motor-id",
                    str(mid),
                    "--feedback-id",
                    "0xFD",
                    "--model",
                    model,
                    "--mode",
                    "disable",
                    "--timeout-ms",
                    "400",
                ],
                timeout=5,
            )
        except Exception as exc:
            logger.debug("motor %s disable: %s", mid, exc)

    await asyncio.gather(*(_disable_one(mid, model) for mid, model in _MOTOR_MODELS.items()))

    logger.info("[b601] disable_follower: done (7 joints)")
    return RecoverResponse(ok=True, message="从臂已卸力，可手推关节", motors_enabled=7)


async def _ping_motor_id(can: str, mid: int, *, timeout_ms: int = 2000) -> bool:
    """Read-only unicast ping for one RobStride ID (Seeed getting-started / hw-diagnose step 6)."""
    cli = resolve_cli_argv("motorbridge-cli")
    model = _MOTOR_MODELS[mid]
    try:
        r = await _run_shell(
            [
                *cli,
                "run",
                "--vendor",
                "robstride",
                "--channel",
                can,
                "--transport",
                "socketcan",
                "--motor-id",
                str(mid),
                "--feedback-id",
                "0xFD",
                "--model",
                model,
                "--mode",
                "ping",
                "--timeout-ms",
                str(timeout_ms),
            ],
            timeout=max(6, timeout_ms // 300 + 4),
        )
        blob = f"{r.stdout or ''}\n{r.stderr or ''}"
        low = blob.lower()
        if "timed out" in low or "failed" in low or "no reply" in low:
            return False
        if re.search(rf"device_id\s*=\s*{mid}\b", blob, re.I):
            return True
        return r.returncode == 0 and "ping device_id" in low
    except Exception as exc:
        logger.debug("ping motor %s: %s", mid, exc)
        return False


def _motor_scan_item(mid: int, online: bool, *, arm_variant: Optional[str] = None) -> MotorScanItem:
    variant = _resolve_arm_variant(arm_variant)
    label = B601_JOINT_LABELS_ZH.get(_B601_JOINT_NAMES[mid - 1], f"ID{mid}")
    return MotorScanItem(
        motor_id=mid,
        model=(_DM_MOTOR_MODELS if variant == "dm" else _MOTOR_MODELS)[mid],
        online=online,
        label=f"ID{mid} {label}",
    )


async def _scan_dm_motors(
    port: str,
    *,
    ping_timeout_ms: int | None = None,
) -> List[MotorScanItem]:
    cli = resolve_cli_argv("motorbridge-cli")
    timeout_ms = str(ping_timeout_ms or 600)
    try:
        r = await _run_shell(
            [
                *cli,
                "scan",
                "--vendor",
                "damiao",
                "--transport",
                "dm-serial",
                "--serial-port",
                port,
                "--serial-baud",
                str(DM_SERIAL_BAUD),
                "--start-id",
                "1",
                "--end-id",
                "7",
                "--timeout-ms",
                timeout_ms,
            ],
            timeout=12,
        )
        blob = f"{r.stdout or ''}\n{r.stderr or ''}"
        hits = {int(m.group(1), 16) for m in re.finditer(r"esc_id=0x([0-9a-f]+)", blob, re.I)}
        hits |= {int(m.group(1), 16) for m in re.finditer(r"probe=0x([0-9a-f]+).*vendor=damiao", blob, re.I)}
        return [_motor_scan_item(i, i in hits, arm_variant="dm") for i in range(1, 8)]
    except Exception as exc:
        logger.debug("dm motor scan on %s failed: %s", port, exc)
        return [_motor_scan_item(i, False, arm_variant="dm") for i in range(1, 8)]


async def scan_motors(
    can: str = DEFAULT_CAN,
    *,
    ping_timeout_ms: int | None = None,
    arm_variant: Optional[str] = None,
) -> List[MotorScanItem]:
    """Ping each motor ID 1..7 individually (read-only)."""
    global _last_motor_scan, _last_motor_scan_ts

    variant = _resolve_arm_variant(arm_variant)
    if variant == "dm":
        items = await _scan_dm_motors(can, ping_timeout_ms=ping_timeout_ms)
        _last_motor_scan = items
        _last_motor_scan_ts = time.time()
        return items

    if not _can_is_up(can):
        items = [_motor_scan_item(i, False, arm_variant="rs") for i in range(1, 8)]
        _last_motor_scan = items
        _last_motor_scan_ts = time.time()
        return items

    items: List[MotorScanItem] = []
    for mid in range(1, 8):
        t_ms = ping_timeout_ms if ping_timeout_ms is not None else (2500 if mid == 7 else 2000)
        online = await _ping_motor_id(can, mid, timeout_ms=t_ms)
        items.append(_motor_scan_item(mid, online, arm_variant="rs"))

    _last_motor_scan = items
    _last_motor_scan_ts = time.time()
    return items


async def diagnose_motors(can: str = DEFAULT_CAN, *, arm_variant: Optional[str] = None) -> MotorDiagnoseResponse:
    """Explicit per-ID diagnostic for setup UI (read-only; no register writes)."""
    variant = _resolve_arm_variant(arm_variant)
    can_up = Path(can).exists() if variant == "dm" else _can_is_up(can)
    if not can_up:
        motors = [_motor_scan_item(i, False, arm_variant=variant) for i in range(1, 8)]
        return MotorDiagnoseResponse(
            ok=False,
            can_iface=can,
            can_up=False,
            motors=motors,
            motors_online=0,
            message=("DM 串口未找到" if variant == "dm" else "CAN 未就绪 — 请先连接 can0"),
            issues=[("DM USB-CAN 串口未找到" if variant == "dm" else "CAN 未 UP")],
        )

    motors = await scan_motors(can, arm_variant=variant)
    online = sum(1 for m in motors if m.online)
    missing = [m for m in motors if not m.online]
    issues: List[str] = []
    if missing:
        labels = ", ".join(m.label for m in missing)
        if any(m.motor_id == 7 for m in missing):
            issues.append(
                f"夹爪（ID7）无应答 — 查腕部→夹爪 CAN/48V 线；成品套件只扫描不重写 ID"
            )
        issues.append(f"掉线：{labels}（{online}/7）")
    msg = (
        "7/7 电机在线，可标定与遥操"
        if online >= 7
        else f"逐 ID 检测：{online}/7 在线"
    )
    return MotorDiagnoseResponse(
        ok=online >= 7,
        can_iface=can,
        can_up=True,
        motors=motors,
        motors_online=online,
        message=msg,
        issues=issues,
    )


def _v4l_dev_path(index: int) -> str:
    return f"/dev/video{int(index)}"


def _open_v4l_capture(index: int, *, retries: int = 5, delay_s: float = 0.12):
    """Open a V4L2 node by path (not integer index).

    OpenCV's ``VideoCapture(index)`` intermittently fails with
    ``can't open camera by index`` even when ``/dev/videoN`` is free — common
    after a previous release / MJPEG preview / Discord portal flicker.
    """
    try:
        import cv2
    except Exception as exc:  # pragma: no cover
        return None, f"OpenCV 不可用：{exc}"

    path = _v4l_dev_path(index)
    if not Path(path).exists():
        return None, f"{path} 不存在（相机已拔掉或索引变了）"

    def _holder_msg() -> str:
        try:
            from .camera import _device_holders

            hits = _device_holders(int(index))
        except Exception:
            hits = []
        if not hits:
            return ""
        parts = [f"pid={p} {c}" for p, c in hits[:3]]
        return " 占用进程: " + "; ".join(parts)

    last_reason = "unknown"
    for attempt in range(max(1, retries)):
        # Don't hard-fail on a fleeting hold (portal / previous preview) — retry open.
        cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
            cap = cv2.VideoCapture(path)
        if cap.isOpened():
            return cap, None
        try:
            cap.release()
        except Exception:
            pass
        held = _holder_msg()
        last_reason = f"OpenCV 打不开 {path}{held}"
        time.sleep(delay_s * (attempt + 1))
    held = _holder_msg()
    if held:
        return None, f"{path} 打不开。{held.lstrip()}（不是瞎猜 Discord；上面是实际 pid）"
    return None, f"{last_reason}（已重试 {retries} 次；当前无进程占用，多半是驱动未就绪，再点一次）"


def _probe_camera_capture(index: int) -> Dict[str, Any]:
    """Pick width/height/fps/fourcc that LeRobot's OpenCvCamera will accept.

    Some UVC cams (e.g. icspring) refuse MJPG@30 and report actual_fps=60,
    which makes lerobot-record abort in ``_validate_fps``.
    """
    # Prefer compressed MJPG so 2–3 USB cams can share one bus.
    # YUYV@30 "works" alone on some cams (icspring) but saturates USB and
    # makes the next OpenCVCamera die with "read thread is not running".
    candidates: List[tuple[Optional[str], int]] = [
        ("MJPG", 30),
        ("MJPG", 60),
        (None, 30),
        (None, 60),
        ("YUYV", 30),  # last resort — high bandwidth
    ]
    try:
        import cv2
    except Exception:
        return {"width": 640, "height": 480, "fps": 30, "fourcc": None}

    cap, err = _open_v4l_capture(index)
    if cap is None:
        logger.warning("b601 camera %s probe open failed: %s", index, err)
        return {"width": 640, "height": 480, "fps": 30, "fourcc": None}

    try:
        for fourcc, fps in candidates:
            if fourcc:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            ok_set = cap.set(cv2.CAP_PROP_FPS, float(fps))
            ok_read, _ = cap.read()
            actual = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if ok_read and ok_set and abs(actual - fps) < 0.5 and w > 0 and h > 0:
                logger.info(
                    "b601 camera %s capture: %sx%s@%s fourcc=%s",
                    index, w, h, fps, fourcc or "auto",
                )
                return {"width": w, "height": h, "fps": fps, "fourcc": fourcc}
    finally:
        cap.release()
        # UVC nodes often need a beat before the next open succeeds.
        time.sleep(0.08)

    logger.warning("b601 camera %s: no exact fps match; omit fourcc and use 30", index)
    return {"width": 640, "height": 480, "fps": 30, "fourcc": None}


def _camera_usb_bus(index: int) -> Optional[str]:
    """Host-controller key, e.g. ``pci-0000:35:00.3`` — cams on the same bus often can't open together."""
    try:
        import subprocess

        out = subprocess.check_output(
            ["udevadm", "info", "--query=property", f"--name=/dev/video{int(index)}"],
            text=True,
            timeout=2,
        )
        for line in out.splitlines():
            if line.startswith("ID_PATH="):
                path = line.split("=", 1)[1].strip()
                # pci-0000:35:00.3-usb-0:2.2:1.0 → pci-0000:35:00.3
                return path.split("-usb-", 1)[0] if "-usb-" in path else path
    except Exception:
        return None
    return None


def _validate_cameras_concurrent(indices: List[int]) -> Optional[str]:
    """Open selected cams together; return a Chinese error if USB bandwidth/bus conflicts."""
    uniq = list(dict.fromkeys(int(i) for i in indices))
    if len(uniq) < 2:
        return None

    buses: Dict[str, List[int]] = {}
    for i in uniq:
        bus = _camera_usb_bus(i) or "unknown"
        buses.setdefault(bus, []).append(i)
    shared = {b: ids for b, ids in buses.items() if len(ids) > 1 and b != "unknown"}
    if shared:
        parts = [f"总线 {b}: Cam " + "/".join(str(x) for x in ids) for b, ids in shared.items()]
        return (
            "这些相机插在同一 USB 控制器上，无法同时采集："
            + "；".join(parts)
            + "。请把其中一路换到主板另一组 USB 口（不要共用同一 Hub）。"
            + "当前可先用跨总线组合：Cam 8+4 或 Cam 6+4。"
        )

    # Even without shared bus metadata, verify concurrent reads succeed.
    try:
        import cv2
    except Exception:
        return None

    # Probe formats first (each open/release), then reopen together for the
    # bandwidth check — never open-by-integer-index (flaky on Linux UVC).
    cfgs = {i: _probe_camera_capture(i) for i in uniq}
    time.sleep(0.15)

    caps: List[Any] = []
    try:
        for i in uniq:
            cfg = cfgs[i]
            cap, err = _open_v4l_capture(i)
            if cap is None:
                for c in caps:
                    c.release()
                return f"无法打开 Cam {i}：{err}"
            if cfg.get("fourcc"):
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*str(cfg["fourcc"])))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(cfg["width"]))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(cfg["height"]))
            cap.set(cv2.CAP_PROP_FPS, float(cfg["fps"]))
            caps.append(cap)
        bad: List[int] = []
        for i, cap in zip(uniq, caps):
            oks = sum(1 for _ in range(8) if cap.read()[0])
            if oks < 3:
                bad.append(i)
        if bad:
            return (
                f"同时打开时 Cam {', '.join(str(x) for x in bad)} 读不到画面（USB 带宽/总线冲突）。"
                "请把冲突的相机换到另一组 USB 口；或先用 Cam 8+4 / Cam 6+4 两路采集。"
            )
    finally:
        for cap in caps:
            try:
                cap.release()
            except Exception:
                pass
    return None


def _cameras_yaml(indices: List[int]) -> str:
    """Build ``--robot.cameras=...`` payload.

    Must be JSON (same as SO-101 ``record_control``). Hand-rolled YAML flow
    maps break draccus/yaml parsing once multiple cameras are present.
    """
    cameras: Dict[str, Any] = {}
    names = ["front", "side", "top", "wrist"]
    for idx, cam_idx in enumerate(indices[:4]):
        name = names[idx] if idx < len(names) else f"cam{idx}"
        cfg = _probe_camera_capture(int(cam_idx))
        entry: Dict[str, Any] = {
            "type": "opencv",
            "index_or_path": int(cam_idx),
            "width": int(cfg["width"]),
            "height": int(cfg["height"]),
            "fps": int(cfg["fps"]),
        }
        if cfg.get("fourcc"):
            entry["fourcc"] = cfg["fourcc"]
        cameras[name] = entry
    return json.dumps(cameras, separators=(",", ":"))


class B601TeleopCLI(CLIProcess):
    role = "b601-teleop"
    # Only match control-loop output — NOT leader "connected." or spawn line.
    ready_patterns = (re.compile(r"Teleop loop time:", re.I),)

    def __init__(
        self,
        *,
        leader_port: str,
        follower_port: str,
        arm_variant: str,
        robot_id: str,
        leader_id: str,
        display_data: bool,
        use_cameras: bool,
        camera_indices: Optional[List[int]] = None,
        fps: int = DEFAULT_TELEOP_FPS,
    ) -> None:
        super().__init__()
        self._leader = leader_port
        self._can = follower_port
        self._arm_variant = _resolve_arm_variant(arm_variant)
        self._robot_id = robot_id
        self._leader_id = leader_id
        self._display = display_data
        self._use_cameras = use_cameras
        self._camera_indices = list(camera_indices or [4, 6])
        self._fps = max(TELEOP_FPS_MIN, min(TELEOP_FPS_MAX, int(fps or DEFAULT_TELEOP_FPS)))

    def build_cmd(self) -> List[str]:
        cameras = _cameras_yaml(self._camera_indices) if self._use_cameras else "{}"
        follower_type = _follower_calib_type(self._arm_variant)
        transport = _follower_transport(self._arm_variant)
        py = _resolve_motorbridge_python()
        if not py:
            # Fallback to lerobot-teleoperate binary (no disable_all patch).
            base = resolve_cli_argv("lerobot-teleoperate")
        else:
            repo_root = Path(__file__).resolve().parents[3]
            launcher = repo_root / "scripts" / "b601_teleop_launcher.py"
            base = [py, str(launcher)]
        return [
            *base,
            f"--robot.type={follower_type}",
            f"--robot.port={self._can}",
            f"--robot.id={self._robot_id}",
            f"--robot.can_adapter={transport}",
            f"--robot.dm_serial_baud={DM_SERIAL_BAUD}",
            f"--robot.cameras={cameras}",
            f"--teleop.type=rebot_arm_102_leader",
            f"--teleop.port={self._leader}",
            f"--teleop.id={self._leader_id}",
            f"--fps={self._fps}",
            f"--display_data={'true' if self._display else 'false'}",
        ]


class B601RecordCLI(CLIProcess):
    role = "b601-record"
    ready_patterns = (re.compile(r"record", re.I), re.compile(r"episode", re.I), re.compile(r"Recording", re.I))

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self._kwargs = kwargs

    def build_env(self) -> dict:
        env = super().build_env()
        # pynput keyboard (→ skip reset) needs a display; inherit or fall back to :0.
        env.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
        env.setdefault("XDG_RUNTIME_DIR", os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        return env

    def build_cmd(self) -> List[str]:
        k = self._kwargs
        cams = _cameras_yaml(k.get("camera_indices") or [4, 6])
        variant = _resolve_arm_variant(k.get("arm_variant"))
        py = _resolve_lerobot_python() or _resolve_motorbridge_python()
        repo_root = Path(__file__).resolve().parents[3]
        launcher = repo_root / "scripts" / "b601_record_launcher.py"
        if py and launcher.is_file():
            base = [py, str(launcher)]
        else:
            base = resolve_cli_argv("lerobot-record")
        return [
            *base,
            f"--robot.type={_follower_calib_type(variant)}",
            f"--robot.port={k['follower_port']}",
            f"--robot.id={k['robot_id']}",
            f"--robot.can_adapter={_follower_transport(variant)}",
            f"--robot.dm_serial_baud={DM_SERIAL_BAUD}",
            f"--robot.cameras={cams}",
            f"--teleop.type=rebot_arm_102_leader",
            f"--teleop.port={k['leader_port']}",
            f"--teleop.id={k['leader_id']}",
            "--display_data=false",
            f"--dataset.repo_id={k['repo_id']}",
            f"--dataset.num_episodes={k['num_episodes']}",
            f"--dataset.single_task={k['single_task']}",
            "--dataset.push_to_hub=false",
            f"--dataset.episode_time_s={k['episode_time_s']}",
            f"--dataset.reset_time_s={k['reset_time_s']}",
            # Encode while recording — otherwise each 100s×2-cam episode blocks
            # 30–90s on libsvtav1 and the UI looks "stuck on 保存中".
            "--dataset.streaming_encoding=true",
            "--dataset.encoder_threads=2",
        ]


class B601InferenceCLI(CLIProcess):
    role = "b601-inference"
    ready_patterns = (re.compile(r"policy", re.I), re.compile(r"record", re.I))

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self._kwargs = kwargs

    def build_cmd(self) -> List[str]:
        k = self._kwargs
        variant = _resolve_arm_variant(k.get("arm_variant"))
        return [
            *resolve_cli_argv("lerobot-record"),
            f"--robot.type={_follower_calib_type(variant)}",
            f"--robot.port={k['follower_port']}",
            f"--robot.id={k['robot_id']}",
            f"--robot.can_adapter={_follower_transport(variant)}",
            f"--robot.dm_serial_baud={DM_SERIAL_BAUD}",
            f"--robot.cameras={_cameras_yaml(list(k.get('camera_indices') or [8, 4]))}",
            f"--teleop.type=rebot_arm_102_leader",
            f"--teleop.port={k['leader_port']}",
            f"--teleop.id={k['leader_id']}",
            f"--policy.path={k['policy_path']}",
            f"--dataset.repo_id=local/b601_inference_run",
            f"--dataset.num_episodes=1",
            f"--dataset.single_task={k['single_task']}",
            "--dataset.push_to_hub=false",
            f"--dataset.episode_time_s={k['episode_time_s']}",
            f"--dataset.reset_time_s=5",
        ]


class B601CalibrateCLI(CLIProcess):
    role = "b601-calibrate"
    ready_patterns = (
        re.compile(r"calibrat", re.I),
        re.compile(r"zero", re.I),
        re.compile(r"ENTER", re.I),
        re.compile(r"press", re.I),
    )

    def __init__(self, *, target: str, leader_port: str, follower_port: str, arm_variant: str, robot_id: str, leader_id: str) -> None:
        super().__init__()
        self._target = target
        self._leader = leader_port
        self._can = follower_port
        self._arm_variant = _resolve_arm_variant(arm_variant)
        self._robot_id = robot_id
        self._leader_id = leader_id

    def build_cmd(self) -> List[str]:
        if self._target == "leader":
            return [
                *resolve_cli_argv("lerobot-calibrate"),
                f"--teleop.type=rebot_arm_102_leader",
                f"--teleop.port={self._leader}",
                f"--teleop.id={self._leader_id}",
            ]
        return [
            *resolve_cli_argv("lerobot-calibrate"),
            f"--robot.type={_follower_calib_type(self._arm_variant)}",
            f"--robot.port={self._can}",
            f"--robot.id={self._robot_id}",
            f"--robot.can_adapter={_follower_transport(self._arm_variant)}",
            f"--robot.dm_serial_baud={DM_SERIAL_BAUD}",
        ]


def _rerun_cli_shim_dir(python_exe: str) -> Path:
    """Directory with a working ``rerun`` launcher.

    Some venvs ship ``bin/rerun`` with a stale shebang (moved machine path).
    Spawn looks up ``rerun`` on PATH — put a bash shim that calls
    ``python -m rerun_cli`` ahead of the broken script.
    """
    shim_dir = Path.home() / ".cache" / "botversex" / "rerun-shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "rerun"
    body = (
        "#!/bin/bash\n"
        f'exec "{python_exe}" -m rerun_cli "$@"\n'
    )
    try:
        if not shim.is_file() or shim.read_text(encoding="utf-8") != body:
            shim.write_text(body, encoding="utf-8")
            shim.chmod(0o755)
    except OSError as exc:
        logger.warning("rerun shim write failed: %s", exc)
    return shim_dir


class B601DatasetVizCLI(CLIProcess):
    """Official ``lerobot-dataset-viz`` → Rerun (cameras + state/action timeline).

    Read-only: does **not** take the B601 CAN/runtime lock.
    """

    role = "b601-dataset-viz"
    ready_patterns = (
        re.compile(r"Starting Rerun", re.I),
        re.compile(r"Logging to Rerun", re.I),
        re.compile(r"Listening for gRPC", re.I),
    )

    def __init__(self, *, repo_id: str, root: Path, episode_index: int) -> None:
        super().__init__()
        self._repo_id = repo_id
        self._root = root
        self._episode = episode_index
        self._python = _resolve_lerobot_python() or sys.executable

    def build_cmd(self) -> List[str]:
        return [
            *resolve_cli_argv("lerobot-dataset-viz"),
            f"--repo-id={self._repo_id}",
            f"--episode-index={self._episode}",
            f"--root={self._root}",
            "--mode=local",
        ]

    def build_env(self) -> dict:
        env = super().build_env()
        # Parent defaults RERUN=off for teleop; viz must spawn the viewer.
        env.pop("RERUN", None)
        shim = _rerun_cli_shim_dir(self._python)
        venv_bin = str(Path(self._python).resolve().parent)
        env["PATH"] = f"{shim}{os.pathsep}{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        env.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
        return env


async def _reap_b601_record(
    *,
    leader: Optional[str] = None,
    can: Optional[str] = None,
    keep_status: bool = True,
) -> None:
    """Release port / runtime locks when record CLI has exited.

    Natural ``lerobot-record`` exit used to leave ``b601-record`` port leases
    held until the user clicked「停止采集」. Stopping teleop does not clear
    those leases — which produced a misleading “请停止遥操” UI error.
    """
    global _record_proc

    if _record_proc is not None and _record_proc.is_alive():
        return

    if _record_proc is not None and not _record_proc.is_alive():
        dead = _record_proc
        logger.info("reaping dead b601 record session %s", dead.session_id)
        await port_lock_manager.release_for_process(dead.session_id)
        if isinstance(dead, B601RecordCLI):
            ports = [
                dead._kwargs.get("leader_port"),
                dead._kwargs.get("follower_port"),
            ]
            ports_f = [str(p) for p in ports if p]
            if ports_f:
                await port_lock_manager.release(ports_f)
        await b601_runtime_lock.release(RuntimeMode.RECORD)
        if not keep_status:
            _record_proc = None

    stale: List[str] = []
    for p in (leader, can):
        if not p:
            continue
        busy, owner = port_lock_manager.is_port_busy(p)
        if busy and owner == "b601-record" and not (_record_proc and _record_proc.is_alive()):
            stale.append(p)
    if stale:
        logger.warning("clearing stale b601-record port locks: %s", stale)
        await port_lock_manager.release(stale)
        await b601_runtime_lock.release(RuntimeMode.RECORD)


async def _reap_b601_teleop(
    *,
    leader: Optional[str] = None,
    can: Optional[str] = None,
) -> None:
    """Release port locks when teleop subprocess died but in-memory leases remain.

    Do NOT kill zombie launcher processes while a teleop start task is running
    or a teleop process is alive — that would SIGKILL the very process we just
    spawned (frontend polls /teleop/status every ~2s and calls this).
    """
    global _teleop_proc

    # If a start task is in flight or the teleop process is alive, do NOT
    # run pkill — it would kill the live launcher.
    if _teleop_start_in_progress():
        return
    if _teleop_proc is not None and _teleop_proc.is_alive():
        return

    if _teleop_proc is not None and not _teleop_proc.is_alive():
        dead = _teleop_proc
        logger.info("reaping dead b601 teleop session %s", dead.session_id)
        await port_lock_manager.release_for_process(dead.session_id)
        follower_port = dead._can if isinstance(dead, B601TeleopCLI) else None
        arm_variant = dead._arm_variant if isinstance(dead, B601TeleopCLI) else None
        if isinstance(dead, B601TeleopCLI):
            await port_lock_manager.release([dead._leader, dead._can])
        _teleop_proc = None
        # Unexpected death often leaves Damiao torque on — force disable so
        # users don't need a power cycle (their previous workaround).
        if follower_port:
            try:
                await disable_follower(follower_port, arm_variant=arm_variant)
            except Exception as exc:
                logger.warning("disable after teleop death failed: %s", exc)

    # Now safe to kill any OS-level zombie teleop processes (e.g. a launcher
    # that crashed with motor overcurrent but its python process didn't exit).
    await asyncio.to_thread(_reap_zombie_teleop_procs)
    await asyncio.sleep(0.2)

    if _teleop_proc is None:
        stale: List[str] = []
        for p in (leader, can):
            if not p:
                continue
            busy, owner = port_lock_manager.is_port_busy(p)
            if busy and owner == "b601-teleop":
                stale.append(p)
        if stale:
            logger.warning("clearing stale b601-teleop port locks: %s", stale)
            await port_lock_manager.release(stale)

    # Finished record sessions also hold leader/follower ports — free them.
    await _reap_b601_record(leader=leader, can=can, keep_status=True)


def _proc_status(proc: Optional[CLIProcess], role: str) -> SessionStatus:
    if proc is None or proc._proc is None:
        extra: Dict[str, Any] = {}
        if role == "calibrate" and _calibrate_target:
            extra["calibrate_target"] = _calibrate_target
        return SessionStatus(running=False, role=role, **extra)
    alive = proc._proc.poll() is None
    rc = None if alive else proc._proc.returncode
    tail = list(proc._log)[-40:] if role == "record" else list(proc._log)[-20:]
    last_err = proc.last_error
    unhealthy = False
    if alive:
        recent = "\n".join(tail).lower()
        if last_err or "traceback" in recent or "error:" in recent or " exited " in recent:
            unhealthy = True
    ep_cur, ep_total = (None, None)
    if role == "record":
        # Search the full ring buffer — encode spam pushes "Recording episode N"
        # out of the last-40 window returned to the UI.
        full_log = list(proc._log)
        ep_cur, ep_total = _parse_record_episode(full_log)
        if ep_total is None and isinstance(proc, B601RecordCLI):
            try:
                ep_total = int(proc._kwargs.get("num_episodes") or 0) or None
            except Exception:
                ep_total = None
        global _record_episode_sticky
        if ep_cur is not None:
            _record_episode_sticky = ep_cur
        elif alive and _record_episode_sticky is not None:
            ep_cur = _record_episode_sticky
        elif not alive and rc == 0 and ep_total is not None:
            # Finished cleanly — show total completed, not "—"
            ep_cur = _record_episode_sticky or ep_total
    status = SessionStatus(
        running=alive,
        healthy=(alive and not unhealthy) or (not alive and rc == 0),
        starting=False,
        last_error=last_err,
        role=role,
        session_id=proc.session_id,
        pid=proc._proc.pid if alive else None,
        started_at=proc.started_at,
        uptime_s=time.time() - proc.started_at if alive else None,
        log_tail=tail,
        episode_current=ep_cur,
        episode_total=ep_total,
        returncode=rc,
    )
    if role == "calibrate" and _calibrate_target:
        status.calibrate_target = _calibrate_target
    if role == "teleop" and isinstance(proc, B601TeleopCLI):
        cal = _calibration_status(robot_id=proc._robot_id, leader_id=proc._leader_id, arm_variant=proc._arm_variant)
        status.robot_id = proc._robot_id
        status.leader_id = proc._leader_id
        status.follower_cal_path = cal.follower_path
        status.leader_cal_path = cal.leader_path
    if role == "record" and isinstance(proc, B601RecordCLI):
        global _record_phase_started_at, _record_phase_last
        rid = str(proc._kwargs.get("repo_id") or "")
        status.repo_id = rid or None
        ds = _lerobot_dataset_path(rid) if rid else None
        status.dataset_dir = str(ds) if ds else None
        try:
            status.episode_time_s = int(proc._kwargs.get("episode_time_s") or 0) or None
        except Exception:
            status.episode_time_s = None
        try:
            status.reset_time_s = int(proc._kwargs.get("reset_time_s") or 0)
        except Exception:
            status.reset_time_s = None
        # Full ring buffer: streaming SVT spam must not hide "Recording episode".
        phase, hint = _parse_record_phase(
            full_log,
            alive=alive,
            returncode=rc,
            ep_cur=ep_cur,
            ep_total=ep_total,
        )
        if phase != _record_phase_last:
            _record_phase_last = phase
            _record_phase_started_at = time.time()
        elapsed = (
            max(0.0, time.time() - _record_phase_started_at)
            if _record_phase_started_at is not None
            else None
        )
        status.phase_elapsed_s = elapsed
        if phase == "recording" and status.episode_time_s and elapsed is not None:
            hint = (
                f"{hint} 已录 {int(elapsed)}s / 目标 {status.episode_time_s}s。"
            )
        elif phase == "resetting" and status.reset_time_s is not None and elapsed is not None:
            hint = (
                f"{hint} 复位已过 {int(elapsed)}s / 目标 {status.reset_time_s}s。"
            )
        elif phase == "saving" and ep_cur and elapsed is not None and elapsed >= 5:
            hint = f"{hint} 已保存约 {int(elapsed)}s…"
        status.record_phase = phase
        status.phase_hint = hint
        if not alive:
            _record_episode_sticky = None
    return status


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/config", response_model=B601ConfigResponse)
async def b601_get_config() -> B601ConfigResponse:
    """Active follower/leader calibration ids + available files on disk."""
    return _config_response()


@router.post("/config", response_model=B601ConfigResponse)
async def b601_set_config(body: B601ConfigUpdate) -> B601ConfigResponse:
    if not body.arm_variant and not body.follower_port and not body.robot_id and not body.leader_id:
        raise HTTPException(status_code=400, detail="请提供 arm_variant、follower_port、robot_id 或 leader_id")
    _save_prefs(
        arm_variant=body.arm_variant,
        follower_port=body.follower_port,
        robot_id=body.robot_id,
        leader_id=body.leader_id,
    )
    return _config_response()


@router.delete("/calibration/file", response_model=B601ConfigResponse)
async def b601_delete_calibration(body: CalibrationDeleteRequest) -> B601ConfigResponse:
    side = body.side.lower().strip()
    cal_id = body.cal_id.strip()
    if not cal_id or "/" in cal_id or ".." in cal_id:
        raise HTTPException(status_code=400, detail="无效的标定 ID")

    if side == "follower":
        follower_type = _follower_calib_type()
        path = _calibration_root() / "robots" / follower_type / f"{cal_id}.json"
        ids_key = "robot_id"
        remaining = _list_cal_ids("robots", follower_type)
    elif side == "leader":
        path = _calibration_root() / "teleoperators" / LEADER_CALIB_TYPE / f"{cal_id}.json"
        ids_key = "leader_id"
        remaining = _list_cal_ids("teleoperators", LEADER_CALIB_TYPE)
    else:
        raise HTTPException(status_code=400, detail="side 必须是 follower 或 leader")

    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"标定文件不存在: {cal_id}")

    path.unlink()
    prefs = _load_prefs()
    if prefs.get(ids_key) == cal_id:
        if remaining and cal_id in remaining:
            remaining = [x for x in remaining if x != cal_id]
        if remaining:
            if side == "follower":
                _save_prefs(robot_id=remaining[-1])
            else:
                _save_prefs(leader_id=remaining[-1])
        else:
            prefs.pop(ids_key, None)
            _PREFS_DIR.mkdir(parents=True, exist_ok=True)
            _PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")

    return _config_response()


@router.get("/health", response_model=HealthResponse)
async def b601_health(can_iface: str = DEFAULT_CAN, arm_variant: Optional[str] = None) -> HealthResponse:
    # During teleop startup, skip motor scan to avoid CAN bus contention
    # that breaks configure() (disable_all / ensure_mode ack timeouts).
    skip_scan = _teleop_start_in_progress() or (
        _teleop_proc is not None and _teleop_proc.is_alive()
    )
    variant = _resolve_arm_variant(arm_variant)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    return await _build_health(port, arm_variant=variant, skip_motor_scan=skip_scan)


async def _build_health(
    can_iface: str,
    *,
    arm_variant: Optional[str] = None,
    skip_motor_scan: bool = False,
) -> HealthResponse:
    variant = _resolve_arm_variant(arm_variant)
    follower_type = _follower_calib_type(variant)
    transport = _follower_transport(variant)
    leader = _resolve_leader(None)
    # Windows demo has no SocketCAN — return immediately so aggressive UI polling
    # cannot block/crash the single uvicorn worker (was causing Vite 502).
    if sys.platform == "win32":
        cal = _calibration_status(arm_variant=variant)
        return HealthResponse(
            ok=False,
            ready_for_teleop=False,
            arm_variant=variant,
            follower_type=follower_type,
            follower_transport=transport,
            follower_port=can_iface,
            can_up=False,
            can_present=False,
            can_iface=can_iface,
            leader_present=False,
            leader_port=leader,
            motors_online=0,
            motors=[],
            motors_scan_stale=False,
            calibration_follower=cal.follower,
            calibration_leader=cal.leader,
            robot_id=cal.robot_id,
            leader_id=cal.leader_id,
            # Do not probe CLIs here — resolve_cli_argv can block tens of seconds.
            motorbridge_cli=False,
            lerobot_teleoperate=False,
            gateway_running=False,
            cameras_available=0,
            power_hint="Windows 展示机无 CAN：B601 遥操请在 Linux 实机上使用",
            issues=["Windows 展示机无 PCAN/CAN0 — B601 仅可浏览 UI，遥操请用 Linux 主机"],
        )

    can_present = Path(can_iface).exists() if variant == "dm" else _can_iface_present(can_iface)
    can_up = can_present if variant == "dm" else (await asyncio.to_thread(_can_is_up, can_iface) if can_present else False)
    if skip_motor_scan:
        motors = list(_last_motor_scan)
        scan_stale = True
        online = sum(1 for m in motors if m.online) if motors else 0
    else:
        motors = await scan_motors(can_iface, arm_variant=variant) if can_up else []
        online = sum(1 for m in motors if m.online)
        scan_stale = False
    cal = _calibration_status(arm_variant=variant)
    gw = _pgrep_running("motorbridge-gateway") or _pgrep_running("ws_gateway")
    cameras_available = 0
    # Skip camera probe when CAN is absent — health is already "not ready".
    if can_present:
        try:
            from .camera import probe_status_async

            camera_status = await probe_status_async()
            cameras_available = int(camera_status.get("usable_count") or 0)
        except Exception as exc:
            logger.debug("camera probe in health: %s", exc)

    leader_ok = Path(leader).exists()
    gripper_ok = any(m.motor_id == 7 and m.online for m in motors)
    hardware_connected = can_up and leader_ok and online >= B601_MIN_MOTORS_TELEOP
    ready_for_teleop = (
        hardware_connected
        and cal.follower
        and cal.leader
        and (not scan_stale or online >= B601_MIN_MOTORS_TELEOP)
    )

    issues: List[str] = []
    if not can_present:
        issues.append(f"未检测到 DM USB-CAN 串口（{can_iface} 不存在）" if variant == "dm" else "未检测到 PCAN-USB（can0 不存在）")
    elif not can_up:
        issues.append("DM 串口已插入但不可用 — 请拔插 USB-CAN 或检查权限" if variant == "dm" else "CAN 已插入但未就绪 — 在下方输入本机登录密码后点「连接从臂」，或展开复制终端命令")
    if not leader_ok:
        issues.append("主臂 USB 未检测到")
    if can_up and not scan_stale and online < 7 and online >= B601_MIN_MOTORS_TELEOP:
        missing = [m.motor_id for m in motors if not m.online]
        labels = [
            B601_JOINT_LABELS_ZH.get(_B601_JOINT_NAMES[i - 1], f"电机{i}") for i in missing
        ]
        issues.append(
            f"部分关节掉线（{online}/7：缺 {', '.join(labels)}）— 仍可遥操，掉线关节不会动"
        )
    elif can_up and not scan_stale and online < B601_MIN_MOTORS_TELEOP:
        missing = [m.motor_id for m in motors if not m.online]
        labels = [
            B601_JOINT_LABELS_ZH.get(_B601_JOINT_NAMES[i - 1], f"电机{i}") for i in missing
        ]
        if 7 in missing:
            issues.append(
                f"夹爪掉线（{online}/7）— 请关闭从臂 48V 电源 5 秒再打开，然后点「开始遥操」"
            )
        elif missing:
            issues.append(
                f"从臂电机在线 {online}/7（掉线：{', '.join(labels)}）— 确认 48V 已开，可点「重新扫描从臂」"
            )
    if hardware_connected and (not cal.follower or not cal.leader):
        missing = []
        if not cal.follower:
            missing.append("从臂")
        if not cal.leader:
            missing.append("主臂")
        issues.append(
            f"所选标定文件缺失：从臂「{cal.robot_id}」"
            f"{' ✓' if cal.follower else ' ✗'}"
            f" · 主臂「{cal.leader_id}」"
            f"{' ✓' if cal.leader else ' ✗'} — 可在下方切换或新建标定"
        )

    power_hint = None
    if can_up and not scan_stale and online == 0:
        power_hint = "请确认 48V 电源已打开"
    elif can_up and not scan_stale and not gripper_ok and online > 0:
        power_hint = "夹爪（ID7）无响应：关闭从臂 48V → 等 5 秒 → 再打开 → 再点「连接 CAN 并扫描从臂」"
    elif scan_stale and skip_motor_scan:
        power_hint = "遥操占用 CAN，电机数为上次扫描结果"

    return HealthResponse(
        ok=hardware_connected,
        ready_for_teleop=ready_for_teleop,
        arm_variant=variant,
        follower_type=follower_type,
        follower_transport=transport,
        follower_port=can_iface,
        can_up=can_up,
        can_present=can_present,
        can_iface=can_iface,
        leader_present=leader_ok,
        leader_port=leader,
        motors_online=online,
        motors=motors,
        motors_scan_stale=scan_stale,
        calibration_follower=cal.follower,
        calibration_leader=cal.leader,
        robot_id=cal.robot_id,
        leader_id=cal.leader_id,
        motorbridge_cli=_cli_on_path("motorbridge-cli"),
        lerobot_teleoperate=_cli_on_path("lerobot-teleoperate"),
        gateway_running=gw,
        cameras_available=cameras_available,
        power_hint=power_hint,
        issues=issues,
    )


LIVE_JOINTS_PATH = (
    Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp") / "b601_joints_live.json"
    if sys.platform == "win32"
    else Path("/tmp/b601_joints_live.json")
)


def _read_live_joints_file() -> Dict[str, float]:
    """Read joints dumped by b601_teleop_launcher (zero extra CAN traffic)."""
    try:
        if LIVE_JOINTS_PATH.exists():
            age = time.time() - LIVE_JOINTS_PATH.stat().st_mtime
            if age < 5.0:
                data = json.loads(LIVE_JOINTS_PATH.read_text(encoding="utf-8"))
                joints = data.get("joints") or {}
                if isinstance(joints, dict) and joints:
                    out: Dict[str, float] = {}
                    for key, val in joints.items():
                        try:
                            pos = float(val)
                        except (TypeError, ValueError):
                            continue
                        if math.isfinite(pos):
                            out[str(key)] = pos
                    return out
    except Exception as exc:
        logger.debug("live joints read failed: %s", exc)
    return {}


async def get_b601_runtime_state(can_iface: str = DEFAULT_CAN) -> Dict[str, Any]:
    """Aggregate teleop status + joints + health for robots.py generic state API."""
    variant = _resolve_arm_variant(None)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    teleop_on = bool(_teleop_proc and _teleop_proc.is_alive())
    starting = _teleop_start_in_progress()
    joints: Dict[str, float] = {}
    if teleop_on:
        joints = _read_live_joints_file()
    elif not starting and variant == "rs":
        joints = await poll_follower_joints(port)
    health = await _build_health(port, arm_variant=variant, skip_motor_scan=teleop_on or starting)
    runtime = b601_runtime_lock.status_dict()
    if teleop_on:
        runtime["runtime_mode"] = RuntimeMode.TELEOP.value
    elif _record_proc and _record_proc.is_alive():
        runtime["runtime_mode"] = RuntimeMode.RECORD.value
    elif _calibrate_proc and _calibrate_proc.is_alive():
        runtime["runtime_mode"] = RuntimeMode.CALIBRATE.value
    elif _inference_proc and _inference_proc.is_alive():
        runtime["runtime_mode"] = RuntimeMode.INFERENCE.value
    return {
        "type": "robot_state",
        "robot_id": health.robot_id,
        "runtime_id": f"b601_{variant}",
        "timestamp": time.time(),
        "connected": health.ok,
        "teleop_running": teleop_on,
        "teleop_starting": starting,
        "joints": joints,
        "health": health.model_dump(),
        "stream_interval_s": 0.1 if teleop_on else 1.0,
        **runtime,
    }


async def stream_b601_state(websocket: WebSocket) -> None:
    """Push B601 state — ~60Hz joints during teleop, 1Hz full health when idle."""
    await websocket.accept()
    try:
        while True:
            teleop_on = bool(_teleop_proc and _teleop_proc.is_alive())
            if teleop_on:
                joints = _read_live_joints_file()
                await websocket.send_json({
                    "type": "robot_state",
                    "runtime_id": "b601_rs",
                    "timestamp": time.time(),
                    "teleop_running": True,
                    "joints": joints,
                    "stream_interval_s": 0.016,
                })
                await asyncio.sleep(0.016)
            else:
                payload = await get_b601_runtime_state()
                await websocket.send_json(payload)
                await asyncio.sleep(float(payload.get("stream_interval_s") or 1.0))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("b601 state websocket closed")


class ProbeRequest(BaseModel):
    can_iface: Optional[str] = None
    wake_follower: bool = False
    sudo_password: Optional[str] = Field(
        default=None,
        description="Optional sudo password for CAN setup; sent to localhost agent only, never stored",
    )


class CanUpRequest(BaseModel):
    can_iface: Optional[str] = None
    sudo_password: Optional[str] = Field(default=None, description="Optional sudo password; never stored")


def _teleop_start_in_progress() -> bool:
    return _teleop_start_task is not None and not _teleop_start_task.done()


async def _abort_teleop_start(*, can: Optional[str] = None, leader: Optional[str] = None) -> None:
    """Cancel in-flight teleop boot and kill launcher processes (for one-click restart)."""
    global _teleop_proc, _teleop_start_task, _teleop_start_error

    if _teleop_start_task and not _teleop_start_task.done():
        _teleop_start_task.cancel()
        try:
            await _teleop_start_task
        except asyncio.CancelledError:
            pass
        _teleop_start_task = None

    proc = _teleop_proc
    _teleop_proc = None
    _teleop_start_error = None

    if proc and proc._proc and proc._proc.poll() is None:
        try:
            await asyncio.to_thread(proc.stop, 3.0)
        except Exception:
            pass
        try:
            await port_lock_manager.release_for_process(proc.session_id)
        except Exception:
            pass
        if isinstance(proc, B601TeleopCLI):
            try:
                await port_lock_manager.release([proc._leader, proc._can])
            except Exception:
                pass

    await asyncio.to_thread(_reap_zombie_teleop_procs)
    await asyncio.sleep(0.25)

    stale: List[str] = []
    for p in (leader, can):
        if not p:
            continue
        busy, owner = port_lock_manager.is_port_busy(p)
        if busy and owner == "b601-teleop":
            stale.append(p)
    if stale:
        await port_lock_manager.release(stale)

    try:
        await b601_runtime_lock.release(RuntimeMode.TELEOP)
    except Exception:
        pass


async def _prepare_follower_for_teleop(can: str, *, arm_variant: Optional[str] = None) -> None:
    """Bring CAN up + confirm enough joints are online.

    The teleop launcher itself disables/ensure_mode/enables each online motor
    per-joint, so we do NOT run the full ``recover_follower`` here on the happy
    path — that added ~30s (3×2000ms retries on a dead gripper) for nothing.
    ``_ensure_motors_online_for_teleop`` only recovers if we're below the min.
    """
    variant = _resolve_arm_variant(arm_variant)
    async with _b601_can_exclusive():
        if variant == "rs":
            _kill_gateway()
        await asyncio.sleep(0.35)
        if variant == "rs" and not _can_is_up(can):
            up = await can_up(can)
            if not up.ok:
                raise RuntimeError(up.message)
        await _ensure_motors_online_for_teleop(can, arm_variant=variant)
        await asyncio.sleep(0.2)


@router.post("/probe", response_model=HealthResponse)
async def b601_probe(body: Optional[ProbeRequest] = None) -> HealthResponse:
    """Official first-run path: bring CAN up (sudo), optionally recover follower, rescan."""
    req = body or ProbeRequest()
    variant = _resolve_arm_variant(None)
    can = _resolve_follower_port(arm_variant=variant, can_iface=req.can_iface)
    if _teleop_start_in_progress():
        # Do not touch CAN while teleop is starting — avoids disable_all ack timeout.
        return await _build_health(can, arm_variant=variant)
    can_setup_msg: Optional[str] = None
    if variant == "rs" and _can_iface_present(can) and not _can_is_up(can):
        result = await can_up(can, sudo_password=req.sudo_password)
        if not result.ok:
            can_setup_msg = result.message
    if req.wake_follower:
        await recover_follower(can, arm_variant=variant)
    health = await _build_health(can, arm_variant=variant)
    if can_setup_msg:
        return health.model_copy(update={"issues": [can_setup_msg, *health.issues]})
    return health


@router.get("/scan", response_model=List[MotorScanItem])
async def b601_scan(can_iface: str = DEFAULT_CAN, arm_variant: Optional[str] = None) -> List[MotorScanItem]:
    if _teleop_start_in_progress() or (_teleop_proc and _teleop_proc.is_alive()):
        raise HTTPException(
            status_code=409,
            detail="遥操进行中 — 请先停止遥操再扫描电机（避免 CAN 冲突）",
        )
    variant = _resolve_arm_variant(arm_variant)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    return await scan_motors(port, arm_variant=variant)


@router.get("/motors/diagnose", response_model=MotorDiagnoseResponse)
async def b601_motors_diagnose(can_iface: str = DEFAULT_CAN, arm_variant: Optional[str] = None) -> MotorDiagnoseResponse:
    """逐 ID ping 1..7（只读，不写寄存器/不改 ID）。对齐 Seeed getting-started 成品套件检测流程。"""
    if _teleop_start_in_progress() or (_teleop_proc and _teleop_proc.is_alive()):
        raise HTTPException(
            status_code=409,
            detail="遥操进行中 — 请先停止遥操再诊断电机",
        )
    variant = _resolve_arm_variant(arm_variant)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    return await diagnose_motors(port, arm_variant=variant)


@router.post("/can/up", response_model=CanUpResponse)
async def b601_can_up(body: Optional[CanUpRequest] = None) -> CanUpResponse:
    req = body or CanUpRequest()
    variant = _resolve_arm_variant(None)
    port = _resolve_follower_port(arm_variant=variant, can_iface=req.can_iface)
    if variant == "dm":
        ok = Path(port).exists()
        return CanUpResponse(ok=ok, message="DM 串口已就绪" if ok else f"DM 串口未找到: {port}", iface=port)
    return await can_up(port, sudo_password=req.sudo_password)


@router.post("/recover", response_model=RecoverResponse)
async def b601_recover(can_iface: str = DEFAULT_CAN, arm_variant: Optional[str] = None) -> RecoverResponse:
    variant = _resolve_arm_variant(arm_variant)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    return await recover_follower(port, arm_variant=variant)


@router.post("/disable", response_model=RecoverResponse)
async def b601_disable(can_iface: str = DEFAULT_CAN, arm_variant: Optional[str] = None) -> RecoverResponse:
    """Release follower holding torque (official motorbridge disable)."""
    variant = _resolve_arm_variant(arm_variant)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    return await disable_follower(port, arm_variant=variant)


@router.get("/calibration", response_model=CalibrationStatus)
async def b601_calibration() -> CalibrationStatus:
    return _calibration_status()


@router.post("/calibrate/start", response_model=SessionStatus)
async def b601_calibrate_start(body: CalibrateStartRequest) -> SessionStatus:
    global _calibrate_proc, _calibrate_target
    target = body.target.lower().strip()
    if target not in ("follower", "leader"):
        raise HTTPException(status_code=400, detail="target 必须是 follower 或 leader")

    if _calibrate_proc and _calibrate_proc.is_alive():
        raise HTTPException(status_code=409, detail="校准已在进行中")

    _require_runtime_idle(RuntimeMode.CALIBRATE)

    if _teleop_proc and _teleop_proc.is_alive():
        raise HTTPException(status_code=409, detail="请先停止遥操再校准")

    variant = _resolve_arm_variant(body.arm_variant)
    can = _resolve_follower_port(arm_variant=variant, explicit=body.follower_port, can_iface=body.can_iface)
    leader = _resolve_leader(body.leader_port)
    if target == "leader" and not Path(leader).exists():
        raise HTTPException(status_code=503, detail=f"主臂未连接: {leader}")

    if variant == "rs" and not _can_is_up(can):
        up = await can_up(can)
        if not up.ok:
            raise HTTPException(status_code=503, detail=up.message)
    if variant == "dm" and not Path(can).exists():
        raise HTTPException(status_code=503, detail=f"DM USB-CAN 串口未连接: {can}")

    proc = B601CalibrateCLI(
        target=target,
        leader_port=leader,
        follower_port=can,
        arm_variant=variant,
        robot_id=_resolve_robot_id(body.robot_id),
        leader_id=_resolve_leader_id(body.leader_id),
    )
    try:
        await asyncio.to_thread(
            proc.start,
            15.0,
            keep_stdin_open=True,
            auto_accept_prompts=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    _calibrate_proc = proc
    _calibrate_target = target
    await b601_runtime_lock.acquire(RuntimeMode.CALIBRATE, "calibrate")
    return _proc_status(proc, "calibrate")


@router.post("/calibrate/continue", response_model=SessionStatus)
async def b601_calibrate_continue() -> SessionStatus:
    if _calibrate_proc is None or not _calibrate_proc.is_alive():
        raise HTTPException(status_code=409, detail="没有进行中的校准")
    try:
        await asyncio.to_thread(_calibrate_proc.send_stdin, "\n")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _proc_status(_calibrate_proc, "calibrate")


@router.post("/calibrate/stop", response_model=SessionStatus)
async def b601_calibrate_stop() -> SessionStatus:
    global _calibrate_proc, _calibrate_target
    if _calibrate_proc:
        await asyncio.to_thread(_calibrate_proc.stop, 6.0)
        _calibrate_proc = None
        _calibrate_target = None
    await b601_runtime_lock.release(RuntimeMode.CALIBRATE)
    return SessionStatus(running=False, role="calibrate")


@router.get("/calibrate/status", response_model=SessionStatus)
async def b601_calibrate_status() -> SessionStatus:
    return _proc_status(_calibrate_proc, "calibrate")


@router.get("/joints", response_model=JointsResponse)
async def b601_joints(can_iface: str = DEFAULT_CAN) -> JointsResponse:
    teleop_on = bool(_teleop_proc and _teleop_proc.is_alive())
    if teleop_on:
        joints = _read_live_joints_file()
        if joints:
            return JointsResponse(ok=True, teleop_running=True, joints=joints)
        return JointsResponse(ok=False, teleop_running=True, joints={})
    variant = _resolve_arm_variant(None)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    if variant == "dm":
        return JointsResponse(ok=False, teleop_running=False, joints={})
    joints = await poll_follower_joints(port)
    return JointsResponse(ok=bool(joints), teleop_running=False, joints=joints)


@router.get("/cameras", response_model=List[CameraDevice])
async def b601_cameras() -> List[CameraDevice]:
    try:
        from .camera import probe_status_async

        status = await probe_status_async()
        devices = status.get("nodes", [])
        out: List[CameraDevice] = []
        for d in devices:
            idx = int(d.get("index", 0))
            out.append(
                CameraDevice(
                    index=idx,
                    path=str(d.get("path", "")),
                    name=str(d.get("name") or ""),
                    readable=bool(d.get("readable")),
                    busy=not bool(d.get("opened")),
                    usb_bus=_camera_usb_bus(idx),
                )
            )
        return out
    except Exception as exc:
        logger.debug("b601 cameras: %s", exc)
        return []


@router.get("/urdf/health", response_model=UrdfHealthResponse)
async def b601_urdf_health() -> UrdfHealthResponse:
    urdf_path = _URDF_ROOT / "b601_rs.urdf"
    if not urdf_path.is_file():
        return UrdfHealthResponse(ok=False, mesh_total=0, mesh_present=0, missing=["b601_rs.urdf"])
    text = urdf_path.read_text(encoding="utf-8", errors="replace")
    meshes = sorted(set(re.findall(r'assets/([^"]+\.STL)"', text, re.I)))
    assets = _URDF_ROOT / "assets"
    missing = [m for m in meshes if not (assets / m).is_file()]
    present = len(meshes) - len(missing)
    return UrdfHealthResponse(
        ok=len(missing) == 0,
        mesh_total=len(meshes),
        mesh_present=present,
        missing=missing,
    )


@router.get("/teleop/preflight", response_model=TeleopPreflightResponse)
async def b601_teleop_preflight(
    can_iface: str = DEFAULT_CAN,
    robot_id: Optional[str] = None,
    leader_id: Optional[str] = None,
    arm_variant: Optional[str] = None,
) -> TeleopPreflightResponse:
    """Resolve active calibration ids + follower pose before teleop (safety)."""
    rid = _resolve_robot_id(robot_id)
    lid = _resolve_leader_id(leader_id)
    variant = _resolve_arm_variant(arm_variant)
    cal = _calibration_status(robot_id=rid, leader_id=lid, arm_variant=variant)
    warnings: List[str] = []
    if not cal.follower:
        warnings.append(f"从臂标定文件不存在：{rid}.json")
    if not cal.leader:
        warnings.append(f"主臂标定文件不存在：{lid}.json")
    joints: Dict[str, float] = {}
    # 不在 preflight 读 CAN 关节 —— 会抢总线且导致前端 10s 超时；官方 teleoperate 自行 connect。
    if _teleop_proc and _teleop_proc.is_alive() and isinstance(_teleop_proc, B601TeleopCLI):
        if _teleop_proc._robot_id != rid or _teleop_proc._leader_id != lid:
            warnings.append(
                f"已有遥操进程在使用 {_teleop_proc._robot_id} / {_teleop_proc._leader_id}，"
                f"与当前选择 {rid} / {lid} 不一致，启动时会强制重启"
            )
    return TeleopPreflightResponse(
        ok=bool(cal.follower and cal.leader),
        robot_id=rid,
        leader_id=lid,
        follower_cal_path=cal.follower_path,
        leader_cal_path=cal.leader_path,
        calibration_follower=cal.follower,
        calibration_leader=cal.leader,
        follower_joints=joints,
        warnings=warnings,
    )


@router.get("/teleop/alignment", response_model=B601AlignmentResponse)
async def b601_teleop_alignment(
    can_iface: str = DEFAULT_CAN,
    robot_id: Optional[str] = None,
    leader_id: Optional[str] = None,
    leader_port: Optional[str] = None,
    arm_variant: Optional[str] = None,
) -> B601AlignmentResponse:
    variant = _resolve_arm_variant(arm_variant)
    if variant == "dm":
        return B601AlignmentResponse(
            ok=True,
            tolerance_deg=B601_ALIGN_TOLERANCE_DEG,
            skipped=True,
            skip_reason="DM 从臂暂不做网页对齐读数；启动前请手动把主从臂摆到近似姿态",
            robot_id=_resolve_robot_id(robot_id),
            leader_id=_resolve_leader_id(leader_id),
        )
    rid = _resolve_robot_id(robot_id)
    lid = _resolve_leader_id(leader_id)
    leader = _resolve_leader(leader_port)
    return await _b601_alignment_report(
        can=can_iface,
        leader_port=leader,
        robot_id=rid,
        leader_id=lid,
    )


@router.post("/teleop/start", response_model=SessionStatus)
async def b601_teleop_start(body: TeleopStartRequest) -> SessionStatus:
    global _teleop_proc, _teleop_start_task, _teleop_start_error

    variant = _resolve_arm_variant(body.arm_variant)
    can = _resolve_follower_port(arm_variant=variant, explicit=body.follower_port, can_iface=body.can_iface)
    leader = _resolve_leader(body.leader_port)
    if body.robot_id or body.leader_id or body.arm_variant or body.follower_port:
        _save_prefs(arm_variant=variant, follower_port=can if variant == "dm" else None, robot_id=body.robot_id, leader_id=body.leader_id)
    robot_id = _resolve_robot_id(body.robot_id)
    leader_id = _resolve_leader_id(body.leader_id)

    cal = _calibration_status(robot_id=robot_id, leader_id=leader_id, arm_variant=variant)
    if not cal.follower:
        raise HTTPException(
            status_code=400,
            detail=f"从臂标定文件不存在：{robot_id}.json — 请在下拉框选择正确 ID 或重新标定",
        )
    if not cal.leader:
        raise HTTPException(
            status_code=400,
            detail=f"主臂标定文件不存在：{leader_id}.json — 请先完成主臂标定",
        )

    if not b601_runtime_lock.is_busy() or b601_runtime_lock.mode == RuntimeMode.GRAVITY_COMP:
        await stop_gravity_comp_if_running(can)
        await asyncio.sleep(0.35)

    _require_runtime_idle(RuntimeMode.TELEOP)

    if _teleop_proc and _teleop_proc.is_alive() and not body.restart:
        same_ids = (
            isinstance(_teleop_proc, B601TeleopCLI)
            and _teleop_proc._arm_variant == variant
            and _teleop_proc._robot_id == robot_id
            and _teleop_proc._leader_id == leader_id
        )
        if same_ids:
            status = _proc_status(_teleop_proc, "teleop")
            if status.running and status.healthy:
                return status

    if body.restart and (_teleop_start_in_progress() or (_teleop_proc and _teleop_proc.is_alive())):
        await _abort_teleop_start(can=can, leader=leader)
    elif _teleop_start_in_progress():
        tail = list(_teleop_proc.log_tail) if _teleop_proc else []
        if not tail:
            tail = ["正在启动遥操…"]
        return SessionStatus(
            running=False,
            starting=True,
            role="teleop",
            robot_id=robot_id,
            leader_id=leader_id,
            log_tail=tail[-20:],
            last_error=_teleop_start_error,
        )

    await _reap_b601_teleop(leader=leader, can=can)

    if _teleop_proc and _teleop_proc._proc and _teleop_proc._proc.poll() is None:
        same_ids = (
            isinstance(_teleop_proc, B601TeleopCLI)
            and _teleop_proc._arm_variant == variant
            and _teleop_proc._robot_id == robot_id
            and _teleop_proc._leader_id == leader_id
        )
        if body.restart or not same_ids:
            await asyncio.to_thread(_teleop_proc.stop, 4.0)
            await port_lock_manager.release_for_process(_teleop_proc.session_id)
            _teleop_proc = None
            await asyncio.sleep(0.5)
        elif same_ids:
            status = _proc_status(_teleop_proc, "teleop")
            if status.healthy:
                return status

    _teleop_start_error = None
    _teleop_start_task = asyncio.create_task(
        _b601_teleop_start_worker(
            can=can,
            arm_variant=variant,
            leader=leader,
            robot_id=robot_id,
            leader_id=leader_id,
            body=body,
            cal=cal,
        )
    )
    return SessionStatus(
        running=False,
        starting=True,
        role="teleop",
        robot_id=robot_id,
        leader_id=leader_id,
        follower_cal_path=cal.follower_path,
        leader_cal_path=cal.leader_path,
        log_tail=["正在连接从臂并启动遥操（约 30–60 秒，会有电机声）…"],
    )


async def _b601_teleop_start_worker(
    *,
    can: str,
    arm_variant: str,
    leader: str,
    robot_id: str,
    leader_id: str,
    body: TeleopStartRequest,
    cal: CalibrationStatus,
) -> None:
    global _teleop_proc, _teleop_start_error, _teleop_start_task
    proc: Optional[B601TeleopCLI] = None
    last_exc: Optional[Exception] = None

    def _friendly_teleop_err(exc: Exception, tail: List[str]) -> str:
        text = str(exc) + "\n" + "\n".join(tail[-8:])
        if "disable_all failed" in text or "control ack timeout" in text:
            return (
                "从臂 CAN 暂时无响应。请再点一次「开始遥操」，系统会自动唤醒并重试。"
            )
        if "0x7005" in text or "夹爪" in text or "gripper" in text.lower():
            return "部分关节未就绪，正在重试…"
        if "exited with code" in text:
            return text.split("Recent output:")[0].strip() or text[:300]
        return str(exc)[:400]

    try:
        logger.warning(
            "[b601] teleop start robot.id=%s leader.id=%s follower_cal=%s leader_cal=%s",
            robot_id,
            leader_id,
            cal.follower_path,
            cal.leader_path,
        )

        def _retryable_teleop_err(text: str) -> bool:
            low = text.lower()
            return any(
                tok in low
                for tok in (
                    "disable_all failed",
                    "control ack timeout",
                    "0x7005",
                    "ensure_mode failed",
                    "gripper",
                    "configure did not complete",
                )
            )

        for attempt in range(3):
            proc = None
            try:
                await _prepare_follower_for_teleop(can, arm_variant=arm_variant)

                if body.use_cameras:
                    try:
                        from .camera import stop_all_streams

                        await asyncio.to_thread(stop_all_streams)
                        await asyncio.sleep(0.25)
                    except Exception as exc:
                        logger.debug("b601 teleop stop camera streams: %s", exc)

                if body.check_alignment and not body.force:
                    align = await _b601_alignment_report(
                        can=can,
                        leader_port=leader,
                        robot_id=robot_id,
                        leader_id=leader_id,
                    )
                    if not align.skipped and not align.ok:
                        raise RuntimeError("主从臂未对齐 — 请调整主臂后重试")

                await port_lock_manager.acquire([leader, can], owner="b601-teleop", mode="subprocess")

                proc = B601TeleopCLI(
                    leader_port=leader,
                    follower_port=can,
                    arm_variant=arm_variant,
                    robot_id=robot_id,
                    leader_id=leader_id,
                    display_data=body.display_data,
                    use_cameras=body.use_cameras,
                    camera_indices=body.camera_indices if body.use_cameras else None,
                    fps=body.fps or DEFAULT_TELEOP_FPS,
                )
                _teleop_proc = proc
                await asyncio.to_thread(proc.start, 45.0)
                await b601_runtime_lock.acquire(RuntimeMode.TELEOP, "teleop")
                await port_lock_manager.register_process(proc.session_id, [leader, can])
                _teleop_start_error = None
                return
            except Exception as exc:
                last_exc = exc
                tail = proc.log_tail if proc else []
                if proc and proc._proc and proc._proc.poll() is None:
                    await asyncio.to_thread(proc.stop, 4.0)
                proc = None
                _teleop_proc = None
                try:
                    await port_lock_manager.release([leader, can])
                except Exception:
                    pass
                text = str(exc) + "\n".join(tail)
                if attempt < 2 and _retryable_teleop_err(text):
                    logger.warning(
                        "[b601] teleop configure failed (attempt %s), recover + retry: %s",
                        attempt + 1,
                        exc,
                    )
                    await recover_follower(can, arm_variant=arm_variant)
                    await asyncio.sleep(1.5 + attempt)
                    continue
                raise

        if last_exc:
            raise last_exc
    except Exception as exc:
        tail = proc.log_tail if proc else []
        _teleop_start_error = _friendly_teleop_err(exc, tail)
        logger.warning("[b601] teleop start failed: %s", _teleop_start_error)
        if proc and proc._proc and proc._proc.poll() is None:
            await asyncio.to_thread(proc.stop, 4.0)
        _teleop_proc = None
        try:
            await port_lock_manager.release([leader, can])
        except Exception:
            pass
    finally:
        _teleop_start_task = None


@router.post("/teleop/stop", response_model=SessionStatus)
async def b601_teleop_stop(can_iface: str = DEFAULT_CAN) -> SessionStatus:
    global _teleop_proc, _teleop_start_task, _teleop_start_error
    if _teleop_start_task and not _teleop_start_task.done():
        _teleop_start_task.cancel()
        try:
            await _teleop_start_task
        except asyncio.CancelledError:
            pass
        _teleop_start_task = None
    _teleop_start_error = None
    proc = _teleop_proc
    _teleop_proc = None

    async def _kill_teleop() -> None:
        if not proc:
            return
        try:
            await port_lock_manager.release_for_process(proc.session_id)
        except Exception as exc:
            logger.debug("teleop stop release ports: %s", exc)
        p = proc._proc
        if p is None or p.poll() is not None:
            return

        # Step 1: SIGINT (== Ctrl+C) so lerobot runs its finally: block,
        # which calls robot.disconnect() with disable_torque_on_disconnect=True.
        # This gracefully releases motor torque; SIGKILL would skip it and
        # leave motors in MIT mode with Kp=150 → twitching on sensor noise.
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGINT)
        except Exception as exc:
            logger.warning("[b601] teleop SIGINT: %s", exc)

        # Step 2: wait up to 3s for clean exit
        for _ in range(30):
            await asyncio.sleep(0.1)
            if p.poll() is not None:
                return

        # Step 3: SIGTERM, wait 1s
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
        for _ in range(10):
            await asyncio.sleep(0.1)
            if p.poll() is not None:
                return

        # Step 4: SIGKILL as last resort
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except Exception as exc:
            logger.warning("[b601] teleop SIGKILL: %s", exc)
            try:
                p.kill()
            except Exception:
                pass

    await _kill_teleop()
    # Disable the follower BEFORE releasing the runtime lock. If we released
    # first, gravity-comp (or any op) could acquire the lock and re-enable the
    # motors in the gap, and then this disable_follower would kill torque on
    # them → the arm floats for an instant then drops. Disabling while we still
    # hold the lock guarantees the motors are safely de-energized before anyone
    # else can touch the bus.
    try:
        variant = proc._arm_variant if isinstance(proc, B601TeleopCLI) else _resolve_arm_variant(None)
        port = proc._can if isinstance(proc, B601TeleopCLI) else _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
        await disable_follower(port, arm_variant=variant)
    except Exception as exc:
        logger.warning("[b601] teleop stop disable: %s", exc)
    await b601_runtime_lock.release(RuntimeMode.TELEOP)
    # Clean up live joints file so /api/b601/joints stops returning stale data
    # and the 3D viewer doesn't keep showing the last teleop pose.
    try:
        if LIVE_JOINTS_PATH.exists():
            LIVE_JOINTS_PATH.unlink()
    except Exception:
        pass
    return SessionStatus(running=False, role="teleop")


@router.get("/teleop/status", response_model=SessionStatus)
async def b601_teleop_status() -> SessionStatus:
    await _reap_b601_teleop()
    if _teleop_start_task and not _teleop_start_task.done():
        tail = list(_teleop_proc.log_tail) if _teleop_proc else []
        if not tail:
            tail = ["正在连接从臂并启动遥操…"]
        return SessionStatus(
            running=False,
            starting=True,
            role="teleop",
            log_tail=tail[-20:],
            last_error=_teleop_start_error,
        )
    if _teleop_start_error and not (_teleop_proc and _teleop_proc.is_alive()):
        return SessionStatus(
            running=False,
            starting=False,
            role="teleop",
            healthy=False,
            last_error=_teleop_start_error,
            log_tail=_teleop_proc.log_tail if _teleop_proc else [],
        )
    return _proc_status(_teleop_proc, "teleop")


@router.post("/record/start", response_model=SessionStatus)
async def b601_record_start(body: RecordStartRequest) -> SessionStatus:
    global _record_proc, _record_phase_started_at, _record_phase_last, _record_episode_sticky
    _record_phase_started_at = time.time()
    _record_phase_last = "starting"
    _record_episode_sticky = None
    if _teleop_proc and _teleop_proc._proc and _teleop_proc._proc.poll() is None:
        raise HTTPException(status_code=409, detail="请先停止遥操再录制")

    _require_runtime_idle(RuntimeMode.RECORD)

    variant = _resolve_arm_variant(body.arm_variant)
    can = _resolve_follower_port(arm_variant=variant, explicit=body.follower_port, can_iface=body.can_iface)
    leader = _resolve_leader(body.leader_port)
    # Drop leases from a previous finished record (rc=0 / crash) so restart works
    # without forcing the user to click「停止采集」.
    await _reap_b601_record(leader=leader, can=can, keep_status=False)
    await _reap_b601_teleop(leader=leader, can=can)
    if variant == "rs":
        _kill_gateway()
    if variant == "rs" and not _can_is_up(can):
        await can_up(can)
    await recover_follower(can, arm_variant=variant)

    # Release any BotverseX MJPEG/snapshot streams so lerobot can open V4L2.
    try:
        from .camera import stop_all_streams

        await asyncio.to_thread(stop_all_streams)
        # Give UVC drivers time to fully release after MJPEG/preview teardown.
        await asyncio.sleep(0.6)
    except Exception as exc:
        logger.debug("b601 record stop camera streams: %s", exc)

    cam_err = await asyncio.to_thread(_validate_cameras_concurrent, list(body.camera_indices or []))
    if cam_err:
        raise HTTPException(status_code=409, detail=cam_err)

    try:
        await port_lock_manager.acquire([leader, can], owner="b601-record", mode="subprocess")
    except PortInUseError as exc:
        owner = getattr(exc, "owner", "") or "unknown"
        hint = (
            "请点「停止采集」"
            if "record" in owner
            else "请点「停止遥操」"
            if "teleop" in owner
            else "请先停止占用该串口的操作"
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"串口 {exc.port} 仍被 {owner} 占用（进程可能已结束）。"
                f"{hint}，或等 2 秒后重试。"
            ),
        ) from exc

    repo_id = _fresh_repo_id(body.repo_id)
    if repo_id != body.repo_id:
        logger.info(
            "[b601] dataset %s already exists on disk — using fresh id %s",
            body.repo_id,
            repo_id,
        )

    proc = B601RecordCLI(
        leader_port=leader,
        follower_port=can,
        arm_variant=variant,
        robot_id=_resolve_robot_id(body.robot_id),
        leader_id=_resolve_leader_id(body.leader_id),
        repo_id=repo_id,
        single_task=body.single_task,
        num_episodes=body.num_episodes,
        episode_time_s=body.episode_time_s,
        reset_time_s=body.reset_time_s,
        camera_indices=body.camera_indices,
    )
    try:
        await asyncio.to_thread(proc.start)
    except Exception as exc:
        await port_lock_manager.release([leader, can])
        msg = str(exc)
        if "FileExistsError" in msg or "File exists" in msg:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"数据集目录已存在（{body.repo_id}）。"
                    "请点「换一个」生成新 ID 后再开始采集；"
                    "或删除 ~/.cache/huggingface/lerobot/ 下对应文件夹。"
                ),
            ) from exc
        raise HTTPException(status_code=500, detail=msg) from exc

    _record_proc = proc
    await b601_runtime_lock.acquire(RuntimeMode.RECORD, "record")
    await port_lock_manager.register_process(proc.session_id, [leader, can])
    status = _proc_status(proc, "record")
    if repo_id != body.repo_id:
        status.phase_hint = (
            f"原 ID「{body.repo_id}」已存在，已自动改用「{repo_id}」开始采集。"
        )
    return status


@router.post("/record/stop", response_model=SessionStatus)
async def b601_record_stop(can_iface: str = DEFAULT_CAN) -> SessionStatus:
    global _record_proc
    leader: Optional[str] = None
    follower: Optional[str] = None
    if _record_proc:
        if isinstance(_record_proc, B601RecordCLI):
            leader = str(_record_proc._kwargs.get("leader_port") or "") or None
            follower = str(_record_proc._kwargs.get("follower_port") or "") or None
        await asyncio.to_thread(_record_proc.stop, 8.0)
        await port_lock_manager.release_for_process(_record_proc.session_id)
        if leader or follower:
            await port_lock_manager.release([p for p in (leader, follower) if p])
        _record_proc = None
    variant = _resolve_arm_variant(None)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    await _reap_b601_record(leader=leader, can=port, keep_status=False)
    await b601_runtime_lock.release(RuntimeMode.RECORD)
    await disable_follower(port, arm_variant=variant)
    return SessionStatus(running=False, role="record")


@router.get("/record/status", response_model=SessionStatus)
async def b601_record_status() -> SessionStatus:
    # Auto-free ports after natural exit so the next start/teleop is not blocked.
    await _reap_b601_record(keep_status=True)
    return _proc_status(_record_proc, "record")


def _inject_record_right_arrow() -> str:
    """Tell lerobot-record to exit_early (skip rest of episode/reset).

    Official LeRobot listens for Right Arrow via pynput globally. We synthesize
    the same keypress from the agent process (same machine / DISPLAY).
    """
    os.environ.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        kb.press(Key.right)
        kb.release(Key.right)
        return "pynput"
    except Exception as exc:
        logger.warning("pynput Right failed: %s", exc)

    display = os.environ.get("DISPLAY") or ":0"
    env = os.environ.copy()
    env["DISPLAY"] = display
    if shutil.which("xdotool"):
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "Right"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return "xdotool"

    raise RuntimeError(
        "无法从网页注入方向键。请直接在键盘上按 →（右方向键）跳过复位/本段；"
        "或安装 xdotool 后重试按钮。"
    )


@router.post("/record/skip", response_model=SessionStatus)
async def b601_record_skip() -> SessionStatus:
    """Skip remaining episode/reset time → next episode (LeRobot Right Arrow)."""
    if not (_record_proc and _record_proc.is_alive()):
        raise HTTPException(status_code=409, detail="当前没有正在运行的录制")
    try:
        tool = await asyncio.to_thread(_inject_record_right_arrow)
        _record_proc._log_line(f"UI skip → injected Right via {tool}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _proc_status(_record_proc, "record")


def _inject_record_left_arrow() -> str:
    """Tell lerobot-record to re-record current episode (Left Arrow)."""
    os.environ.setdefault("DISPLAY", os.environ.get("DISPLAY") or ":0")
    try:
        from pynput.keyboard import Controller, Key

        kb = Controller()
        kb.press(Key.left)
        kb.release(Key.left)
        return "pynput"
    except Exception as exc:
        logger.warning("pynput Left failed: %s", exc)

    display = os.environ.get("DISPLAY") or ":0"
    env = os.environ.copy()
    env["DISPLAY"] = display
    if shutil.which("xdotool"):
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "Left"],
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return "xdotool"

    raise RuntimeError(
        "无法从网页注入方向键。请直接在键盘上按 ←（左方向键）重录本条；"
        "或安装 xdotool 后重试按钮。"
    )


@router.post("/record/rerecord", response_model=SessionStatus)
async def b601_record_rerecord() -> SessionStatus:
    """Re-record current episode (LeRobot Left Arrow)."""
    if not (_record_proc and _record_proc.is_alive()):
        raise HTTPException(status_code=409, detail="当前没有正在运行的录制")
    try:
        tool = await asyncio.to_thread(_inject_record_left_arrow)
        _record_proc._log_line(f"UI rerecord ← injected Left via {tool}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _proc_status(_record_proc, "record")


class RecordMarkRequest(BaseModel):
    repo_id: str
    episode_index: int = Field(..., ge=0, description="0-based episode index")
    verdict: str = Field(..., description="ok | bad | clear")

    @field_validator("repo_id")
    @classmethod
    def _repo(cls, v: str) -> str:
        rid = (v or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", rid):
            raise ValueError("repo_id 必须是 owner/name 两段")
        return rid

    @field_validator("verdict")
    @classmethod
    def _verdict(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in ("ok", "bad", "clear"):
            raise ValueError("verdict 必须是 ok / bad / clear")
        return s


class RecordMarkResponse(BaseModel):
    ok: bool
    repo_id: str
    episode_index: int
    verdict: Optional[str] = None
    marks: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""


@router.post("/record/mark", response_model=RecordMarkResponse)
async def b601_record_mark(body: RecordMarkRequest) -> RecordMarkResponse:
    """Soft-mark an episode as ok/bad (or clear) in meta/botversex_episode_marks.json."""
    from .b601_episode_curation import set_verdict

    root = _lerobot_dataset_dir(body.repo_id)
    if root is None:
        # Allow marking while the first episode is still being written — create meta.
        path = _lerobot_dataset_path(body.repo_id)
        if path is None:
            raise HTTPException(400, "无效 repo_id")
        path.mkdir(parents=True, exist_ok=True)
        (path / "meta").mkdir(parents=True, exist_ok=True)
        root = path
    try:
        data = await asyncio.to_thread(
            set_verdict, root, int(body.episode_index), body.verdict  # type: ignore[arg-type]
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    verdict = None if body.verdict == "clear" else body.verdict
    return RecordMarkResponse(
        ok=True,
        repo_id=body.repo_id,
        episode_index=body.episode_index,
        verdict=verdict,
        marks=data,
        message="已标记" if verdict else "已清除标记",
    )


class DatasetEpisodeItem(BaseModel):
    episode_index: int
    length: int = 0
    verdict: Optional[str] = None
    marked_at: Optional[float] = None
    videos: List[Dict[str, Any]] = Field(default_factory=list)


class DatasetEpisodesResponse(BaseModel):
    repo_id: str
    path: Optional[str] = None
    num_episodes: int = 0
    bad_count: int = 0
    unmarked_count: int = 0
    episodes: List[DatasetEpisodeItem] = Field(default_factory=list)


@router.get("/dataset/episodes", response_model=DatasetEpisodesResponse)
async def b601_dataset_episodes(repo_id: str) -> DatasetEpisodesResponse:
    """List episodes with soft marks + per-episode video timestamp windows."""
    from .b601_episode_curation import list_episodes

    rid = (repo_id or "").strip()
    root = _lerobot_dataset_dir(rid)
    if root is None:
        return DatasetEpisodesResponse(repo_id=rid, episodes=[])
    try:
        rows = await asyncio.to_thread(list_episodes, root, rid)
    except Exception as exc:
        raise HTTPException(500, f"读取 episode 列表失败：{exc}") from exc
    bad = sum(1 for r in rows if r.get("verdict") == "bad")
    unmarked = sum(1 for r in rows if not r.get("verdict"))
    return DatasetEpisodesResponse(
        repo_id=rid,
        path=str(root),
        num_episodes=len(rows),
        bad_count=bad,
        unmarked_count=unmarked,
        episodes=[DatasetEpisodeItem(**r) for r in rows],
    )


class DatasetEpisodeDeleteRequest(BaseModel):
    repo_id: str
    episode_index: Optional[int] = Field(default=None, ge=0)
    episode_indices: Optional[List[int]] = None
    delete_all_bad: bool = False

    @field_validator("repo_id")
    @classmethod
    def _repo(cls, v: str) -> str:
        rid = (v or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", rid):
            raise ValueError("repo_id 必须是 owner/name 两段")
        return rid


class DatasetEpisodeDeleteResponse(BaseModel):
    ok: bool
    repo_id: str
    deleted: List[int] = Field(default_factory=list)
    num_episodes: int = 0
    message: str = ""


@router.post("/dataset/episode/delete", response_model=DatasetEpisodeDeleteResponse)
async def b601_dataset_episode_delete(body: DatasetEpisodeDeleteRequest) -> DatasetEpisodeDeleteResponse:
    """Physically delete one or more episodes from a local LeRobot dataset."""
    from .b601_episode_curation import (
        bad_episode_indices,
        delete_episodes_inplace,
        total_episodes_from_info,
    )

    if _record_proc and _record_proc.is_alive():
        raise HTTPException(409, "录制进行中，不能删除 episode")

    root = _lerobot_dataset_dir(body.repo_id)
    if root is None:
        raise HTTPException(404, f"本地数据集不存在：{body.repo_id}")

    indices: List[int] = []
    if body.delete_all_bad:
        total = total_episodes_from_info(root)
        indices = bad_episode_indices(root, total)
    if body.episode_indices:
        indices.extend(int(i) for i in body.episode_indices)
    if body.episode_index is not None:
        indices.append(int(body.episode_index))
    indices = sorted(set(indices))
    if not indices:
        raise HTTPException(400, "没有要删除的 episode（请指定索引或先标记不满意）")

    try:
        result = await asyncio.to_thread(delete_episodes_inplace, root, body.repo_id, indices)
    except Exception as exc:
        raise HTTPException(500, f"删除失败：{exc}") from exc

    return DatasetEpisodeDeleteResponse(
        ok=True,
        repo_id=body.repo_id,
        deleted=list(result.get("deleted") or indices),
        num_episodes=int(result.get("num_episodes") or 0),
        message=f"已删除 {len(indices)} 条，剩余 {result.get('num_episodes')} 条",
    )


class DatasetVideosResponse(BaseModel):
    repo_id: str
    path: Optional[str] = None
    num_episodes: Optional[int] = None
    videos: List[Dict[str, str]] = Field(default_factory=list)


@router.get("/dataset_videos", response_model=DatasetVideosResponse)
async def b601_dataset_videos(repo_id: str) -> DatasetVideosResponse:
    """List MP4s under a LeRobot cache dataset for in-page preview."""
    rid = (repo_id or "").strip()
    root = _lerobot_dataset_dir(rid)
    if root is None:
        return DatasetVideosResponse(repo_id=rid, videos=[])
    num_eps: Optional[int] = None
    info = root / "meta" / "info.json"
    if info.is_file():
        try:
            meta = json.loads(info.read_text(encoding="utf-8"))
            if isinstance(meta.get("total_episodes"), int):
                num_eps = meta["total_episodes"]
        except Exception:
            pass
    videos: List[Dict[str, str]] = []
    vroot = root / "videos"
    if vroot.is_dir():
        for mp4 in sorted(vroot.rglob("*.mp4")):
            # videos/observation.images.front/chunk-000/file-000.mp4
            try:
                rel = mp4.relative_to(vroot)
                key = rel.parts[0] if rel.parts else mp4.stem
            except Exception:
                key = mp4.stem
            from urllib.parse import quote

            rel_s = str(mp4.relative_to(root))
            videos.append(
                {
                    "key": key.replace("observation.images.", ""),
                    "file": mp4.name,
                    "url": (
                        f"/api/b601/dataset_video?repo_id={quote(rid, safe='')}"
                        f"&rel={quote(rel_s, safe='')}"
                    ),
                }
            )
    return DatasetVideosResponse(repo_id=rid, path=str(root), num_episodes=num_eps, videos=videos)


class DatasetFrameResponse(BaseModel):
    ok: bool
    repo_id: str
    t: float = 0.0
    episode_index: Optional[int] = None
    frame_index: Optional[int] = None
    joints: Dict[str, float] = Field(default_factory=dict)
    message: str = ""


# Cached (timestamp_global, episode, frame_local, state7) tables for playback sync.
_dataset_frame_cache: Dict[str, Dict[str, Any]] = {}


def _build_dataset_frame_index(root: Path) -> Optional[Dict[str, Any]]:
    """Map global video timeline → observation.state for 3D playback sync."""
    try:
        import pyarrow.parquet as pq
        import numpy as np
    except ImportError:
        return None

    data_files = sorted((root / "data").rglob("*.parquet"))
    ep_files = sorted((root / "meta" / "episodes").rglob("*.parquet"))
    if not data_files:
        return None

    # Episode video timeline (prefer front cam).
    ep_bounds: List[tuple[float, float, int, int, int]] = []
    if ep_files:
        try:
            et = pq.read_table(
                ep_files[0],
                columns=[
                    "episode_index",
                    "dataset_from_index",
                    "dataset_to_index",
                    "videos/observation.images.front/from_timestamp",
                    "videos/observation.images.front/to_timestamp",
                ],
            )
            pdf = et.to_pandas()
            for _, row in pdf.iterrows():
                ep_bounds.append(
                    (
                        float(row["videos/observation.images.front/from_timestamp"]),
                        float(row["videos/observation.images.front/to_timestamp"]),
                        int(row["episode_index"]),
                        int(row["dataset_from_index"]),
                        int(row["dataset_to_index"]),
                    )
                )
        except Exception as exc:
            logger.debug("episode timeline load failed: %s", exc)

    tables = [pq.read_table(f, columns=["timestamp", "observation.state", "episode_index", "frame_index"]) for f in data_files]
    import pyarrow as pa

    table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
    ts = table.column("timestamp").to_numpy()
    ep = table.column("episode_index").to_numpy()
    fi = table.column("frame_index").to_numpy()
    # fixed_size_list → (N, 7)
    states = np.vstack([list(x.as_py()) for x in table.column("observation.state")])

    # Build global timeline timestamps aligned with concatenated videos.
    global_ts = np.zeros(len(ts), dtype=np.float64)
    if ep_bounds:
        for g0, _g1, epi, i0, i1 in ep_bounds:
            # rows [i0, i1)
            sl = slice(i0, i1)
            if i1 > i0 and i1 <= len(ts):
                global_ts[sl] = g0 + ts[sl]
    else:
        # Fallback: cumulative by episode order
        offset = 0.0
        for epi in sorted(set(int(x) for x in ep)):
            mask = ep == epi
            local = ts[mask]
            global_ts[mask] = offset + local
            if len(local):
                offset += float(local.max()) + (1.0 / 30.0)

    order = np.argsort(global_ts)
    # B601 / Seeed LeRobot record degrees in observation.state (see meta stats).
    units = "degrees"
    info_path = root / "meta" / "info.json"
    if info_path.is_file():
        try:
            meta = json.loads(info_path.read_text(encoding="utf-8"))
            rt = str(meta.get("robot_type") or "")
            # Keep degrees for seeed_b601_*; only skip if explicitly radians elsewhere.
            if "seeed_b601" in rt or "b601" in rt:
                units = "degrees"
        except Exception:
            pass
    # episode_index → front-cam absolute from_timestamp (for t_rel lookup)
    ep_from: Dict[int, float] = {}
    for g0, _g1, epi, _i0, _i1 in ep_bounds:
        ep_from[int(epi)] = float(g0)
    return {
        "global_ts": global_ts[order],
        "states": states[order],
        "episode_index": ep[order],
        "frame_index": fi[order],
        "units": units,
        "ep_from": ep_from,
    }


def _state_to_joint_dict(state7: Any, *, units: str = "degrees") -> Dict[str, float]:
    """Map LeRobot observation.state[7] → joint1..joint7 (radians) for the URDF viewer.

    Seeed B601 LeRobot datasets store arm joints in **degrees** (teleop live
    stream is radians). Always convert degrees→radians — per-frame heuristics
    mis-classified near-zero poses as already-radians and warped the 3D arm.
    """
    import math

    vals = [float(x) for x in state7]
    arm = vals[:6]
    if units != "radians":
        arm = [math.radians(x) for x in arm]
    g_raw = vals[6] if len(vals) > 6 else 0.0
    # Gripper: action span is roughly 0..25° when open; URDF wants 0..0.05 m.
    if units != "radians" or abs(g_raw) > 0.25:
        g = max(0.0, min(0.05, abs(g_raw) / 25.0 * 0.05))
    else:
        g = max(0.0, min(0.05, abs(g_raw)))
    out: Dict[str, float] = {}
    for i, v in enumerate(arm, start=1):
        out[f"joint{i}"] = v
    out["joint7"] = g
    return out


@router.get("/dataset_frame", response_model=DatasetFrameResponse)
async def b601_dataset_frame(
    repo_id: str,
    t: float = 0.0,
    episode_index: Optional[int] = None,
    t_rel: Optional[float] = None,
) -> DatasetFrameResponse:
    """Sample follower joints for 3D playback sync.

    Prefer ``episode_index`` + ``t_rel`` (seconds within that episode) — matches
    the UI 「本条」 clock. Fallback: absolute front-timeline ``t``.
    """
    rid = (repo_id or "").strip()
    root = _lerobot_dataset_dir(rid)
    if root is None:
        return DatasetFrameResponse(ok=False, repo_id=rid, t=t, message="dataset not found")

    try:
        import numpy as np
    except ImportError:
        return DatasetFrameResponse(ok=False, repo_id=rid, t=t, message="numpy not available")

    cache_key = f"{root}:v2"
    idx = _dataset_frame_cache.get(cache_key)
    if idx is None:
        built = await asyncio.to_thread(_build_dataset_frame_index, root)
        if built is None:
            return DatasetFrameResponse(ok=False, repo_id=rid, t=t, message="无法读取 parquet")
        _dataset_frame_cache[cache_key] = built
        # Bound cache size
        if len(_dataset_frame_cache) > 6:
            _dataset_frame_cache.pop(next(iter(_dataset_frame_cache)))
        idx = built

    gts = idx["global_ts"]
    if len(gts) == 0:
        return DatasetFrameResponse(ok=False, repo_id=rid, t=t, message="empty dataset")

    query_t = float(t)
    if episode_index is not None:
        epi = int(episode_index)
        ep_from = idx.get("ep_from") or {}
        g0 = float(ep_from.get(epi, ep_from.get(str(epi), 0.0)))
        rel = float(t_rel) if t_rel is not None else 0.0
        query_t = g0 + max(0.0, rel)
        # Restrict search to this episode's rows when possible
        ep_arr = idx["episode_index"]
        mask = ep_arr == epi
        if np.any(mask):
            sub_gts = gts[mask]
            sub_i = int(np.searchsorted(sub_gts, query_t, side="left"))
            if sub_i <= 0:
                sub_i = 0
            elif sub_i >= len(sub_gts):
                sub_i = len(sub_gts) - 1
            else:
                if abs(sub_gts[sub_i] - query_t) > abs(sub_gts[sub_i - 1] - query_t):
                    sub_i = sub_i - 1
            # map back to global index
            global_indices = np.flatnonzero(mask)
            i = int(global_indices[sub_i])
            joints = _state_to_joint_dict(idx["states"][i], units=str(idx.get("units") or "degrees"))
            return DatasetFrameResponse(
                ok=True,
                repo_id=rid,
                t=float(gts[i]),
                episode_index=int(idx["episode_index"][i]),
                frame_index=int(idx["frame_index"][i]),
                joints=joints,
            )

    # nearest frame on full timeline
    i = int(np.searchsorted(gts, query_t, side="left"))
    if i <= 0:
        i = 0
    elif i >= len(gts):
        i = len(gts) - 1
    else:
        if abs(gts[i] - query_t) > abs(gts[i - 1] - query_t):
            i = i - 1

    joints = _state_to_joint_dict(idx["states"][i], units=str(idx.get("units") or "degrees"))
    return DatasetFrameResponse(
        ok=True,
        repo_id=rid,
        t=float(gts[i]),
        episode_index=int(idx["episode_index"][i]),
        frame_index=int(idx["frame_index"][i]),
        joints=joints,
    )


@router.get("/dataset_video")
async def b601_dataset_video(repo_id: str, rel: str):
    """Stream one LeRobot dataset MP4 for <video> preview."""
    from fastapi.responses import FileResponse

    rid = (repo_id or "").strip()
    root = _lerobot_dataset_dir(rid)
    if root is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    # Prevent path traversal
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise HTTPException(status_code=400, detail="invalid path")
    mp4 = (root / rel_path).resolve()
    try:
        mp4.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid path") from exc
    if not mp4.is_file() or mp4.suffix.lower() != ".mp4":
        raise HTTPException(status_code=404, detail="video not found")
    return FileResponse(str(mp4), media_type="video/mp4", filename=mp4.name)


def _gb10_infer_script() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "b601_gb10_infer_loop.py"


def _resolve_lerobot_py_for_remote() -> str:
    py = _resolve_lerobot_python()
    if not py:
        raise HTTPException(500, "lerobot / motorbridge python not found for GB10 infer loop")
    return py


def _remote_infer_running() -> bool:
    return bool(_remote_infer_proc and _remote_infer_proc.poll() is None)


@router.post("/inference/start", response_model=SessionStatus)
async def b601_inference_start(body: InferenceStartRequest) -> SessionStatus:
    global _inference_proc, _remote_infer_proc, _remote_infer_started_at
    _require_runtime_idle(RuntimeMode.INFERENCE)
    variant = _resolve_arm_variant(body.arm_variant)
    can = _resolve_follower_port(arm_variant=variant, explicit=body.follower_port, can_iface=body.can_iface)
    if variant == "rs":
        _kill_gateway()
    await recover_follower(can, arm_variant=variant)

    backend = (body.backend or "remote").strip().lower()
    # Backward compat: "gb10" was the old hardcoded remote backend.
    if backend == "gb10":
        backend = "remote"
    if backend == "remote":
        script = _gb10_infer_script()
        if not script.is_file():
            raise HTTPException(500, f"missing remote infer script: {script}")
        if _remote_infer_running():
            raise HTTPException(409, "remote inference already running")
        cams = list(body.camera_indices or [4, 6])
        front = int(cams[0]) if cams else 4
        side = int(cams[1]) if len(cams) > 1 else 6
        # Vision MJPEG preview holds V4L2 handles in this process — same race
        # as teleop/record. Release before the infer loop opens cams.
        try:
            from .camera import stop_all_streams

            await asyncio.to_thread(stop_all_streams, 1.5)
            await asyncio.sleep(0.25)
        except Exception as exc:
            logger.debug("b601 remote infer stop camera streams: %s", exc)
        sidecar = resolve_sidecar_url(body.node_id, body.sidecar_url)
        default_model = resolve_model_path(body.node_id, None)
        env = {
            **os.environ,
            "BOTVERSEX_PI0_SIDECAR_URL": sidecar,
            "B601_ARM_VARIANT": variant,
            "B601_FOLLOWER_PORT": can,
            "B601_CAN": can,
            "B601_ROBOT_ID": _resolve_robot_id(body.robot_id),
            "B601_CAMERA_FRONT": str(front),
            "B601_CAMERA_SIDE": str(side),
            "B601_TASK": body.single_task,
            "B601_PI05_MODEL": body.policy_path.strip() or default_model,
            # Two-phase: slow lift until |shoulder_lift|>=55°, then uncapped hit.
            # Unset B601_MAX_DELTA_DEG so two-phase is used (legacy single-limit override).
            "B601_LIFT_DONE_DEG": os.environ.get("B601_LIFT_DONE_DEG", "55.0"),
            "B601_LIFT_MAX_DELTA_DEG": os.environ.get("B601_LIFT_MAX_DELTA_DEG", "8.0"),
            "B601_HIT_MAX_DELTA_DEG": os.environ.get("B601_HIT_MAX_DELTA_DEG", "0"),
            "B601_WARMUP_STEPS": os.environ.get("B601_WARMUP_STEPS", "5"),
        }
        # Do not pass a fixed B601_MAX_DELTA_DEG unless the operator set one —
        # otherwise it would disable two-phase lift/hit.
        if "B601_MAX_DELTA_DEG" in os.environ:
            env["B601_MAX_DELTA_DEG"] = os.environ["B601_MAX_DELTA_DEG"]
        else:
            env.pop("B601_MAX_DELTA_DEG", None)
        py = _resolve_lerobot_py_for_remote()
        log_path = Path("/tmp/b601_gb10_infer_loop.log")
        log_f = open(log_path, "ab", buffering=0)
        _remote_infer_proc = subprocess.Popen(
            [py, str(script)],
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _remote_infer_started_at = time.time()
        await b601_runtime_lock.acquire(RuntimeMode.INFERENCE, "inference-gb10")
        return SessionStatus(
            running=True,
            role="inference-gb10",
            healthy=True,
            starting=True,
            pid=_remote_infer_proc.pid,
            started_at=_remote_infer_started_at,
            log_tail=[f"sidecar={sidecar}", f"log={log_path}"],
        )

    # Legacy: local lerobot-record (loads policy on this laptop — may OOM for Pi0.5)
    if not (body.policy_path or "").strip():
        raise HTTPException(400, "local backend requires policy_path")
    leader = _resolve_leader(body.leader_port)
    proc = B601InferenceCLI(
        leader_port=leader,
        follower_port=can,
        arm_variant=variant,
        robot_id=_resolve_robot_id(body.robot_id),
        leader_id=_resolve_leader_id(body.leader_id),
        policy_path=body.policy_path,
        single_task=body.single_task,
        episode_time_s=body.episode_time_s,
        camera_indices=list(body.camera_indices or [8, 4]),
    )
    await asyncio.to_thread(proc.start)
    _inference_proc = proc
    await b601_runtime_lock.acquire(RuntimeMode.INFERENCE, "inference")
    return _proc_status(proc, "inference")


@router.get("/inference/status", response_model=SessionStatus)
async def b601_inference_status() -> SessionStatus:
    if _remote_infer_running():
        status_path = Path("/tmp/b601_gb10_infer_status.json")
        phase = None
        err = None
        if status_path.is_file():
            try:
                data = json.loads(status_path.read_text())
                phase = data.get("phase")
                err = data.get("error")
            except Exception:
                pass
        uptime = (time.time() - _remote_infer_started_at) if _remote_infer_started_at else None
        return SessionStatus(
            running=True,
            role="inference-gb10",
            healthy=err is None,
            starting=phase in (None, "connect_sidecar", "connected"),
            last_error=str(err) if err else None,
            pid=_remote_infer_proc.pid if _remote_infer_proc else None,
            started_at=_remote_infer_started_at,
            uptime_s=uptime,
            log_tail=[f"phase={phase or '?'}"] ,
        )
    if _remote_infer_proc is not None and _remote_infer_proc.poll() is not None:
        detail = None
        status_path = Path("/tmp/b601_gb10_infer_status.json")
        if status_path.is_file():
            try:
                data = json.loads(status_path.read_text())
                detail = data.get("error") or data.get("phase")
            except Exception:
                pass
        if not detail:
            log_path = Path("/tmp/b601_gb10_infer_loop.log")
            try:
                if log_path.is_file():
                    lines = log_path.read_text(errors="replace").splitlines()
                    for line in reversed(lines[-80:]):
                        low = line.lower()
                        if "error" in low or "runtimeerror" in low or "cannot open" in low:
                            detail = line.strip()
                            break
            except Exception:
                pass
        msg = f"remote infer exited code={_remote_infer_proc.returncode}"
        if detail:
            msg = f"{msg}: {detail}"
        return SessionStatus(
            running=False,
            role="inference-gb10",
            healthy=False,
            last_error=msg,
        )
    return _proc_status(_inference_proc, "inference")


def _default_sidecar_url(explicit: Optional[str] = None, node_id: Optional[str] = None) -> str:
    return resolve_sidecar_url(node_id, explicit)


@router.get("/inference/sidecar_status")
async def b601_sidecar_status(sidecar_url: Optional[str] = None, node_id: Optional[str] = None) -> dict:
    """Proxy remote Pi0.5 sidecar /healthz for deploy UI."""
    url = _default_sidecar_url(sidecar_url, node_id)
    try:
        import urllib.request

        def _get() -> dict:
            req = urllib.request.Request(f"{url}/healthz", method="GET")
            with urllib.request.urlopen(req, timeout=4) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = await asyncio.to_thread(_get)
        return {"ok": True, "sidecar_url": url, **data}
    except Exception as exc:
        return {
            "ok": False,
            "sidecar_url": url,
            "loaded": False,
            "model_key": None,
            "error": str(exc),
        }


@router.post("/inference/load_model")
async def b601_sidecar_load_model(body: SidecarLoadRequest) -> dict:
    """Ask remote sidecar to hot-load a model (path on the remote or HF id)."""
    url = _default_sidecar_url(body.sidecar_url, body.node_id)
    payload = {
        "model_key": body.model_key.strip(),
        "prefer_device": body.prefer_device,
        "task_prompt": body.task_prompt,
    }

    def _post() -> dict:
        import urllib.error
        import urllib.request

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{url}/load",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"sidecar /load {exc.code}: {detail}") from exc

    try:
        result = await asyncio.to_thread(_post)
        return {"ok": True, "sidecar_url": url, **result}
    except Exception as exc:
        raise HTTPException(502, f"remote load failed: {exc}") from exc


@router.post("/inference/sync_model")
async def b601_sync_model_to_remote(body: SidecarSyncRequest) -> dict:
    """Background: HF/Qualia model → rsync to remote compute node → optional sidecar /load.

    Resolves SSH target and remote dir from the configured RemoteComputeNode
    (body.node_id), falling back to the default node. For local nodes, rsync is
    a no-op (model is downloaded in place).
    """
    script = Path(__file__).resolve().parents[3] / "scripts" / "sync_model_to_remote.py"
    if not script.is_file():
        # Backward-compat fallback to old script name.
        script = Path(__file__).resolve().parents[3] / "scripts" / "sync_pi05_to_gb10.py"
    if not script.is_file():
        raise HTTPException(500, f"missing sync script: {script}")
    if not (body.model_id or body.job_id):
        raise HTTPException(400, "model_id or job_id required")
    status_path = Path("/tmp/b601_pi05_sync_status.json")
    log_path = Path("/tmp/b601_pi05_sync.log")
    sidecar = _default_sidecar_url(body.sidecar_url, body.node_id)
    remote_dir = resolve_remote_dir(body.node_id, body.remote_dir)
    ssh_target = resolve_ssh_target(body.node_id)
    ssh_jump = resolve_ssh_jump(body.node_id)
    cmd = [
        sys.executable,
        str(script),
        "--remote-dir",
        remote_dir,
        "--sidecar-url",
        sidecar,
        "--status-file",
        str(status_path),
    ]
    if ssh_target:
        cmd.extend(["--host", ssh_target])
    if ssh_jump:
        cmd.extend(["--jump", ssh_jump])
    if body.model_id:
        cmd.extend(["--model-id", body.model_id.strip()])
    if body.job_id:
        cmd.extend(["--job-id", body.job_id.strip()])
    if body.load:
        cmd.append("--load")
    cmd.extend(["--task-prompt", body.task_prompt])
    log_f = open(log_path, "ab", buffering=0)
    proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)
    status_path.write_text(
        json.dumps(
            {
                "phase": "starting",
                "pid": proc.pid,
                "model_id": body.model_id,
                "job_id": body.job_id,
                "node_id": body.node_id,
                "remote_dir": remote_dir,
                "ts": time.time(),
            },
            ensure_ascii=False,
        )
    )
    return {
        "ok": True,
        "pid": proc.pid,
        "log": str(log_path),
        "status_file": str(status_path),
        "message": "sync started in background",
    }


@router.get("/inference/sync_status")
async def b601_sync_model_status() -> dict:
    path = Path("/tmp/b601_pi05_sync_status.json")
    if not path.is_file():
        return {"ok": True, "phase": "idle"}
    try:
        data = json.loads(path.read_text())
        return {"ok": True, **data}
    except Exception as exc:
        return {"ok": False, "phase": "error", "error": str(exc)}


@router.post("/inference/stop", response_model=SessionStatus)
async def b601_inference_stop(can_iface: str = DEFAULT_CAN) -> SessionStatus:
    global _inference_proc, _remote_infer_proc, _remote_infer_started_at
    if _remote_infer_proc is not None:
        proc = _remote_infer_proc
        _remote_infer_proc = None
        _remote_infer_started_at = None
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            await asyncio.to_thread(proc.wait, 8)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
    if _inference_proc:
        await asyncio.to_thread(_inference_proc.stop, 8.0)
        _inference_proc = None
    await b601_runtime_lock.release(RuntimeMode.INFERENCE)
    variant = _resolve_arm_variant(None)
    port = _resolve_follower_port(arm_variant=variant, can_iface=can_iface)
    await disable_follower(port, arm_variant=variant)
    return SessionStatus(running=False, role="inference")


@router.post("/gateway/start", response_model=GatewayStatus)
async def b601_gateway_start(bind: str = "127.0.0.1:9002") -> GatewayStatus:
    global _gateway_proc
    if _gateway_proc and _gateway_proc.poll() is None:
        return GatewayStatus(running=True, pid=_gateway_proc.pid)
    _kill_gateway()
    cli = resolve_cli_argv("motorbridge-gateway")
    _gateway_proc = subprocess.Popen([*cli, "--bind", bind], start_new_session=True)
    return GatewayStatus(running=True, pid=_gateway_proc.pid)


@router.post("/gateway/stop", response_model=GatewayStatus)
async def b601_gateway_stop() -> GatewayStatus:
    _kill_gateway()
    return GatewayStatus(running=False)


@router.get("/gateway/status", response_model=GatewayStatus)
async def b601_gateway_status() -> GatewayStatus:
    if _gateway_proc and _gateway_proc.poll() is None:
        return GatewayStatus(running=True, pid=_gateway_proc.pid)
    running = _pgrep_running("motorbridge-gateway") or _pgrep_running("ws_gateway")
    return GatewayStatus(running=running)


class SnapshotRequest(BaseModel):
    repo_id: Optional[str] = Field(default=None, description="LeRobot repo id e.g. local/b601-dm-demo")
    label: str = Field(default="lab_snapshot", max_length=64)


class DatasetCheckResponse(BaseModel):
    exists: bool
    repo_id: str
    path: Optional[str] = None
    num_episodes: Optional[int] = None


def _lerobot_dataset_path(repo_id: str) -> Optional[Path]:
    """Expected on-disk path for a 2-part HF/LeRobot repo_id (may not exist yet)."""
    if not repo_id or repo_id.count("/") != 1:
        return None
    owner, name = repo_id.split("/", 1)
    if not owner or not name:
        return None
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return base / "lerobot" / owner / name


def _lerobot_dataset_dir(repo_id: str) -> Optional[Path]:
    candidate = _lerobot_dataset_path(repo_id)
    return candidate if candidate is not None and candidate.is_dir() else None


def _fresh_repo_id(preferred: str) -> str:
    """Return ``preferred`` if unused; otherwise a new owner/name that does not exist on disk.

    LeRobot ``create`` raises FileExistsError when the cache dir already exists —
    common after a failed first second of recording left an empty folder.
    """
    rid = (preferred or "").strip()
    if rid.count("/") != 1:
        return rid
    owner, name = rid.split("/", 1)
    path = _lerobot_dataset_path(rid)
    if path is None or not path.exists():
        return rid
    stem = re.sub(r"-\d{8}_\d{4,6}(_\d+)?$", "", name) or name
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for n in range(0, 80):
        cand = f"{owner}/{stem}-{stamp}" if n == 0 else f"{owner}/{stem}-{stamp}_{n}"
        p = _lerobot_dataset_path(cand)
        if p is not None and not p.exists():
            return cand
    return f"{owner}/{stem}-{stamp}_{os.getpid()}"


@router.get("/dataset_check", response_model=DatasetCheckResponse)
async def b601_dataset_check(repo_id: str) -> DatasetCheckResponse:
    """Mirror SO-101 ``/api/recording/dataset_check`` for B601 LeRobot cache dirs."""
    rid = (repo_id or "").strip()
    root = _lerobot_dataset_dir(rid)
    if root is None:
        return DatasetCheckResponse(exists=False, repo_id=rid)
    num_eps: Optional[int] = None
    info = root / "meta" / "info.json"
    if info.is_file():
        try:
            meta = json.loads(info.read_text(encoding="utf-8"))
            raw = meta.get("total_episodes")
            if isinstance(raw, int):
                num_eps = raw
        except Exception:
            num_eps = None
    return DatasetCheckResponse(exists=True, repo_id=rid, path=str(root), num_episodes=num_eps)


class DatasetListItem(BaseModel):
    repo_id: str
    path: str
    num_episodes: Optional[int] = None
    total_frames: Optional[int] = None
    robot_type: Optional[str] = None
    mtime: float = 0.0
    size_mb: Optional[float] = None


class DatasetListResponse(BaseModel):
    items: List[DatasetListItem] = Field(default_factory=list)
    root: str = ""


def _dataset_list_item(owner: str, name: str, path: Path) -> Optional[DatasetListItem]:
    if not (path / "meta" / "info.json").is_file() and not (path / "data").is_dir():
        return None
    num_eps: Optional[int] = None
    total_frames: Optional[int] = None
    robot_type: Optional[str] = None
    info = path / "meta" / "info.json"
    if info.is_file():
        try:
            meta = json.loads(info.read_text(encoding="utf-8"))
            if isinstance(meta.get("total_episodes"), int):
                num_eps = meta["total_episodes"]
            if isinstance(meta.get("total_frames"), int):
                total_frames = meta["total_frames"]
            if isinstance(meta.get("robot_type"), str):
                robot_type = meta["robot_type"]
        except Exception:
            pass
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    size_mb: Optional[float] = None
    try:
        # Fast-ish: sum top-level video+data dirs only
        total = 0
        for sub in ("data", "videos", "meta"):
            d = path / sub
            if not d.is_dir():
                continue
            for f in d.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        size_mb = round(total / (1024 * 1024), 1)
    except OSError:
        size_mb = None
    return DatasetListItem(
        repo_id=f"{owner}/{name}",
        path=str(path),
        num_episodes=num_eps,
        total_frames=total_frames,
        robot_type=robot_type,
        mtime=mtime,
        size_mb=size_mb,
    )


@router.get("/datasets", response_model=DatasetListResponse)
async def b601_datasets_list(prefix: Optional[str] = None) -> DatasetListResponse:
    """List local LeRobot datasets under ``~/.cache/huggingface/lerobot/``."""
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "lerobot"
    items: List[DatasetListItem] = []
    if not base.is_dir():
        return DatasetListResponse(items=[], root=str(base))

    pref = (prefix or "").strip().lower()

    def _scan() -> List[DatasetListItem]:
        out: List[DatasetListItem] = []
        try:
            owners = sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return out
        for owner_dir in owners:
            if not owner_dir.is_dir() or owner_dir.name.startswith("."):
                continue
            try:
                names = sorted(owner_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            except OSError:
                continue
            for name_dir in names:
                if not name_dir.is_dir():
                    continue
                rid = f"{owner_dir.name}/{name_dir.name}"
                if pref and pref not in rid.lower() and pref not in name_dir.name.lower():
                    continue
                item = _dataset_list_item(owner_dir.name, name_dir.name, name_dir)
                if item is not None:
                    out.append(item)
        out.sort(key=lambda x: x.mtime, reverse=True)
        return out[:80]

    items = await asyncio.to_thread(_scan)
    return DatasetListResponse(items=items, root=str(base))


class DatasetVizStartRequest(BaseModel):
    repo_id: str
    episode_index: int = Field(0, ge=0, le=10_000)

    @field_validator("repo_id")
    @classmethod
    def _rid(cls, v: str) -> str:
        rid = (v or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", rid):
            raise ValueError("repo_id 必须是 owner/name 两段")
        return rid


class DatasetVizStatus(BaseModel):
    running: bool = False
    repo_id: Optional[str] = None
    episode_index: Optional[int] = None
    message: str = ""
    log_tail: List[str] = Field(default_factory=list)
    last_error: Optional[str] = None


def _dataset_viz_status() -> DatasetVizStatus:
    global _dataset_viz_proc
    proc = _dataset_viz_proc
    if proc is None:
        return DatasetVizStatus(message="未启动")
    alive = proc._proc is not None and proc._proc.poll() is None  # noqa: SLF001
    if not alive:
        err = proc.last_error
        _dataset_viz_proc = None
        return DatasetVizStatus(
            running=False,
            message="已结束",
            log_tail=proc.log_tail,
            last_error=err,
        )
    repo = getattr(proc, "_repo_id", None)
    ep = getattr(proc, "_episode", None)
    return DatasetVizStatus(
        running=True,
        repo_id=str(repo) if repo else None,
        episode_index=int(ep) if ep is not None else None,
        message=f"Rerun 回看中 · {repo} · episode {ep}",
        log_tail=proc.log_tail,
        last_error=proc.last_error,
    )


@router.get("/dataset_viz/status", response_model=DatasetVizStatus)
async def b601_dataset_viz_status() -> DatasetVizStatus:
    """Status of the optional official Rerun dataset viewer (read-only)."""
    return _dataset_viz_status()


@router.post("/dataset_viz/start", response_model=DatasetVizStatus)
async def b601_dataset_viz_start(body: DatasetVizStartRequest) -> DatasetVizStatus:
    """Launch official ``lerobot-dataset-viz`` (Rerun) for one episode.

    Does not touch CAN / teleop / record locks — safe alongside idle hardware.
    Opens a native Rerun window on the Agent machine (needs DISPLAY).
    """
    global _dataset_viz_proc
    rid = body.repo_id
    root = _lerobot_dataset_dir(rid)
    if root is None:
        raise HTTPException(status_code=404, detail=f"本地找不到数据集 {rid}")

    # Stop previous viz session if any (only one Rerun spawn at a time).
    if _dataset_viz_proc is not None:
        try:
            await asyncio.to_thread(_dataset_viz_proc.stop, 3.0)
        except Exception:
            pass
        _dataset_viz_proc = None

    py = _resolve_lerobot_python() or sys.executable

    def _probe_rerun() -> None:
        import rerun  # noqa: F401

    try:
        await asyncio.to_thread(_probe_rerun)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"本机未安装 rerun-sdk（{exc}）。"
                "请在 realtime venv 中执行: pip install 'rerun-sdk==0.26.2'"
            ),
        ) from exc

    _rerun_cli_shim_dir(py)

    proc = B601DatasetVizCLI(repo_id=rid, root=root, episode_index=int(body.episode_index))
    try:
        await asyncio.to_thread(proc.start, 25.0)
    except Exception as exc:
        logger.exception("dataset_viz start failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    _dataset_viz_proc = proc
    return _dataset_viz_status()


@router.post("/dataset_viz/stop", response_model=DatasetVizStatus)
async def b601_dataset_viz_stop() -> DatasetVizStatus:
    """Stop the dataset-viz logger process (Rerun window may stay open)."""
    global _dataset_viz_proc
    proc = _dataset_viz_proc
    if proc is not None:
        try:
            await asyncio.to_thread(proc.stop, 3.0)
        except Exception:
            pass
        _dataset_viz_proc = None
    return DatasetVizStatus(running=False, message="已停止")


class DatasetPushRequest(BaseModel):
    """Upload a local LeRobot cache dataset to Hugging Face Hub."""

    repo_id: str = Field(..., description="Local cache id, e.g. local/b601-dm-20260718_0031")
    hub_repo_id: Optional[str] = Field(
        default=None,
        description="HF dataset id owner/name. Required if local owner is 'local'.",
    )
    token: Optional[str] = Field(
        default=None,
        description="HF write token. Omit to use ~/.cache/huggingface/token or HF_TOKEN.",
    )
    private: bool = False

    @field_validator("repo_id")
    @classmethod
    def _local_repo(cls, v: str) -> str:
        rid = (v or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", rid):
            raise ValueError("repo_id 必须是 owner/name 两段")
        return rid

    @field_validator("hub_repo_id")
    @classmethod
    def _hub_repo(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not str(v).strip():
            return None
        rid = str(v).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", rid):
            raise ValueError("hub_repo_id 必须是 owner/name 两段")
        if rid.startswith("local/"):
            raise ValueError("hub_repo_id 不能用 local/ — 请填你的 HF 用户名/数据集名")
        return rid


class DatasetPushResponse(BaseModel):
    ok: bool
    local_repo_id: str
    hub_repo_id: Optional[str] = None
    url: Optional[str] = None
    message: str = ""
    bytes_uploaded_hint: Optional[str] = None


def _resolve_hf_token(explicit: Optional[str] = None) -> Optional[str]:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        from .hf import _read_token

        return _read_token()
    except Exception:
        pass
    for k in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"):
        v = os.environ.get(k)
        if v and v.strip():
            return v.strip()
    token_path = Path.home() / ".cache" / "huggingface" / "token"
    if token_path.is_file():
        try:
            t = token_path.read_text(encoding="utf-8").strip()
            if t:
                return t
        except Exception:
            pass
    return None


def _push_dataset_to_hub(
    local_dir: Path,
    hub_repo_id: str,
    token: str,
    *,
    private: bool = False,
) -> DatasetPushResponse:
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return DatasetPushResponse(
            ok=False,
            local_repo_id="",
            hub_repo_id=hub_repo_id,
            message="huggingface_hub 未安装（请用 lerobot venv）",
        )

    api = HfApi(token=token)
    try:
        api.whoami()
    except Exception as exc:
        return DatasetPushResponse(
            ok=False,
            local_repo_id="",
            hub_repo_id=hub_repo_id,
            message=(
                f"无法连接 Hugging Face / token 无效：{exc}。"
                "本机若在国内，可设 HF_ENDPOINT=https://hf-mirror.com 后重试，"
                "或到能访问 huggingface.co 的网络再上传。"
            ),
        )

    try:
        api.create_repo(
            repo_id=hub_repo_id,
            repo_type="dataset",
            private=private,
            exist_ok=True,
        )
        api.upload_folder(
            folder_path=str(local_dir),
            repo_id=hub_repo_id,
            repo_type="dataset",
        )
    except Exception as exc:
        return DatasetPushResponse(
            ok=False,
            local_repo_id="",
            hub_repo_id=hub_repo_id,
            message=f"上传失败：{exc}",
        )

    return DatasetPushResponse(
        ok=True,
        local_repo_id="",
        hub_repo_id=hub_repo_id,
        url=f"https://huggingface.co/datasets/{hub_repo_id}",
        message="上传完成",
    )


@router.post("/dataset/push", response_model=DatasetPushResponse)
async def b601_dataset_push(body: DatasetPushRequest) -> DatasetPushResponse:
    """Push a local LeRobot dataset folder to Hugging Face Hub."""
    from .b601_episode_curation import bad_episode_indices, total_episodes_from_info

    local_rid = body.repo_id.strip()
    root = _lerobot_dataset_dir(local_rid)
    if root is None:
        return DatasetPushResponse(
            ok=False,
            local_repo_id=local_rid,
            message=f"本地数据集不存在：{local_rid}",
        )

    total = total_episodes_from_info(root)
    bad = bad_episode_indices(root, total)
    if bad:
        shown = ", ".join(str(i + 1) for i in bad[:12])
        more = "" if len(bad) <= 12 else f" 等 {len(bad)} 条"
        return DatasetPushResponse(
            ok=False,
            local_repo_id=local_rid,
            message=(
                f"还有标为「不满意」的条目未删除（第 {shown}{more}）。"
                "请先在审片区删除，或改标为可用后再上传。"
            ),
        )

    token = _resolve_hf_token(body.token)
    if not token:
        return DatasetPushResponse(
            ok=False,
            local_repo_id=local_rid,
            message="未配置 HF token。请在上传框填写，或写入 ~/.cache/huggingface/token",
        )

    # Persist token for later (chmod 600) when user pasted one — never into the git repo.
    if body.token and body.token.strip():
        try:
            token_path = Path.home() / ".cache" / "huggingface" / "token"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token, encoding="utf-8")
            token_path.chmod(0o600)
        except Exception as exc:
            logger.debug("could not persist HF token: %s", exc)

    hub_rid = body.hub_repo_id
    if not hub_rid:
        owner, name = local_rid.split("/", 1)
        if owner == "local":
            return DatasetPushResponse(
                ok=False,
                local_repo_id=local_rid,
                message=(
                    "本地 id 是 local/...，上传到 HF 需要你的用户名。"
                    "请填写 Hub 数据集 ID，例如 yourname/b601-dm-20260718_0031"
                ),
            )
        hub_rid = local_rid

    size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    size_hint = f"{size / (1024 * 1024):.1f} MB"

    result = await asyncio.to_thread(
        _push_dataset_to_hub, root, hub_rid, token, private=body.private
    )
    result.local_repo_id = local_rid
    result.bytes_uploaded_hint = size_hint
    if result.ok and not result.message:
        result.message = "上传完成"
    return result


@router.post("/snapshot")
async def b601_snapshot(body: SnapshotRequest):
    """Pack episode metadata + joints + config for lab / paper supplementary."""
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    teleop_on = bool(_teleop_proc and _teleop_proc.is_alive())
    variant = _resolve_arm_variant(None)
    port = _resolve_follower_port(arm_variant=variant)
    health = await _build_health(
        port,
        arm_variant=variant,
        skip_motor_scan=teleop_on or _teleop_start_in_progress(),
    )
    config = _config_response()
    joints = _read_live_joints_file() if teleop_on else ({} if variant == "dm" else await poll_follower_joints(port))
    record_status = _proc_status(_record_proc, "record")
    manifest = {
        "schema": "botversex.b601.lab_snapshot.v1",
        "label": body.label,
        "created_at": time.time(),
        "repo_id": body.repo_id,
        "runtime_id": f"b601_{variant}",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("health.json", health.model_dump_json(indent=2))
        zf.writestr("config.json", config.model_dump_json(indent=2))
        zf.writestr("record_status.json", record_status.model_dump_json(indent=2))
        if joints:
            zf.writestr("joints_snapshot.json", json.dumps(joints, indent=2))
        if LIVE_JOINTS_PATH.is_file():
            zf.writestr("joints_live.json", LIVE_JOINTS_PATH.read_text(encoding="utf-8"))
        if body.repo_id:
            ds_dir = _lerobot_dataset_dir(body.repo_id)
            if ds_dir:
                info = ds_dir / "meta" / "info.json"
                if info.is_file():
                    zf.writestr("dataset/meta/info.json", info.read_text(encoding="utf-8"))
                for parquet in sorted((ds_dir / "data").rglob("*.parquet"))[:3]:
                    arc = f"dataset/data/{parquet.relative_to(ds_dir / 'data')}"
                    zf.write(parquet, arcname=arc)

    buf.seek(0)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"b601_{body.label}_{stamp}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


from .b601_gravity_comp import router as _gravity_comp_router  # noqa: E402
from .b601_gravity_comp import stop_gravity_comp_if_running  # noqa: E402
from .b601_kinematics import router as _kinematics_router  # noqa: E402
from .b601_ros2 import router as _ros2_router  # noqa: E402

router.include_router(_kinematics_router)
router.include_router(_gravity_comp_router)
router.include_router(_ros2_router)
