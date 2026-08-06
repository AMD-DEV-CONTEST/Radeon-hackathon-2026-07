"""LeKiwi API — Local Agent side.

Thin wrappers around the official LeRobot host/client architecture for the
LeKiwi mobile manipulator (Kiwi omni base + SO-101 arm). The robot-side
Raspberry Pi/Orin runs ``lekiwi_host``; BotverseX connects as
``lekiwi_client`` over ZMQ and launches teleop/record sessions locally.

P2 closed loop: /api/lekiwi/handshake/* endpoints implement the
"采集 → norm_stats → 续训 → sync_model_to_remote 热加载" chain from
~/brainbot/lingbot_configs/handshake_data_plan.md (brought over from GB10).

Endpoints:
  GET  /api/lekiwi/health           — LeKiwi Host reachability + CLI presence
  POST /api/lekiwi/teleop/start      — start lerobot-teleoperate (lekiwi)
  POST /api/lekiwi/teleop/stop       — stop teleop subprocess
  GET  /api/lekiwi/teleop/status     — running / starting / last_error / log_tail
  POST /api/lekiwi/record/start      — start lerobot-record (lekiwi)
  POST /api/lekiwi/record/stop       — stop record subprocess
  GET  /api/lekiwi/record/status     — running / episode progress / log_tail
  POST /api/lekiwi/disable           — emergency disable torque
  GET  /api/lekiwi/handshake/plan     — read episode count + compute L1/L2/L3 progress
  POST /api/lekiwi/handshake/auto_continue — trigger norm_stats → train → sync chain
  GET  /api/lekiwi/handshake/auto_continue/status — chain progress
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/lekiwi", tags=["lekiwi"])

# ---------------------------------------------------------------------------
# Defaults — official LeKiwi host/client architecture
# ---------------------------------------------------------------------------
DEFAULT_REMOTE_IP = os.environ.get("LEKIWI_REMOTE_IP", "192.168.1.50")
DEFAULT_CMD_PORT = int(os.environ.get("LEKIWI_CMD_PORT", "5555"))
DEFAULT_OBSERVATION_PORT = int(os.environ.get("LEKIWI_OBSERVATION_PORT", "5556"))
DEFAULT_ROBOT_PORT = os.environ.get("LEKIWI_ROBOT_PORT", "/dev/ttyACM0")
DEFAULT_LEADER_PORT = os.environ.get("LEKIWI_LEADER_PORT", "/dev/ttyACM1")
DEFAULT_ROBOT_TYPE = os.environ.get("LEKIWI_ROBOT_TYPE", "lekiwi_client")


# ---------------------------------------------------------------------------
# In-memory session state (single active session at a time, like b601.py)
# ---------------------------------------------------------------------------
_teleop_proc: Optional[subprocess.Popen] = None
_record_proc: Optional[subprocess.Popen] = None
_teleop_started_at: Optional[float] = None
_record_started_at: Optional[float] = None
_teleop_log: List[str] = []
_record_log: List[str] = []
_teleop_last_error: Optional[str] = None
_record_last_error: Optional[str] = None
_teleop_session_id: Optional[str] = None
_record_session_id: Optional[str] = None
_record_repo_id: Optional[str] = None
_record_episode_current: Optional[int] = None
_record_episode_total: Optional[int] = None
_LOG_TAIL_LINES = 60


def _resolve_cli(name: str) -> Optional[List[str]]:
    """Resolve a lerobot-* CLI argv prefix, or None if not installed."""
    try:
        from ._cli_process import resolve_cli_argv
        return resolve_cli_argv(name)
    except Exception:
        import shutil
        which = shutil.which(name)
        return [which] if which else None


def _lerobot_teleoperate_present() -> bool:
    return _resolve_cli("lerobot-teleoperate") is not None


def _lerobot_record_present() -> bool:
    return _resolve_cli("lerobot-record") is not None


def _port_exists(port: str) -> bool:
    return bool(port) and Path(port).exists()


def _push_log(buf: List[str], line: str) -> None:
    line = line.rstrip()
    if not line:
        return
    buf.append(line)
    if len(buf) > _LOG_TAIL_LINES:
        del buf[: len(buf) - _LOG_TAIL_LINES]


def _reader_thread(proc: subprocess.Popen, buf: List[str], on_error: Any) -> None:
    try:
        for line in proc.stdout:
            _push_log(buf, line.decode("utf-8", errors="replace"))
    except Exception as exc:
        on_error(str(exc))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class TeleopStartRequest(BaseModel):
    robot_type: str = DEFAULT_ROBOT_TYPE
    deployment_mode: str = "remote"
    remote_ip: str = DEFAULT_REMOTE_IP
    command_port: int = DEFAULT_CMD_PORT
    observation_port: int = DEFAULT_OBSERVATION_PORT
    robot_port: str = DEFAULT_ROBOT_PORT
    leader_port: str = DEFAULT_LEADER_PORT
    display_data: bool = False
    restart: bool = True


class RecordStartRequest(BaseModel):
    repo_id: str
    single_task: str = "lekiwi handshake"
    robot_type: str = DEFAULT_ROBOT_TYPE
    deployment_mode: str = "remote"
    remote_ip: str = DEFAULT_REMOTE_IP
    command_port: int = DEFAULT_CMD_PORT
    observation_port: int = DEFAULT_OBSERVATION_PORT
    robot_port: str = DEFAULT_ROBOT_PORT
    leader_port: str = DEFAULT_LEADER_PORT
    num_episodes: int = 5
    episode_time_s: int = 30
    reset_time_s: int = 5


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
def _tcp_reachable(host: str, port: int, timeout_s: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


@router.get("/health")
async def lekiwi_health() -> JSONResponse:
    wired_port_present = _port_exists(DEFAULT_ROBOT_PORT)
    leader_present = _port_exists(DEFAULT_LEADER_PORT)
    lerobot_teleop = _lerobot_teleoperate_present()
    lerobot_record = _lerobot_record_present()
    command_reachable, observations_reachable = await asyncio.gather(
        asyncio.to_thread(_tcp_reachable, DEFAULT_REMOTE_IP, DEFAULT_CMD_PORT),
        asyncio.to_thread(
            _tcp_reachable, DEFAULT_REMOTE_IP, DEFAULT_OBSERVATION_PORT
        ),
    )
    remote_host_ready = command_reachable and observations_reachable
    ok = lerobot_teleop and remote_host_ready
    issues: List[str] = []
    if not lerobot_teleop:
        issues.append("lerobot-teleoperate 未安装")
    if not lerobot_record:
        issues.append("lerobot-record 未安装")
    if not command_reachable:
        issues.append(
            f"LeKiwi Host 命令端口不可达：{DEFAULT_REMOTE_IP}:{DEFAULT_CMD_PORT}"
        )
    if not observations_reachable:
        issues.append(
            f"LeKiwi Host 图像端口不可达：{DEFAULT_REMOTE_IP}:{DEFAULT_OBSERVATION_PORT}"
        )
    if not leader_present:
        issues.append(f"主臂串口未找到：{DEFAULT_LEADER_PORT}")

    return JSONResponse(
        {
            "runtime_id": "lekiwi",
            "ok": ok,
            "deployment_mode": "remote",
            "remote_ip": DEFAULT_REMOTE_IP,
            "command_port": DEFAULT_CMD_PORT,
            "observation_port": DEFAULT_OBSERVATION_PORT,
            "command_reachable": command_reachable,
            "observations_reachable": observations_reachable,
            "remote_host_ready": remote_host_ready,
            "robot_port": DEFAULT_ROBOT_PORT,
            "wired_port_present": wired_port_present,
            "leader_port": DEFAULT_LEADER_PORT,
            "robot_type": DEFAULT_ROBOT_TYPE,
            "leader_present": leader_present,
            "lerobot_teleoperate": lerobot_teleop,
            "lerobot_record": lerobot_record,
            "motor_bus": "Feetech STS3215 · one serial bus · IDs 1–9",
            "teleop_running": _teleop_proc is not None and _teleop_proc.poll() is None,
            "record_running": _record_proc is not None and _record_proc.poll() is None,
            "issues": issues,
        }
    )


# ---------------------------------------------------------------------------
# Teleop
# ---------------------------------------------------------------------------
def _build_teleop_cmd(req: TeleopStartRequest) -> List[str]:
    cli = _resolve_cli("lerobot-teleoperate")
    if cli is None:
        raise HTTPException(500, "lerobot-teleoperate not installed")
    if req.deployment_mode not in {"remote", "wired"}:
        raise HTTPException(422, "deployment_mode must be `remote` or `wired`")
    robot_type = "lekiwi_client" if req.deployment_mode == "remote" else "lekiwi"
    cmd = [
        *cli,
        "--robot.type", robot_type,
        "--robot.id", "botversex-lekiwi",
        "--teleop.type", "so101_leader",
        "--teleop.port", req.leader_port,
        "--teleop.id", "botversex-leader",
    ]
    if req.deployment_mode == "remote":
        cmd.extend(
            [
                "--robot.remote_ip", req.remote_ip,
                "--robot.port_zmq_cmd", str(req.command_port),
                "--robot.port_zmq_observations", str(req.observation_port),
            ]
        )
    else:
        cmd.extend(["--robot.port", req.robot_port])
    if req.display_data:
        cmd.extend(["--display_data", "true"])
    return cmd


@router.post("/teleop/start")
async def lekiwi_teleop_start(req: TeleopStartRequest) -> JSONResponse:
    global _teleop_proc, _teleop_started_at, _teleop_last_error, _teleop_session_id
    if _teleop_proc is not None and _teleop_proc.poll() is None:
        if not req.restart:
            return JSONResponse({"ok": True, "message": "teleop already running"}, status_code=200)
        await _stop_teleop()

    cmd = _build_teleop_cmd(req)
    _teleop_session_id = f"lekiwi-teleop-{uuid.uuid4().hex[:8]}"
    _teleop_log.clear()
    _teleop_last_error = None
    _push_log(_teleop_log, "$ " + " ".join(cmd))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "RERUN": "off"},
        )
    except FileNotFoundError as exc:
        _teleop_last_error = str(exc)
        raise HTTPException(500, f"failed to spawn lerobot-teleoperate: {exc}")

    _teleop_proc = proc
    _teleop_started_at = time.time()
    # Start a daemon thread to drain stdout into _teleop_log
    import threading
    threading.Thread(
        target=_reader_thread,
        args=(proc, _teleop_log, lambda e: setattr(_teleop_last_error, "_last_error", e)),
        daemon=True,
    ).start()
    return JSONResponse(
        {
            "ok": True,
            "session_id": _teleop_session_id,
            "pid": proc.pid,
            "message": "teleop starting",
        }
    )


async def _stop_teleop() -> None:
    global _teleop_proc, _teleop_started_at
    proc = _teleop_proc
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        await asyncio.to_thread(proc.wait, timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
    _teleop_proc = None
    _teleop_started_at = None


@router.post("/teleop/stop")
async def lekiwi_teleop_stop() -> JSONResponse:
    await _stop_teleop()
    return JSONResponse(
        {
            "ok": True,
            "message": "遥操已停止；LeKiwi Host 的 500ms watchdog 会将底盘速度归零",
        }
    )


@router.get("/teleop/status")
async def lekiwi_teleop_status() -> JSONResponse:
    proc = _teleop_proc
    running = proc is not None and proc.poll() is None
    return JSONResponse(
        {
            "running": running,
            "starting": running and _teleop_started_at is not None and (time.time() - _teleop_started_at) < 30,
            "session_id": _teleop_session_id,
            "pid": proc.pid if proc else None,
            "started_at": _teleop_started_at,
            "uptime_s": (time.time() - _teleop_started_at) if running and _teleop_started_at else None,
            "log_tail": list(_teleop_log),
            "last_error": _teleop_last_error,
        }
    )


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------
def _build_record_cmd(req: RecordStartRequest) -> List[str]:
    cli = _resolve_cli("lerobot-record")
    if cli is None:
        raise HTTPException(500, "lerobot-record not installed")
    if req.deployment_mode not in {"remote", "wired"}:
        raise HTTPException(422, "deployment_mode must be `remote` or `wired`")
    robot_type = "lekiwi_client" if req.deployment_mode == "remote" else "lekiwi"
    cmd = [
        *cli,
        "--robot.type", robot_type,
        "--robot.id", "botversex-lekiwi",
        "--teleop.type", "so101_leader",
        "--teleop.port", req.leader_port,
        "--teleop.id", "botversex-leader",
        "--dataset.repo_id", req.repo_id,
        "--dataset.single_task", req.single_task,
        "--dataset.num_episodes", str(req.num_episodes),
        "--dataset.episode_time_s", str(req.episode_time_s),
        "--dataset.reset_time_s", str(req.reset_time_s),
    ]
    if req.deployment_mode == "remote":
        cmd.extend(
            [
                "--robot.remote_ip", req.remote_ip,
                "--robot.port_zmq_cmd", str(req.command_port),
                "--robot.port_zmq_observations", str(req.observation_port),
            ]
        )
    else:
        cmd.extend(["--robot.port", req.robot_port])
    return cmd


@router.post("/record/start")
async def lekiwi_record_start(req: RecordStartRequest) -> JSONResponse:
    global _record_proc, _record_started_at, _record_last_error, _record_session_id, _record_repo_id, _record_episode_current, _record_episode_total
    if _record_proc is not None and _record_proc.poll() is None:
        raise HTTPException(409, "record already running — stop first")
    # Stop teleop first (they share the same CAN bus)
    await _stop_teleop()

    cmd = _build_record_cmd(req)
    _record_session_id = f"lekiwi-record-{uuid.uuid4().hex[:8]}"
    _record_repo_id = req.repo_id
    _record_episode_total = req.num_episodes
    _record_episode_current = 0
    _record_log.clear()
    _record_last_error = None
    _push_log(_record_log, "$ " + " ".join(cmd))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "RERUN": "off"},
        )
    except FileNotFoundError as exc:
        _record_last_error = str(exc)
        raise HTTPException(500, f"failed to spawn lerobot-record: {exc}")

    _record_proc = proc
    _record_started_at = time.time()
    import threading
    threading.Thread(
        target=_reader_thread,
        args=(proc, _record_log, lambda e: None),
        daemon=True,
    ).start()
    return JSONResponse(
        {
            "ok": True,
            "session_id": _record_session_id,
            "pid": proc.pid,
            "repo_id": req.repo_id,
            "message": "record starting",
        }
    )


@router.post("/record/stop")
async def lekiwi_record_stop() -> JSONResponse:
    global _record_proc, _record_started_at
    proc = _record_proc
    if proc is None:
        return JSONResponse({"ok": True, "message": "no record running"})
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        await asyncio.to_thread(proc.wait, timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
    _record_proc = None
    _record_started_at = None
    return JSONResponse({"ok": True})


@router.get("/record/status")
async def lekiwi_record_status() -> JSONResponse:
    global _record_episode_total
    proc = _record_proc
    running = proc is not None and proc.poll() is None
    # Best-effort: parse "Episode N/M" from log tail
    current = _record_episode_current
    for line in reversed(_record_log[-10:]):
        if "Episode" in line and "/" in line:
            try:
                tag = line.split("Episode", 1)[1].strip().split()[0]
                if "/" in tag:
                    cur_str, total_str = tag.split("/", 1)
                    current = int(cur_str)
                    if _record_episode_total is None:
                        _record_episode_total = int(total_str)
            except (ValueError, IndexError):
                continue
            break
    return JSONResponse(
        {
            "running": running,
            "session_id": _record_session_id,
            "pid": proc.pid if proc else None,
            "started_at": _record_started_at,
            "uptime_s": (time.time() - _record_started_at) if running and _record_started_at else None,
            "repo_id": _record_repo_id,
            "episode_current": current,
            "episode_total": _record_episode_total,
            "log_tail": list(_record_log),
            "last_error": _record_last_error,
        }
    )


# ---------------------------------------------------------------------------
# Emergency disable
# ---------------------------------------------------------------------------
@router.post("/disable")
async def lekiwi_disable() -> JSONResponse:
    """Emergency stop local sessions.

    The remote host owns motor torque. Its watchdog zeros base velocity after
    500ms without commands; a physical torque cut must happen on the robot.
    """
    global _record_proc
    await _stop_teleop()
    if _record_proc is not None and _record_proc.poll() is None:
        try:
            os.killpg(_record_proc.pid, signal.SIGTERM)
        except Exception:
            pass
        _record_proc = None
    return JSONResponse(
        {
            "ok": True,
            "base_stop": "watchdog",
            "torque_disabled": False,
            "message": "本地会话已停止；底盘由 Host watchdog 自动归零。远程架构无法伪造断扭矩，请使用机器人实体急停/断电。",
        }
    )


# ===========================================================================
# P2 closed loop — LeKiwi handshake data plan
# ===========================================================================
#
# Implements the "采集完成 → 自动算 norm_stats → 续训 → sync_model_to_remote
# 热加载" chain. The frontend calls /handshake/plan on a timer to render the
# L1/L2/L3 progress card; when a new tier is reached it calls
# /handshake/auto_continue to kick off the chain in background.
#
# The chain is intentionally tolerant: each step logs + persists status to
# /tmp/lekiwi_handshake_status.json, and any failure is non-fatal (the user
# can retry). Training is submitted to the API server (POST /api/v1/trainings)
# which fronts Qualia; sync_model goes through the existing
# /api/b601/inference/sync_model endpoint so it reuses RemoteComputeNode.

import json
import threading

# L-tier thresholds (matches LeKiwiHandshakeProgressCard defaults)
DEFAULT_L1_TARGET = 20
DEFAULT_L2_TARGET = 50
DEFAULT_L3_TARGET = 100

_HANDSHAKE_STATUS_PATH = Path("/tmp/lekiwi_handshake_status.json")
_handshake_chain_thread: Optional[threading.Thread] = None
_handshake_chain_running = False


def _lerobot_cache_dir() -> Path:
    """Local LeRobot dataset cache root (~/.cache/huggingface/lerobot/datasets)."""
    return Path.home() / ".cache" / "huggingface" / "lerobot" / "datasets"


def _dataset_path(repo_id: str) -> Path:
    """Resolve local LeRobot dataset path for a repo_id (owner/name)."""
    # LeRobot stores datasets as owner--name under the datasets cache dir
    safe = repo_id.replace("/", "--")
    return _lerobot_cache_dir() / safe


def _count_episodes(repo_id: str) -> int:
    """Best-effort episode count for a LeRobot dataset.

    LeRobot v2 datasets store episodes as parquet files under data/. We
    count unique episode_index values; if the dataset isn't found or the
    format is unexpected, return 0.
    """
    ds_path = _dataset_path(repo_id)
    if not ds_path.exists():
        return 0
    # Try parquet count via pyarrow if available
    try:
        import pyarrow.parquet as pq  # type: ignore
        data_dir = ds_path / "data"
        if not data_dir.is_dir():
            return 0
        episodes: set[int] = set()
        for pq_file in data_dir.rglob("*.parquet"):
            try:
                table = pq.read_table(pq_file, columns=["episode_index"])
                episodes.update(table.column("episode_index").to_pylist())
            except Exception:
                continue
        return len(episodes)
    except ImportError:
        pass
    # Fallback: count episode_*.mp4 or episode_index dirs
    meta = ds_path / "meta" / "episodes.jsonl"
    if meta.exists():
        try:
            with meta.open() as f:
                return sum(1 for _ in f)
        except OSError:
            return 0
    # Last resort: count video files
    videos = list(ds_path.rglob("episode_*.mp4"))
    return len(videos)


def _tier_reached(current: int, l1: int, l2: int, l3: int) -> Optional[str]:
    """Return the highest tier just reached, or None."""
    if current >= l3:
        return "L3"
    if current >= l2:
        return "L2"
    if current >= l1:
        return "L1"
    return None


def _write_handshake_status(**kwargs: Any) -> None:
    payload = {"ts": time.time(), **kwargs}
    try:
        _HANDSHAKE_STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False))
    except OSError as exc:
        logger.warning("handshake status write failed: %s", exc)


class HandshakePlanRequest(BaseModel):
    repo_id: str
    l1_target: int = DEFAULT_L1_TARGET
    l2_target: int = DEFAULT_L2_TARGET
    l3_target: int = DEFAULT_L3_TARGET


@router.post("/handshake/plan")
async def lekiwi_handshake_plan(req: HandshakePlanRequest) -> JSONResponse:
    """Read episode count for a LeRobot dataset and compute L1/L2/L3 progress."""
    current = await asyncio.to_thread(_count_episodes, req.repo_id)
    tier = _tier_reached(current, req.l1_target, req.l2_target, req.l3_target)
    return JSONResponse(
        {
            "ok": True,
            "repo_id": req.repo_id,
            "current_episodes": current,
            "l1_target": req.l1_target,
            "l2_target": req.l2_target,
            "l3_target": req.l3_target,
            "tier_reached": tier,
            "dataset_path": str(_dataset_path(req.repo_id)),
            "dataset_exists": _dataset_path(req.repo_id).exists(),
        }
    )


class AutoContinueRequest(BaseModel):
    repo_id: str
    l1_target: int = DEFAULT_L1_TARGET
    l2_target: int = DEFAULT_L2_TARGET
    l3_target: int = DEFAULT_L3_TARGET
    # Training submission (POST /api/v1/trainings on the API server)
    api_base_url: str = "http://127.0.0.1:8000"
    api_token: Optional[str] = None
    algorithm: str = "pi05"  # pi05 | act | smolvla
    dataset_id: Optional[str] = None  # internal dataset id; defaults to repo_id
    model_id: Optional[str] = None  # base model to continue from
    # sync_model_to_remote args
    node_id: Optional[str] = None
    remote_dir: Optional[str] = None
    task_prompt: str = "lekiwi handshake"
    # Norm stats script (lingbot_configs/make_norm_stats.py from GB10)
    norm_stats_script: Optional[str] = None  # auto-detect if None


def _detect_norm_stats_script() -> Optional[Path]:
    """Look for make_norm_stats.py in common locations."""
    candidates = [
        Path.home() / "brainbot" / "lingbot_configs" / "make_norm_stats.py",
        Path.home() / "rebot_lerobot" / "lingbot_configs" / "make_norm_stats.py",
        Path("/home/amd/brainbot/lingbot_configs/make_norm_stats.py"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _run_chain(req: AutoContinueRequest, current_episodes: int, tier: str) -> None:
    """Background chain: norm_stats → train → sync_model_to_remote.

    Each step writes status to /tmp/lekiwi_handshake_status.json. Failures
    are logged but don't abort the chain — the user can retry.
    """
    global _handshake_chain_running
    try:
        _write_handshake_status(
            phase="norm_stats",
            tier=tier,
            current_episodes=current_episodes,
            repo_id=req.repo_id,
            started=True,
        )
        # --- Step 1: norm_stats ---
        script = Path(req.norm_stats_script) if req.norm_stats_script else _detect_norm_stats_script()
        norm_ok = True
        norm_log = ""
        if script and script.is_file():
            try:
                proc = subprocess.run(
                    [sys.executable, str(script), "--repo-id", req.repo_id],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                norm_ok = proc.returncode == 0
                norm_log = (proc.stdout + proc.stderr)[-2000:]
            except Exception as exc:
                norm_ok = False
                norm_log = str(exc)
        else:
            norm_log = "norm_stats script not found — skipping (dataset will use defaults)"

        _write_handshake_status(
            phase="train",
            tier=tier,
            current_episodes=current_episodes,
            repo_id=req.repo_id,
            norm_stats_ok=norm_ok,
            norm_stats_log=norm_log,
        )

        # --- Step 2: submit training to API server ---
        train_ok = False
        train_log = ""
        job_id = None
        try:
            import httpx
            headers = {"Content-Type": "application/json"}
            if req.api_token:
                headers["Authorization"] = f"Bearer {req.api_token}"
            body = {
                "dataset_id": req.dataset_id or req.repo_id,
                "algo": req.algorithm,
                "train_backend": "qualia",
                "epochs": 1,
                "batch_size": 8,
                "model_id": req.model_id,
            }
            async def _post():
                async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
                    return await client.post(
                        f"{req.api_base_url}/api/v1/trainings",
                        json=body,
                        headers=headers,
                    )
            resp = asyncio.run(_post())
            if resp.status_code == 201:
                data = resp.json()
                job_id = str(data.get("id") or "")
                train_ok = True
                train_log = f"submitted job {job_id}"
            else:
                train_log = f"API {resp.status_code}: {resp.text[:500]}"
        except Exception as exc:
            train_log = f"train submit failed: {exc}"

        _write_handshake_status(
            phase="sync",
            tier=tier,
            current_episodes=current_episodes,
            repo_id=req.repo_id,
            norm_stats_ok=norm_ok,
            train_ok=train_ok,
            train_job_id=job_id,
            train_log=train_log,
        )

        # --- Step 3: sync_model_to_remote (only if we got a job_id) ---
        sync_ok = False
        sync_log = ""
        if job_id:
            try:
                import httpx
                # Call our own /api/b601/inference/sync_model endpoint (same process)
                sync_body = {
                    "job_id": job_id,
                    "node_id": req.node_id,
                    "remote_dir": req.remote_dir,
                    "load": True,
                    "task_prompt": req.task_prompt,
                }
                async def _sync_post():
                    async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                        return await client.post(
                            "http://127.0.0.1:8002/api/b601/inference/sync_model",
                            json=sync_body,
                        )
                resp = asyncio.run(_sync_post())
                if resp.status_code == 200:
                    sync_ok = True
                    sync_log = f"sync started: {resp.json()}"
                else:
                    sync_log = f"sync {resp.status_code}: {resp.text[:500]}"
            except Exception as exc:
                sync_log = f"sync failed: {exc}"
        else:
            sync_log = "skipped — no train job_id"

        _write_handshake_status(
            phase="done",
            tier=tier,
            current_episodes=current_episodes,
            repo_id=req.repo_id,
            norm_stats_ok=norm_ok,
            train_ok=train_ok,
            train_job_id=job_id,
            train_log=train_log,
            sync_ok=sync_ok,
            sync_log=sync_log,
            finished=True,
        )
    except Exception as exc:
        _write_handshake_status(
            phase="error",
            tier=tier,
            current_episodes=current_episodes,
            repo_id=req.repo_id,
            error=str(exc),
            finished=True,
        )
    finally:
        _handshake_chain_running = False


@router.post("/handshake/auto_continue")
async def lekiwi_handshake_auto_continue(req: AutoContinueRequest) -> JSONResponse:
    """Trigger the P2 closed-loop chain in background.

    Reads the dataset episode count; if a new L-tier is reached, kicks off
    norm_stats → train → sync_model_to_remote. Returns immediately with the
    plan; the chain runs in a daemon thread and writes status to
    /tmp/lekiwi_handshake_status.json (read via /handshake/auto_continue/status).
    """
    global _handshake_chain_thread, _handshake_chain_running
    if _handshake_chain_running:
        return JSONResponse(
            {"ok": False, "error": "auto-continue chain already running"},
            status_code=409,
        )
    current = await asyncio.to_thread(_count_episodes, req.repo_id)
    tier = _tier_reached(current, req.l1_target, req.l2_target, req.l3_target)
    if tier is None:
        return JSONResponse(
            {
                "ok": True,
                "triggered": False,
                "current_episodes": current,
                "message": f"未达到任何 L 层（需 {req.l1_target} 集才到 L1）",
            }
        )

    _handshake_chain_running = True
    _handshake_chain_thread = threading.Thread(
        target=_run_chain,
        args=(req, current, tier),
        daemon=True,
    )
    _handshake_chain_thread.start()
    return JSONResponse(
        {
            "ok": True,
            "triggered": True,
            "tier_reached": tier,
            "current_episodes": current,
            "message": f"已达到 {tier}，正在后台启动 norm_stats → 训练 → 同步链路",
        }
    )


@router.get("/handshake/auto_continue/status")
async def lekiwi_handshake_auto_continue_status() -> JSONResponse:
    """Read the latest chain status from /tmp/lekiwi_handshake_status.json."""
    if not _HANDSHAKE_STATUS_PATH.is_file():
        return JSONResponse({"ok": True, "phase": "idle", "running": _handshake_chain_running})
    try:
        data = json.loads(_HANDSHAKE_STATUS_PATH.read_text())
        data["running"] = _handshake_chain_running
        return JSONResponse({"ok": True, **data})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc), "running": _handshake_chain_running})
