"""Reachy Mini daemon proxy.

BotverseX owns the platform-facing API. For the USB-only Reachy Mini variant,
the Pollen/Allan daemon runs locally on this machine and talks to the robot over
serial (for example /dev/ttyACM0).
"""
from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .platform_paths import (
    default_log_path,
    is_windows,
    iter_serial_port_candidates,
    serial_port_exists,
    venv_executable,
)
from .robot_config import get_robot_manifest, get_service_config, get_transport_config


router = APIRouter(prefix="/api/reachy", tags=["reachy-mini"])
ws_router = APIRouter(tags=["reachy-mini"])

REACHY_MINI_JOINT_NAMES = [
    "body_rotation",
    "stewart_1",
    "stewart_2",
    "stewart_3",
    "stewart_4",
    "stewart_5",
    "stewart_6",
    "right_antenna",
    "left_antenna",
]

REALTIME_ROOT = Path(__file__).parent.parent.resolve()
LOCAL_MOVES_DIR = REALTIME_ROOT / "data" / "reachy_mini_moves"
CUSTOM_MOVE_CATEGORY = "custom"
REACHY_RUNTIME_ID = "reachy_mini"
DEFAULT_RECORD_HZ = 10.0
# Official SDK async_play_move defaults to 100 Hz set_target streaming; 50 Hz is enough over HTTP.
PLAYBACK_FREQUENCY_HZ = 50.0
PLAYBACK_INITIAL_GOTO_S = 0.15
# Legacy goto playback cap (unused after set_target rewrite; kept for tests referencing the constant).
MAX_PLAYBACK_SEGMENT_S = 0.35
IDENTITY_HEAD_MATRIX = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

_local_daemon_process: subprocess.Popen[str] | None = None

# In-memory Reachy record / virtual / local playback state (single-process realtime).
_record_session: dict[str, Any] = {
    "active": False,
    "captured": False,
    "name": "",
    "display_name": "",
    "description": "",
    "sample_hz": DEFAULT_RECORD_HZ,
    "started_at": 0.0,
    "frames": [],
    "task": None,
}
_virtual: dict[str, Any] = {
    "active": False,
    "state": {},
    "motor_mode": "disabled",
}
_playback_tasks: dict[str, asyncio.Task[None]] = {}
_playback_cancel: dict[str, asyncio.Event] = {}

# Reachy Mini body_rotation motor (Dynamixel ID 10) — used for USB port autodetect.
_REACHY_PROBE_MOTOR_ID = 10
_SERIAL_DETECT_CACHE_TTL_S = 30.0
_serial_detect_cache: dict[str, Any] = {
    "port": None,
    "expires_at": 0.0,
    "source": None,
}
# Serial port used by the last successfully started managed daemon (port may be busy while running).
_active_daemon_serial: str | None = None


def _reachy_host() -> str:
    service = get_service_config(REACHY_RUNTIME_ID)
    return os.environ.get("REACHY_MINI_HOST", str(service.get("host") or "127.0.0.1"))


def _reachy_port() -> int:
    service = get_service_config(REACHY_RUNTIME_ID)
    raw = os.environ.get("REACHY_MINI_PORT", str(service.get("port") or 8010))
    try:
        return int(raw)
    except ValueError:
        return int(service.get("port") or 8010)


def _configured_serial_port() -> str:
    transport = get_transport_config(REACHY_RUNTIME_ID)
    ports = transport.get("ports") or {}
    return str(ports.get("serial") or "auto")


def _invalidate_serial_detect_cache() -> None:
    _serial_detect_cache["port"] = None
    _serial_detect_cache["expires_at"] = 0.0
    _serial_detect_cache["source"] = None


def _daemon_tcp_open(timeout_s: float = 0.4) -> bool:
    try:
        with socket.create_connection((_reachy_host(), _reachy_port()), timeout=timeout_s):
            return True
    except OSError:
        return False


def _daemon_log_tail_text(max_lines: int = 80) -> str:
    lines = _daemon_log_tail(max_lines=max_lines)
    return "\n".join(lines)


def _daemon_log_shows_motor_failure() -> bool:
    """True when the latest daemon boot failed to find motors on the configured port."""
    text = _daemon_log_tail_text()
    if not text:
        return False
    return (
        "No motor found on port" in text
        or "Application startup failed" in text
        or "Motor communication error" in text
    )


def _daemon_log_shows_audio_error() -> bool:
    """True when the latest daemon boot failed because of GStreamer/audio deps.

    M21 audio auto-fallback uses this to retry with `--deactivate-audio`.
    """
    text = _daemon_log_tail_text(max_lines=120)
    if not text:
        return False
    return (
        "gi' module is required for GStreamerAudio" in text
        or "gstreamer installation" in text
        or "GStreamerAudio but could not be imported" in text
        or "MediaManager" in text
        and "audio" in text.lower()
    )


def _serial_port_from_daemon_log(*, trust_only_if_healthy: bool = True) -> str | None:
    """Read the last --serialport from the daemon log (works when the port is busy)."""
    if trust_only_if_healthy and _daemon_log_shows_motor_failure():
        return None
    log_path = _reachy_daemon_log()
    if not log_path.is_file():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    matches = re.findall(r"--serialport\s+(\S+)", text)
    return matches[-1] if matches else None


def _ping_reachy_motor_on_port(port: str) -> bool:
    """Return True if Reachy Mini motor ID 10 responds on this serial port (via SDK rustypot)."""
    sdk_path = _reachy_sdk_path()
    if not sdk_path.exists():
        return False

    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(sdk_path / 'src')!r})\n"
        "from reachy_mini.tools.setup_motor import lookup_for_motor\n"
        f"ok = lookup_for_motor({port!r}, {_REACHY_PROBE_MOTOR_ID}, 1_000_000, silent=True)\n"
        "raise SystemExit(0 if ok else 1)\n"
    )
    probe_timeout = 35.0 if is_windows() else 2.5
    try:
        proc = subprocess.run(
            [_reachy_python(), "-c", code],
            cwd=str(sdk_path),
            capture_output=True,
            timeout=probe_timeout,
            env=_reachy_daemon_env(),
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _auto_detect_reachy_port(*, force: bool = False) -> str | None:
    """Scan USB serial ports for a Reachy Mini motor response."""
    now = time.monotonic()
    cached = _serial_detect_cache.get("port")
    if (
        not force
        and isinstance(cached, str)
        and now < float(_serial_detect_cache.get("expires_at") or 0.0)
        and serial_port_exists(cached)
    ):
        return cached

    try:
        import serial  # noqa: F401
    except ImportError:
        _serial_detect_cache["port"] = None
        _serial_detect_cache["expires_at"] = now + _SERIAL_DETECT_CACHE_TTL_S
        _serial_detect_cache["source"] = "auto"
        return None

    for port in iter_serial_port_candidates():
        if _ping_reachy_motor_on_port(port):
            _serial_detect_cache["port"] = port
            _serial_detect_cache["expires_at"] = now + _SERIAL_DETECT_CACHE_TTL_S
            _serial_detect_cache["source"] = "auto"
            return port

    _serial_detect_cache["port"] = None
    _serial_detect_cache["expires_at"] = now + _SERIAL_DETECT_CACHE_TTL_S
    _serial_detect_cache["source"] = "auto"
    return None


def _resolve_serial_port_meta(*, force_detect: bool = False) -> dict[str, Any]:
    """Resolve serial port with source: env | auto | config | fallback."""
    configured = _configured_serial_port()
    env = os.environ.get("REACHY_MINI_SERIAL_PORT", "").strip()
    if env:
        return {"port": env, "source": "env", "configured": configured}

    if _local_daemon_running() and _active_daemon_serial:
        return {
            "port": _active_daemon_serial,
            "source": "daemon",
            "configured": configured,
        }

    if _daemon_tcp_open():
        from_log = _serial_port_from_daemon_log(trust_only_if_healthy=True)
        if from_log and _ping_reachy_motor_on_port(from_log):
            return {
                "port": from_log,
                "source": "daemon",
                "configured": configured,
            }

    use_auto = configured.lower() == "auto"
    configured_missing = (
        not use_auto
        and configured
        and not serial_port_exists(configured)
    )
    if use_auto or configured_missing:
        detected = _auto_detect_reachy_port(force=force_detect)
        if detected:
            return {"port": detected, "source": "auto", "configured": configured}

    if use_auto:
        candidates = iter_serial_port_candidates()
        fallback = candidates[0] if candidates else ("COM3" if sys.platform == "win32" else "/dev/ttyACM0")
        return {"port": fallback, "source": "fallback", "configured": configured}

    return {"port": configured, "source": "config", "configured": configured}


def _reachy_serial_port(*, force_detect: bool = False) -> str:
    return _resolve_serial_port_meta(force_detect=force_detect)["port"]


def _resolve_serial_port_for_start() -> dict[str, Any]:
    """Pick a serial port with a live Reachy motor before starting the daemon."""
    configured = _configured_serial_port()
    for candidate in iter_serial_port_candidates():
        if _ping_reachy_motor_on_port(candidate):
            return {"port": candidate, "source": "auto", "configured": configured}

    meta = _resolve_serial_port_meta(force_detect=True)
    port = str(meta["port"])
    if Path(port).exists():
        return meta

    acm_ports = iter_serial_port_candidates()
    if acm_ports:
        return {"port": acm_ports[0], "source": "fallback", "configured": configured}
    return meta


async def _stop_broken_daemon_listener() -> None:
    """Stop a reachy daemon that is listening on HTTP but failed motor init (503)."""
    global _local_daemon_process, _active_daemon_serial

    proc = _local_daemon_process
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            await asyncio.get_event_loop().run_in_executor(None, proc.wait, 5)
        except Exception:
            proc.kill()
            await asyncio.get_event_loop().run_in_executor(None, proc.wait)
        _local_daemon_process = None

    if is_windows():
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                    "Where-Object { $_.CommandLine -match 'reachy_mini.daemon.app.main' } | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            subprocess.run(
                ["pkill", "-f", "reachy_mini.daemon.app.main"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    _active_daemon_serial = None
    _invalidate_serial_detect_cache()
    await asyncio.sleep(0.5)


def _reachy_sdk_path() -> Path:
    service = get_service_config(REACHY_RUNTIME_ID)
    return Path(os.environ.get("REACHY_MINI_SDK_PATH", str(service.get("sdk_path") or ""))).expanduser()


def _reachy_daemon_log() -> Path:
    service = get_service_config(REACHY_RUNTIME_ID)
    return Path(
        os.environ.get(
            "REACHY_MINI_LOG_FILE",
            str(service.get("log_file") or default_log_path("botversex_reachy_mini_daemon.log")),
        )
    ).expanduser()


def _reachy_python() -> str:
    configured = os.environ.get("REACHY_MINI_DAEMON_PYTHON")
    if configured:
        return configured
    sdk_path = _reachy_sdk_path()
    venv_python = venv_executable(sdk_path, "python")
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _gi_overlay_path() -> Path:
    """Symlink gi+cairo from system python3-gi without pulling typing_extensions."""
    overlay = Path.home() / ".local/share/botversex/gi_overlay"
    overlay.mkdir(parents=True, exist_ok=True)
    for name in ("gi", "cairo"):
        link = overlay / name
        target = Path(f"/usr/lib/python3/dist-packages/{name}")
        if target.exists() and (not link.exists() or not link.is_symlink()):
            if link.exists() or link.is_symlink():
                link.unlink(missing_ok=True)
            link.symlink_to(target)
    return overlay


def _system_gi_pythonpaths() -> list[str]:
    overlay = _gi_overlay_path()
    if (overlay / "gi").exists():
        return [str(overlay)]
    return [
        p
        for p in (
            "/usr/lib/python3/dist-packages",
            "/usr/local/lib/python3/dist-packages",
        )
        if Path(p).is_dir()
    ]


def _reachy_daemon_env() -> dict[str, str]:
    env = dict(os.environ)
    sdk_src = _reachy_sdk_path() / "src"
    existing = env.get("PYTHONPATH")
    parts = [str(sdk_src), *_system_gi_pythonpaths()]
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _http_base_url() -> str:
    return f"http://{_reachy_host()}:{_reachy_port()}"


def _ws_base_url() -> str:
    return f"ws://{_reachy_host()}:{_reachy_port()}"


def _daemon_url(path: str) -> str:
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{_http_base_url()}{path}"


def _local_categories() -> list[str]:
    if not LOCAL_MOVES_DIR.exists():
        return []
    return sorted(
        p.name for p in LOCAL_MOVES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def _local_moves(category: str) -> list[str]:
    category_dir = LOCAL_MOVES_DIR / category
    if not category_dir.is_dir():
        return []
    return sorted(p.stem for p in category_dir.glob("*.json"))


def _local_daemon_running() -> bool:
    return _local_daemon_process is not None and _local_daemon_process.poll() is None


def _daemon_log_tail(max_lines: int = 10) -> list[str]:
    log_path = _reachy_daemon_log()
    if not log_path.is_file():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-max_lines:]
    except OSError:
        return []


def _reachy_ping_hints(
    *,
    serial: dict[str, Any],
    http_probe: dict[str, Any],
    log_tail: list[str],
    serial_meta: dict[str, Any],
) -> list[str]:
    port = str(serial.get("port") or serial_meta.get("port") or "")
    source = str(serial_meta.get("source") or "")
    configured = str(serial_meta.get("configured") or "")
    hints: list[str] = []

    if source == "auto" and port:
        hints.append(f"已自动检测到 Reachy 串口：{port}（换 USB 口后点「启动守护进程」会重新探测）。")
    elif configured.lower() == "auto" and not port:
        acm_ports = iter_serial_port_candidates()
        if acm_ports:
            hints.append(
                f"未在任何 /dev/ttyACM* 上检测到 Reachy 电机（已扫描：{', '.join(acm_ports)}）。"
                "请确认机器人已通电。"
            )
        else:
            hints.append("未找到 /dev/ttyACM* 设备。请插入 Reachy USB 并确认已通电。")

    log_text = "\n".join(log_tail)
    if "No motor found on port" in log_text:
        hints.append(
            f"守护进程在 {port} 未检测到 Reachy 电机：请确认机器人已通电（不只是 USB 插入），"
            "并确认数据线支持数据传输。"
        )
        other_ports = sorted(p for p in iter_serial_port_candidates() if p != port)
        if other_ports:
            hints.append(
                f"系统上还有其它串口 {', '.join(other_ports)}。"
                "串口设为 auto 时会自动探测；也可设置 REACHY_MINI_SERIAL_PORT 指定端口。"
            )
    elif not http_probe.get("ok"):
        if serial.get("exists"):
            hints.append(
                f"串口 {port} 已找到，但守护进程 HTTP ({http_probe.get('base')}) 不可达。"
                "请点击「启动守护进程」或查看日志。"
            )
        else:
            hints.append(
                f"未找到串口 {port}。请插入 Reachy USB；配置为 auto 时会自动扫描 /dev/ttyACM*。"
            )

    if source == "env":
        hints.append(f"当前使用环境变量 REACHY_MINI_SERIAL_PORT={port}。")

    hints.extend([
        "Plug Reachy Mini into USB and confirm the robot is powered on.",
        "Click Start Local Daemon if daemon_http.ok=false.",
        "If permission denied, add the user running apps/realtime to dialout or fix udev permissions.",
        "Override with REACHY_MINI_SERIAL_PORT to pin a specific /dev/ttyACM* path.",
    ])
    return hints


def _local_daemon_status_payload(http_probe: dict[str, Any] | None = None) -> dict[str, Any]:
    proc_running = _local_daemon_running()
    return {
        "transport": "usb_serial",
        "service": "local_daemon",
        "serial_port": _reachy_serial_port(),
        "sdk_path": str(_reachy_sdk_path()),
        "python": _reachy_python(),
        "pythonpath": _reachy_daemon_env().get("PYTHONPATH"),
        "log_file": str(_reachy_daemon_log()),
        "manifest": get_robot_manifest(REACHY_RUNTIME_ID),
        "daemon_http": http_probe or {
            "base": _http_base_url(),
            "ok": None,
            "error": None,
        },
        "managed_process": {
            "running": proc_running,
            "pid": _local_daemon_process.pid if proc_running and _local_daemon_process else None,
            "returncode": _local_daemon_process.poll() if _local_daemon_process else None,
        },
    }


async def _probe_daemon_http(timeout_s: float | None = None) -> dict[str, Any]:
    if timeout_s is None:
        timeout_s = 15.0 if is_windows() else 2.0
    try:
        async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
            r = await client.get(
                _daemon_url("/api/state/full"),
                params={"with_body_yaw": "true"},
            )
        return {
            "base": _http_base_url(),
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "error": None if r.status_code == 200 else f"HTTP {r.status_code}",
        }
    except Exception as exc:
        return {
            "base": _http_base_url(),
            "ok": False,
            "status_code": None,
            "error": f"{type(exc).__name__}: {exc!s}",
        }


def _serial_status(check_open: bool = False, port: str | None = None) -> dict[str, Any]:
    port = port or _reachy_serial_port()
    path = Path(port)
    status: dict[str, Any] = {
        "port": port,
        "exists": path.exists(),
        "readable": os.access(port, os.R_OK) if path.exists() else False,
        "writable": os.access(port, os.W_OK) if path.exists() else False,
        "openable": None,
        "error": None,
    }
    if not path.exists() or not check_open:
        return status

    try:
        import serial  # type: ignore
    except ImportError as exc:
        status["error"] = f"pyserial_not_installed: {exc!s}"
        return status

    try:
        ser = serial.Serial(port, baudrate=1_000_000, timeout=0.1, write_timeout=0.1)
        ser.close()
        status["openable"] = True
    except Exception as exc:
        status["openable"] = False
        status["error"] = f"{type(exc).__name__}: {exc!s}"
    return status


async def _forward_json(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: Any | None = None,
) -> Response:
    """Forward a request to the Reachy daemon and preserve useful errors."""
    params = dict(request.query_params)
    url = _daemon_url(path)

    try:
        # Ignore ALL_PROXY / HTTP_PROXY / HTTPS_PROXY. Reachy daemon is a LAN
        # endpoint and proxying it breaks (SOCKS requires extra deps).
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.request(method, url, params=params, json=json_body)
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "reachy_daemon_unreachable",
                "message": f"Cannot reach Reachy Mini daemon at {_http_base_url()}",
                "hint": "Use /api/reachy/local-daemon/start for USB Reachy Mini, or set REACHY_MINI_HOST/REACHY_MINI_PORT for an external daemon.",
                "error": str(exc),
            },
        ) from exc

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return JSONResponse(
                status_code=response.status_code,
                content=response.json(),
            )
        except ValueError:
            pass

    return Response(
        status_code=response.status_code,
        content=response.content,
        media_type=content_type or None,
    )


def _to_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _extract_joint_values(state: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Convert Reachy state payloads to BotverseX numeric + named joint maps."""
    head = _to_float_list(state.get("head_joints"))
    target_head = _to_float_list(state.get("target_head_joints"))
    antennas = _to_float_list(
        state.get("antennas_position") or state.get("antenna_positions")
    )

    if not head and target_head:
        head = target_head

    values = [0.0] * len(REACHY_MINI_JOINT_NAMES)
    if head:
        for idx, value in enumerate(head[:7]):
            values[idx] = value
    else:
        try:
            values[0] = float(state.get("body_yaw", 0.0) or 0.0)
        except (TypeError, ValueError):
            values[0] = 0.0

    if antennas:
        if len(antennas) >= 1:
            # The Pollen daemon returns (left, right); BotverseX runtime names are
            # right_antenna, left_antenna, so keep both explicit below.
            values[8] = antennas[0]
        if len(antennas) >= 2:
            values[7] = antennas[1]

    numeric = {str(i + 1): value for i, value in enumerate(values)}
    named = {name: values[i] for i, name in enumerate(REACHY_MINI_JOINT_NAMES)}
    return numeric, named


def _state_envelope(state: dict[str, Any]) -> dict[str, Any]:
    numeric, named = _extract_joint_values(state)
    return {
        "type": "reachy_state",
        "robot_id": "reachy_mini",
        "timestamp": time.time(),
        "state": state,
        "joints": numeric,
        "named_joints": named,
        "virtual": _virtual_active(),
    }


def _virtual_active() -> bool:
    return bool(_virtual.get("active"))


def _default_virtual_state() -> dict[str, Any]:
    return {
        "control_mode": "disabled",
        "head_pose": [row[:] for row in IDENTITY_HEAD_MATRIX],
        "head_joints": [0.0] * 7,
        "target_head_joints": [0.0] * 7,
        "body_yaw": 0.0,
        "target_body_yaw": 0.0,
        "antennas_position": [0.0, 0.0],
        "target_antennas_position": [0.0, 0.0],
    }


def _virtual_state_dict() -> dict[str, Any]:
    state = _virtual.get("state")
    if not isinstance(state, dict) or not state:
        state = _default_virtual_state()
        _virtual["state"] = state
    state["control_mode"] = _virtual.get("motor_mode", "disabled")
    _sync_virtual_head_joints(state)
    return state


def _is_head_matrix(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    return all(isinstance(row, list) and len(row) == 4 for row in value)


def _is_head_rpy_dict(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return any(key in value for key in ("roll", "pitch", "yaw", "x", "y", "z"))


def _head_rpy_dict_to_matrix(head: Any) -> list[list[float]] | None:
    if not _is_head_rpy_dict(head):
        return None
    import math

    try:
        roll = float(head.get("roll", 0.0) or 0.0)
        pitch = float(head.get("pitch", 0.0) or 0.0)
        yaw = float(head.get("yaw", 0.0) or 0.0)
    except (TypeError, ValueError):
        return None

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, 0.0],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, 0.0],
        [-sp, cp * sr, cp * cr, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _head_for_goto_payload(head: Any) -> Any:
    """Daemon accepts XYZRPYPose dict or Matrix4x4Pose {\"matrix\": ...}."""
    if _is_head_matrix(head):
        return {"matrix": head}
    if _is_head_rpy_dict(head):
        return head
    return {"matrix": [row[:] for row in IDENTITY_HEAD_MATRIX]}


def _normalize_virtual_head(frame: dict[str, Any]) -> list[list[float]]:
    head = frame.get("head")
    if _is_head_matrix(head):
        return head
    matrix = _head_rpy_dict_to_matrix(head)
    if matrix:
        return matrix
    return [row[:] for row in IDENTITY_HEAD_MATRIX]


def _sanitize_playback_times(times: list[float], *, max_segment: float = MAX_PLAYBACK_SEGMENT_S) -> list[float]:
    """Preserve ordering but cap gaps (bad recordings used wall-clock while daemon was slow)."""
    if not times:
        return times
    out = [times[0]]
    for t in times[1:]:
        prev = out[-1]
        dt = max(float(t) - prev, 0.02)
        out.append(prev + min(dt, max_segment))
    return out


def _lerp_scalar(v0: float, v1: float, alpha: float) -> float:
    return v0 + alpha * (v1 - v0)


def _lerp_angle(v0: float, v1: float, alpha: float) -> float:
    import math

    diff = ((v1 - v0 + math.pi) % (2 * math.pi)) - math.pi
    return v0 + diff * alpha


def _head_matrix_to_rpy(matrix: list[list[float]]) -> dict[str, float]:
    import math

    try:
        r10 = float(matrix[1][0])
        r11 = float(matrix[1][1])
        r20 = float(matrix[2][0])
        r21 = float(matrix[2][1])
        r22 = float(matrix[2][2])
        tx = float(matrix[0][3]) if len(matrix[0]) > 3 else 0.0
        ty = float(matrix[1][3]) if len(matrix[1]) > 3 else 0.0
        tz = float(matrix[2][3]) if len(matrix[2]) > 3 else 0.0
    except (TypeError, ValueError, IndexError):
        return {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}

    pitch = math.asin(max(-1.0, min(1.0, -r20)))
    roll = math.atan2(r21, r22)
    yaw = math.atan2(r10, r11 if abs(r11) > 1e-6 else 1.0)
    return {"x": tx, "y": ty, "z": tz, "roll": roll, "pitch": pitch, "yaw": yaw}


def _frame_head_to_rpy(head: Any) -> dict[str, float]:
    if _is_head_rpy_dict(head):
        try:
            return {
                "x": float(head.get("x", 0.0) or 0.0),
                "y": float(head.get("y", 0.0) or 0.0),
                "z": float(head.get("z", 0.0) or 0.0),
                "roll": float(head.get("roll", 0.0) or 0.0),
                "pitch": float(head.get("pitch", 0.0) or 0.0),
                "yaw": float(head.get("yaw", 0.0) or 0.0),
            }
        except (TypeError, ValueError):
            pass
    if _is_head_matrix(head):
        return _head_matrix_to_rpy(head)
    return {"x": 0.0, "y": 0.0, "z": 0.0, "roll": 0.0, "pitch": 0.0, "yaw": 0.0}


def _lerp_head_rpy(
    a: dict[str, float], b: dict[str, float], alpha: float
) -> dict[str, float]:
    return {
        "x": _lerp_scalar(a["x"], b["x"], alpha),
        "y": _lerp_scalar(a["y"], b["y"], alpha),
        "z": _lerp_scalar(a["z"], b["z"], alpha),
        "roll": _lerp_angle(a["roll"], b["roll"], alpha),
        "pitch": _lerp_angle(a["pitch"], b["pitch"], alpha),
        "yaw": _lerp_angle(a["yaw"], b["yaw"], alpha),
    }


def _frame_antennas(frame: dict[str, Any]) -> list[float]:
    antennas = _to_float_list(frame.get("antennas"))
    if len(antennas) < 2:
        return [0.0, 0.0]
    return antennas[:2]


def _frame_body_yaw(frame: dict[str, Any]) -> float:
    try:
        return float(frame.get("body_yaw", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pose_delta(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Max joint-space delta between two move frames (for decimation)."""
    ra = _frame_head_to_rpy(a.get("head"))
    rb = _frame_head_to_rpy(b.get("head"))
    delta = 0.0
    for key in ("roll", "pitch", "yaw"):
        delta = max(delta, abs(ra[key] - rb[key]))
    delta = max(delta, abs(_frame_body_yaw(a) - _frame_body_yaw(b)))
    ants_a = _frame_antennas(a)
    ants_b = _frame_antennas(b)
    delta = max(delta, abs(ants_a[0] - ants_b[0]), abs(ants_a[1] - ants_b[1]))
    return delta


def _decimate_move_keyframes(
    times: list[float],
    frames: list[dict[str, Any]],
    *,
    min_interval_s: float = 0.12,
    min_pose_delta: float = 0.015,
) -> tuple[list[float], list[dict[str, Any]]]:
    """Drop redundant 10 Hz hand-recorded samples; playback interpolates between kept poses."""
    if len(times) <= 2 or len(frames) <= 2:
        return times, frames
    kept = [0]
    for index in range(1, len(times) - 1):
        last = kept[-1]
        if times[index] - times[last] < min_interval_s:
            continue
        if _pose_delta(frames[last], frames[index]) < min_pose_delta:
            continue
        kept.append(index)
    if kept[-1] != len(times) - 1:
        kept.append(len(times) - 1)
    return [times[i] for i in kept], [frames[i] for i in kept]


def _evaluate_recorded_move(
    t: float,
    times: list[float],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    """Mirror pollen-robotics/reachy_mini RecordedMove.evaluate (linear segment interpolation)."""
    import bisect

    if not times or not frames:
        return {"head": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}, "antennas": [0.0, 0.0], "body_yaw": 0.0}

    frame_count = min(len(times), len(frames))
    times = times[:frame_count]
    frames = frames[:frame_count]

    if t >= times[-1]:
        t = max(times[-1] - 1e-4, times[0])

    index = bisect.bisect_right(times, t)
    idx_prev = index - 1 if index > 0 else 0
    idx_next = index if index < frame_count else idx_prev

    t_prev = times[idx_prev]
    t_next = times[idx_next]
    if t_next == t_prev:
        alpha = 0.0
    else:
        alpha = (t - t_prev) / (t_next - t_prev)

    prev_frame = frames[idx_prev] if isinstance(frames[idx_prev], dict) else {}
    next_frame = frames[idx_next] if isinstance(frames[idx_next], dict) else {}

    head = _lerp_head_rpy(
        _frame_head_to_rpy(prev_frame.get("head")),
        _frame_head_to_rpy(next_frame.get("head")),
        alpha,
    )
    ants_prev = _frame_antennas(prev_frame)
    ants_next = _frame_antennas(next_frame)
    antennas = [
        _lerp_scalar(ants_prev[0], ants_next[0], alpha),
        _lerp_scalar(ants_prev[1], ants_next[1], alpha),
    ]
    body_yaw = _lerp_scalar(_frame_body_yaw(prev_frame), _frame_body_yaw(next_frame), alpha)

    return {"head": head, "antennas": antennas, "body_yaw": body_yaw}


def _head_pose_matrix_to_joints(head: Any, body_yaw: float = 0.0) -> list[float]:
    """Approximate Stewart + body joints from a 4×4 head pose (virtual preview)."""
    import math

    if not _is_head_matrix(head):
        return [body_yaw, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    try:
        r10 = float(head[1][0])
        r11 = float(head[1][1])
        r12 = float(head[1][2])
        r20 = float(head[2][0])
        r21 = float(head[2][1])
        r22 = float(head[2][2])
    except (TypeError, ValueError, IndexError):
        return [body_yaw, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    pitch = math.asin(max(-1.0, min(1.0, -r20)))
    roll = math.atan2(r21, r22)
    yaw = math.atan2(r10, r11 if abs(r11) > 1e-6 else 1.0)

    return [
        body_yaw,
        roll * 0.45,
        pitch * 0.55,
        -pitch * 0.55,
        roll * 0.35,
        yaw * 0.25,
        -yaw * 0.25,
    ]


def _sync_virtual_head_joints(state: dict[str, Any]) -> None:
    """Keep head_joints in sync with head_pose so the 3D preview actually moves."""
    try:
        body_yaw = float(state.get("body_yaw", 0.0) or 0.0)
    except (TypeError, ValueError):
        body_yaw = 0.0
    head_pose = state.get("head_pose")
    joints = _head_pose_matrix_to_joints(head_pose, body_yaw)
    state["head_joints"] = joints
    state["target_head_joints"] = joints[:]


def _state_to_move_frame(state: dict[str, Any]) -> dict[str, Any]:
    head = state.get("head_pose") or state.get("target_head_pose")
    if not _is_head_matrix(head) and not _is_head_rpy_dict(head):
        head = [row[:] for row in IDENTITY_HEAD_MATRIX]
    antennas = _to_float_list(
        state.get("antennas_position") or state.get("antenna_positions")
    )
    if len(antennas) < 2:
        antennas = [0.0, 0.0]
    try:
        body_yaw = float(state.get("body_yaw", state.get("target_body_yaw", 0.0)) or 0.0)
    except (TypeError, ValueError):
        body_yaw = 0.0
    return {
        "head": head,
        "antennas": antennas[:2],
        "body_yaw": body_yaw,
    }


def _apply_frame_to_virtual(frame: dict[str, Any]) -> None:
    state = _virtual_state_dict()
    state["head_pose"] = _normalize_virtual_head(frame)
    antennas = _to_float_list(frame.get("antennas"))
    if len(antennas) < 2:
        antennas = [0.0, 0.0]
    state["antennas_position"] = antennas[:2]
    state["target_antennas_position"] = antennas[:2]
    try:
        body_yaw = float(frame.get("body_yaw", 0.0) or 0.0)
    except (TypeError, ValueError):
        body_yaw = 0.0
    state["body_yaw"] = body_yaw
    state["target_body_yaw"] = body_yaw
    _sync_virtual_head_joints(state)


def _slugify_move_name(name: str) -> str:
    """Filesystem-safe move id; keeps CJK and other Unicode letters (not ASCII-only)."""
    cleaned = name.strip()
    if not cleaned:
        return f"custom_{int(time.time())}"
    slug = re.sub(r'[/\\<>:"|?*\x00-\x1f]+', "_", cleaned)
    slug = re.sub(r"\s+", "_", slug).strip("._")
    if len(slug) > 120:
        slug = slug[:120]
    return slug or f"custom_{int(time.time())}"


def _find_local_move_path(move_name: str) -> Path | None:
    if not LOCAL_MOVES_DIR.exists():
        return None
    stem = Path(move_name).stem
    for category_dir in LOCAL_MOVES_DIR.iterdir():
        if not category_dir.is_dir():
            continue
        candidate = category_dir / f"{stem}.json"
        if candidate.is_file():
            return candidate
    return None


def _load_local_move(move_name: str) -> dict[str, Any] | None:
    path = _find_local_move_path(move_name)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    times = data.get("time")
    frames = data.get("set_target_data")
    if not isinstance(times, list) or not isinstance(frames, list) or not times or not frames:
        return None
    if len(times) != len(frames):
        return None
    return data


async def _daemon_request(
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: Any | None = None,
    timeout_s: float = 10.0,
) -> httpx.Response:
    url = _daemon_url(path)
    async with httpx.AsyncClient(timeout=timeout_s, trust_env=False) as client:
        return await client.request(method, url, params=params, json=json_body)


async def _set_daemon_motor_mode(mode: str) -> dict[str, Any]:
    """Best-effort daemon motor mode switch. Returns {ok, mode, error?}."""
    try:
        response = await _daemon_request(
            "POST", f"/api/motors/set_mode/{mode}", timeout_s=5.0
        )
        ok = response.status_code < 400
        return {"ok": ok, "mode": mode, "http_status": response.status_code}
    except Exception as exc:  # noqa: BLE001 — daemon optional, never block record
        return {"ok": False, "mode": mode, "error": str(exc)}


def _read_control_mode(state: dict[str, Any]) -> str | None:
    value = state.get("control_mode")
    return str(value) if isinstance(value, str) and value else None


async def _fetch_daemon_state() -> dict[str, Any]:
    response = await _daemon_request(
        "GET",
        "/api/state/full",
        params={
            "with_head_joints": "true",
            "with_body_yaw": "true",
            "with_antenna_positions": "true",
            "with_control_mode": "true",
        },
    )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "reachy_daemon_state_failed",
                "message": f"Daemon state/full returned HTTP {response.status_code}",
            },
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Invalid daemon state payload")
    return payload


async def _daemon_goto_frame(frame: dict[str, Any], duration: float) -> None:
    payload: dict[str, Any] = {
        "head_pose": _head_for_goto_payload(frame.get("head")),
        "antennas": frame.get("antennas"),
        "body_yaw": frame.get("body_yaw", 0.0),
        "duration": max(float(duration), 0.05),
        "interpolation": "minjerk",
    }
    response = await _daemon_request("POST", "/api/move/goto", json_body=payload)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "reachy_daemon_goto_failed",
                "message": f"Daemon move/goto returned HTTP {response.status_code}",
            },
        )


async def _daemon_set_target_frame(frame: dict[str, Any]) -> None:
    """High-frequency pose streaming — matches official async_play_move + set_target."""
    payload: dict[str, Any] = {
        "target_head_pose": _head_for_goto_payload(frame.get("head")),
        "target_antennas": _frame_antennas(frame),
        "target_body_yaw": _frame_body_yaw(frame),
    }
    response = await _daemon_request("POST", "/api/move/set_target", json_body=payload, timeout_s=2.0)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "reachy_daemon_set_target_failed",
                "message": f"Daemon move/set_target returned HTTP {response.status_code}",
            },
        )


async def _cancel_all_playbacks() -> None:
    for play_id, event in list(_playback_cancel.items()):
        event.set()
    for task in list(_playback_tasks.values()):
        if not task.done():
            task.cancel()
    _playback_cancel.clear()
    _playback_tasks.clear()


async def _play_local_move_task(play_id: str, move_name: str, move_data: dict[str, Any]) -> None:
    """Play a recorded move like reachy_mini.async_play_move: evaluate + set_target at fixed Hz."""
    cancel_event = _playback_cancel[play_id]
    times = [float(t) for t in move_data.get("time", [])]
    frames = move_data.get("set_target_data", [])
    if not times or not frames:
        return

    frame_count = min(len(times), len(frames))
    times = times[:frame_count]
    frames = [f for f in frames[:frame_count] if isinstance(f, dict)]
    if not frames:
        return

    duration = max(times[-1], 0.05)
    sleep_period = 1.0 / max(PLAYBACK_FREQUENCY_HZ, 1.0)

    if not _virtual_active() and PLAYBACK_INITIAL_GOTO_S > 0:
        start_frame = _evaluate_recorded_move(0.0, times, frames)
        try:
            await _daemon_goto_frame(start_frame, PLAYBACK_INITIAL_GOTO_S)
            await asyncio.sleep(PLAYBACK_INITIAL_GOTO_S)
        except HTTPException:
            pass

    t0 = time.monotonic()
    while True:
        if cancel_event.is_set():
            break

        elapsed = time.monotonic() - t0
        if elapsed >= duration:
            pose = _evaluate_recorded_move(max(duration - 1e-4, 0.0), times, frames)
            if _virtual_active():
                _apply_frame_to_virtual(pose)
            else:
                try:
                    await _daemon_set_target_frame(pose)
                except HTTPException:
                    pass
            break

        t = min(elapsed, duration - 1e-3)
        pose = _evaluate_recorded_move(t, times, frames)
        if _virtual_active():
            _apply_frame_to_virtual(pose)
        else:
            try:
                await _daemon_set_target_frame(pose)
            except HTTPException:
                pass

        loop_elapsed = time.monotonic() - t0 - t
        if loop_elapsed < sleep_period:
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=sleep_period - loop_elapsed)
                break
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(0.001)

    _playback_cancel.pop(play_id, None)
    _playback_tasks.pop(play_id, None)


async def _start_local_playback(move_name: str, move_data: dict[str, Any]) -> dict[str, Any]:
    await _cancel_all_playbacks()
    play_id = str(uuid.uuid4())
    cancel_event = asyncio.Event()
    _playback_cancel[play_id] = cancel_event
    task = asyncio.create_task(_play_local_move_task(play_id, move_name, move_data))
    _playback_tasks[play_id] = task
    return {"uuid": play_id, "status": "playing", "move_name": move_name, "source": "local"}


async def _merged_local_categories(request: Request) -> list[str]:
    local = set(_local_categories())
    try:
        response = await _forward_json(request, "GET", "/api/move/local-categories")
        if isinstance(response, JSONResponse):
            body = response.body
            daemon_cats = json.loads(body.decode()) if body else []
            if isinstance(daemon_cats, list):
                local.update(str(c) for c in daemon_cats)
    except HTTPException as exc:
        if exc.status_code != 502:
            raise
    return sorted(local)


async def _merged_local_moves(category: str, request: Request) -> list[str]:
    local = set(_local_moves(category))
    try:
        response = await _forward_json(
            request,
            "GET",
            f"/api/move/local-moves/list/{category}",
        )
        if isinstance(response, JSONResponse):
            body = response.body
            daemon_moves = json.loads(body.decode()) if body else []
            if isinstance(daemon_moves, list):
                local.update(str(m) for m in daemon_moves)
    except HTTPException as exc:
        if exc.status_code != 502:
            raise
    return sorted(local)


def _record_sample_interval() -> float:
    sample_hz = float(_record_session.get("sample_hz") or DEFAULT_RECORD_HZ)
    return 1.0 / max(sample_hz, 1.0)


def _record_elapsed_from_frames() -> float:
    """Sample-index timing (not wall clock) — matches saved move JSON duration."""
    frames = _record_session.get("frames") or []
    if not frames:
        return 0.0
    return max(len(frames) - 1, 0) * _record_sample_interval()


async def _stop_record_poll_task() -> None:
    _record_session["active"] = False
    task = _record_session.get("task")
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    _record_session["task"] = None


async def _record_poll_loop() -> None:
    interval = _record_sample_interval()
    while _record_session.get("active"):
        try:
            state = await _fetch_daemon_state()
            frame = _state_to_move_frame(state)
            frames = _record_session.setdefault("frames", [])
            # Sample-index timing: wall-clock gaps when daemon is slow must not stretch playback.
            elapsed = len(frames) * interval
            frames.append({"t": elapsed, "data": frame})
        except HTTPException:
            pass
        except Exception:
            pass
        await asyncio.sleep(interval)


def _frames_to_move_json(
    frames: list[dict[str, Any]],
    *,
    description: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    if not frames:
        raise HTTPException(status_code=400, detail="No frames recorded")
    times = [float(f.get("t", 0.0)) for f in frames]
    t0 = times[0]
    normalized_times = [max(t - t0, 0.0) for t in times]
    set_target_data = [f["data"] for f in frames if isinstance(f.get("data"), dict)]
    if not set_target_data:
        raise HTTPException(status_code=400, detail="No valid frames recorded")
    if len(normalized_times) != len(set_target_data):
        normalized_times = normalized_times[: len(set_target_data)]
    normalized_times, set_target_data = _decimate_move_keyframes(
        normalized_times,
        set_target_data,
    )
    payload: dict[str, Any] = {
        "description": description,
        "time": normalized_times,
        "set_target_data": set_target_data,
    }
    if display_name and display_name.strip():
        payload["display_name"] = display_name.strip()
    return payload


class ReachyRecordStartBody(BaseModel):
    name: str | None = None
    description: str | None = None
    sample_hz: float = Field(default=DEFAULT_RECORD_HZ, ge=1.0, le=30.0)
    # Put motors in back-drivable mode for hand-teaching. Default OFF — auto-disabling
    # makes the head collapse (no gravity comp on this firmware). Operator should
    # manually use 扭矩关闭 when they want to hand-pose.
    compliant: bool = False


class ReachyRecordStopBody(BaseModel):
    name: str | None = None
    display_name: str | None = None


class ReachyMoveComposeBody(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    time: list[float]
    set_target_data: list[dict[str, Any]]


def _validate_compose_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        head = frame.get("head")
        if head is None:
            raise HTTPException(status_code=400, detail="Each frame requires head pose")
        antennas = frame.get("antennas")
        if not isinstance(antennas, list) or len(antennas) < 2:
            antennas = [0.0, 0.0]
        try:
            body_yaw = float(frame.get("body_yaw", 0.0) or 0.0)
        except (TypeError, ValueError):
            body_yaw = 0.0
        out.append({
            "head": head,
            "antennas": [float(antennas[0]), float(antennas[1])],
            "body_yaw": body_yaw,
        })
    if not out:
        raise HTTPException(status_code=400, detail="No valid frames in composed move")
    return out


def _save_custom_move_json(
    move_name: str,
    move_json: dict[str, Any],
    *,
    display_name: str | None = None,
) -> Path:
    category_dir = LOCAL_MOVES_DIR / CUSTOM_MOVE_CATEGORY
    category_dir.mkdir(parents=True, exist_ok=True)
    out_path = category_dir / f"{move_name}.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    if display_name and display_name.strip():
        move_json["display_name"] = display_name.strip()
    tmp_path.write_text(json.dumps(move_json, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(out_path)
    return out_path


@router.get("/moves/json/{category}/{move_name}")
async def get_move_json(category: str, move_name: str) -> Response:
    path = LOCAL_MOVES_DIR / category / f"{Path(move_name).stem}.json"
    if not path.is_file():
        path = _find_local_move_path(move_name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Move not found: {move_name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read move: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Invalid move JSON")
    return JSONResponse(content=data)


@router.delete("/moves/{category}/{move_name}")
async def delete_move(category: str, move_name: str) -> Response:
    if category != CUSTOM_MOVE_CATEGORY:
        raise HTTPException(
            status_code=403,
            detail={"code": "move_delete_forbidden", "message": "Only custom moves can be deleted."},
        )
    stem = Path(move_name).stem
    path = LOCAL_MOVES_DIR / category / f"{stem}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Move not found: {move_name}")
    try:
        path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete move: {exc}") from exc
    return JSONResponse(content={"ok": True, "category": category, "move_name": stem})


@router.post("/moves/compose")
async def compose_move(body: ReachyMoveComposeBody) -> Response:
    if not body.time or not body.set_target_data:
        raise HTTPException(status_code=400, detail="time and set_target_data are required")
    if len(body.time) != len(body.set_target_data):
        raise HTTPException(status_code=400, detail="time and set_target_data length mismatch")

    move_name = _slugify_move_name(body.name)
    display_name = (body.display_name or body.name or move_name).strip()
    frames = _validate_compose_frames(body.set_target_data)
    move_json: dict[str, Any] = {
        "description": body.description or display_name,
        "display_name": display_name,
        "time": [float(t) for t in body.time],
        "set_target_data": frames,
    }
    out_path = _save_custom_move_json(move_name, move_json, display_name=display_name)
    duration_s = float(move_json["time"][-1]) if move_json["time"] else 0.0
    return JSONResponse(
        content={
            "ok": True,
            "move_name": move_name,
            "display_name": display_name,
            "category": CUSTOM_MOVE_CATEGORY,
            "path": str(out_path.relative_to(REALTIME_ROOT)),
            "duration_s": duration_s,
            "sample_count": len(frames),
        },
    )


@router.get("/state/full")
async def get_full_state(request: Request) -> Response:
    if _virtual_active():
        return JSONResponse(content=_virtual_state_dict())
    return await _forward_json(request, "GET", "/api/state/full")


@router.get("/motors/status")
async def get_motor_status(request: Request) -> Response:
    if _virtual_active():
        return JSONResponse(content={"mode": _virtual.get("motor_mode", "disabled")})
    return await _forward_json(request, "GET", "/api/motors/status")


@router.post("/motors/set_mode/{mode}")
async def set_motor_mode(mode: str, request: Request) -> Response:
    if _virtual_active():
        _virtual["motor_mode"] = mode
        state = _virtual_state_dict()
        state["control_mode"] = mode
        return JSONResponse(content={"status": "ok", "mode": mode, "virtual": True})
    return await _forward_json(request, "POST", f"/api/motors/set_mode/{mode}")


@router.post("/move/goto")
async def move_goto(request: Request) -> Response:
    body = await request.json()
    if _virtual_active():
        frame = {
            "head": body.get("head_pose"),
            "antennas": body.get("antennas"),
            "body_yaw": body.get("body_yaw", 0.0),
        }
        _apply_frame_to_virtual(frame)
        return JSONResponse(content={"status": "ok", "virtual": True})
    return await _forward_json(
        request,
        "POST",
        "/api/move/goto",
        json_body=body,
    )


@router.post("/move/stop")
async def stop_move(request: Request) -> Response:
    had_playback = bool(_playback_tasks)
    await _cancel_all_playbacks()
    if _virtual_active() or had_playback:
        return JSONResponse(
            content={"status": "stopped", "virtual": _virtual_active(), "local": had_playback},
        )
    body = await request.json()
    return await _forward_json(request, "POST", "/api/move/stop", json_body=body)


@router.get("/move/local-categories")
async def get_local_categories(request: Request) -> Response:
    if _virtual_active():
        return JSONResponse(content=_local_categories())
    merged = await _merged_local_categories(request)
    return JSONResponse(content=merged)


@router.get("/move/local-moves/list/{category}")
async def get_local_moves(category: str, request: Request) -> Response:
    if _virtual_active():
        return JSONResponse(content=_local_moves(category))
    merged = await _merged_local_moves(category, request)
    return JSONResponse(content=merged)


@router.get("/move/local-moves/get/{move_name}")
async def get_local_move_json(move_name: str) -> Response:
    """Return the raw move JSON so browsers can play it in a virtual 3D twin
    without a daemon. Used by the /robots hero and the virtual play page.
    """
    move_data = _load_local_move(move_name)
    if move_data is None:
        raise HTTPException(status_code=404, detail=f"Local move not found: {move_name}")
    return JSONResponse(content=move_data)


@router.post("/move/play/local-move/{move_name}")
async def play_local_move(move_name: str, request: Request) -> Response:
    move_data = _load_local_move(move_name)
    if move_data is not None:
        result = await _start_local_playback(move_name, move_data)
        return JSONResponse(content=result)
    if _virtual_active():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "reachy_move_not_found",
                "message": f"Local move not found: {move_name}",
            },
        )
    return await _forward_json(request, "POST", f"/api/move/play/local-move/{move_name}")


@router.post("/move/play/wake_up")
async def wake_up(request: Request) -> Response:
    if _virtual_active():
        move_data = _load_local_move("wake_up")
        if move_data:
            return JSONResponse(content=await _start_local_playback("wake_up", move_data))
        return JSONResponse(content={"status": "ok", "virtual": True})
    return await _forward_json(request, "POST", "/api/move/play/wake_up")


@router.post("/move/play/goto_sleep")
async def goto_sleep(request: Request) -> Response:
    if _virtual_active():
        move_data = _load_local_move("goto_sleep")
        if move_data:
            return JSONResponse(content=await _start_local_playback("goto_sleep", move_data))
        return JSONResponse(content={"status": "ok", "virtual": True})
    return await _forward_json(request, "POST", "/api/move/play/goto_sleep")


@router.get("/daemon/status")
async def get_daemon_status(request: Request) -> Response:
    return await _forward_json(request, "GET", "/api/daemon/status")


@router.get("/local-daemon/status")
async def get_local_daemon_status() -> Response:
    http_probe = await _probe_daemon_http()
    return JSONResponse(content=_local_daemon_status_payload(http_probe=http_probe))


@router.post("/local-daemon/start")
async def start_local_daemon() -> Response:
    global _local_daemon_process, _active_daemon_serial

    _invalidate_serial_detect_cache()

    http_probe = await _probe_daemon_http(timeout_s=1.0)
    if http_probe["ok"]:
        inferred = _serial_port_from_daemon_log(trust_only_if_healthy=True)
        if inferred:
            _active_daemon_serial = inferred
        elif not _active_daemon_serial:
            _active_daemon_serial = _serial_port_from_daemon_log(trust_only_if_healthy=False)
        return JSONResponse(
            content={
                "ok": True,
                "message": "Reachy Mini local daemon is already reachable.",
                "serial_detection": _resolve_serial_port_meta(force_detect=False),
                **_local_daemon_status_payload(http_probe=http_probe),
            }
        )

    if _daemon_tcp_open() and not http_probe.get("ok"):
        await _stop_broken_daemon_listener()
        http_probe = await _probe_daemon_http(timeout_s=1.0)

    if is_windows() and not http_probe.get("ok"):
        await _stop_broken_daemon_listener()
        http_probe = await _probe_daemon_http(timeout_s=1.0)

    if _local_daemon_running():
        return JSONResponse(
            content={
                "ok": True,
                "message": "Reachy Mini local daemon is already managed by BotverseX.",
                **_local_daemon_status_payload(http_probe=http_probe),
            }
        )

    sdk_path = _reachy_sdk_path()
    if not sdk_path.exists():
        raise HTTPException(
            status_code=500,
            detail={
                "code": "reachy_sdk_path_missing",
                "message": f"Reachy Mini SDK path does not exist: {sdk_path}",
                "hint": "Set REACHY_MINI_SDK_PATH to Allan's reachy_mini_Allan directory.",
            },
        )

    serial_meta = _resolve_serial_port_for_start()
    serial_port = str(serial_meta["port"])
    serial = _serial_status(check_open=False, port=serial_port)
    if not serial["exists"]:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "reachy_serial_missing",
                "message": f"Reachy Mini serial port not found: {serial_port}",
                "hint": "Plug Reachy Mini into USB (power on) or set REACHY_MINI_SERIAL_PORT.",
                "serial": serial,
                "serial_detection": serial_meta,
            },
        )
    if not _ping_reachy_motor_on_port(serial_port):
        scanned = {
            p: _ping_reachy_motor_on_port(p) for p in iter_serial_port_candidates()
        }
        raise HTTPException(
            status_code=400,
            detail={
                "code": "reachy_motor_not_found",
                "message": f"No Reachy motor on {serial_port}. Power on the robot (not only USB).",
                "hint": "Confirm the USB cable supports data. Try another port or set REACHY_MINI_SERIAL_PORT.",
                "serial": serial,
                "serial_detection": serial_meta,
                "scan": scanned,
            },
        )

    service = get_service_config(REACHY_RUNTIME_ID)
    template = service.get("command") or [
        "python",
        "-m",
        "reachy_mini.daemon.app.main",
        "--serialport",
        "{serial}",
        "--fastapi-host",
        "{host}",
        "--fastapi-port",
        "{port}",
        "--no-preload-datasets",
        "--autostart",
    ]
    cmd = [
        _reachy_python() if part == "python" else str(part).format(
            serial=serial_port,
            host=_reachy_host(),
            port=_reachy_port(),
            sdk_path=str(_reachy_sdk_path()),
        )
        for part in template
    ]

    try:
        log_path = _reachy_daemon_log()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = log_path.open("a", encoding="utf-8")
        log_fh.write("\n\n=== BotverseX Reachy Mini local daemon start ===\n")
        log_fh.write(f"cwd={sdk_path}\n")
        log_fh.write(f"cmd={' '.join(cmd)}\n")
        log_fh.flush()
        _local_daemon_process = subprocess.Popen(
            cmd,
            cwd=str(sdk_path),
            env=_reachy_daemon_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _active_daemon_serial = serial_port
        _serial_detect_cache["port"] = serial_port
        _serial_detect_cache["expires_at"] = time.monotonic() + _SERIAL_DETECT_CACHE_TTL_S
        _serial_detect_cache["source"] = "auto"
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "reachy_local_daemon_start_failed",
                "message": f"Failed to start Reachy Mini local daemon: {exc!s}",
                "command": cmd,
            },
        ) from exc

    # Wait for daemon bind (startup can take ~15–25s on first motor scan).
    http_probe = {"ok": False, "base": _http_base_url(), "status_code": None, "error": "starting"}
    audio_fallback_used = False
    for _ in range(30):
        await asyncio.sleep(1.0)
        if _local_daemon_process is not None and _local_daemon_process.poll() is not None:
            break
        http_probe = await _probe_daemon_http(timeout_s=1.0)
        if http_probe.get("ok"):
            break
    if not http_probe.get("ok"):
        _invalidate_serial_detect_cache()
        proc_exited = (
            _local_daemon_process is not None
            and _local_daemon_process.poll() is not None
        )
        # M21 audio auto-fallback: if first boot died because GStreamer/audio
        # deps are missing (very common on dev boxes), retry once with
        # --deactivate-audio so motion still works. Conversation App will be
        # unavailable but the rest of the platform is usable.
        if proc_exited and _daemon_log_shows_audio_error() and "--deactivate-audio" not in cmd:
            _local_daemon_process = None
            _active_daemon_serial = None
            cmd_with_no_audio = cmd + ["--deactivate-audio"]
            try:
                log_fh.write(
                    "\n=== M21 audio auto-fallback: retrying with --deactivate-audio ===\n"
                )
                log_fh.write(f"cmd={' '.join(cmd_with_no_audio)}\n")
                log_fh.flush()
                _local_daemon_process = subprocess.Popen(
                    cmd_with_no_audio,
                    cwd=str(sdk_path),
                    env=_reachy_daemon_env(),
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                _active_daemon_serial = serial_port
                audio_fallback_used = True
                cmd = cmd_with_no_audio
                for _ in range(20):
                    await asyncio.sleep(1.0)
                    if _local_daemon_process is not None and _local_daemon_process.poll() is not None:
                        break
                    http_probe = await _probe_daemon_http(timeout_s=1.0)
                    if http_probe.get("ok"):
                        break
            except Exception:
                pass
        if not http_probe.get("ok") and (
            _local_daemon_process is None or _local_daemon_process.poll() is not None
        ):
            _local_daemon_process = None
            _active_daemon_serial = None
    return JSONResponse(
        content={
            "ok": _local_daemon_running() and bool(http_probe.get("ok")),
            "message": "Reachy Mini local daemon start requested.",
            "command": cmd,
            "serial_detection": serial_meta,
            "audio_fallback_used": audio_fallback_used,
            "audio_warning": (
                "Audio subsystem unavailable (GStreamer/gi missing). "
                "Daemon restarted with --deactivate-audio. "
                "Conversation App and DOA will not work until GStreamer is installed."
                if audio_fallback_used else None
            ),
            **_local_daemon_status_payload(http_probe=http_probe),
        }
    )


@router.post("/local-daemon/stop")
async def stop_local_daemon() -> Response:
    global _local_daemon_process, _active_daemon_serial

    proc = _local_daemon_process
    if proc is None:
        http_probe = await _probe_daemon_http(timeout_s=1.0)
        return JSONResponse(
            content={
                "ok": True,
                "message": "No BotverseX-managed Reachy Mini local daemon process is running.",
                **_local_daemon_status_payload(http_probe=http_probe),
            }
        )

    if proc.poll() is None:
        proc.terminate()
        try:
            await asyncio.get_event_loop().run_in_executor(None, proc.wait, 5)
        except Exception:
            proc.kill()
            await asyncio.get_event_loop().run_in_executor(None, proc.wait)

    _local_daemon_process = None
    _active_daemon_serial = None
    _invalidate_serial_detect_cache()
    http_probe = await _probe_daemon_http(timeout_s=1.0)
    return JSONResponse(
        content={
            "ok": True,
            "message": "BotverseX-managed Reachy Mini local daemon stopped.",
            **_local_daemon_status_payload(http_probe=http_probe),
        }
    )


@router.get("/record/status")
async def get_record_status() -> Response:
    frames = _record_session.get("frames") or []
    elapsed_s = _record_elapsed_from_frames()
    latest_frame = frames[-1].get("data") if frames and isinstance(frames[-1], dict) else None
    return JSONResponse(
        content={
            "active": bool(_record_session.get("active")),
            "captured": bool(_record_session.get("captured")),
            "name": _record_session.get("name") or "",
            "sample_hz": float(_record_session.get("sample_hz") or DEFAULT_RECORD_HZ),
            "sample_count": len(frames),
            "elapsed_s": round(elapsed_s, 3),
            "virtual": _virtual_active(),
            "compliant": bool(_record_session.get("compliant")),
            "control_mode": _record_session.get("control_mode"),
            "latest_frame": latest_frame,
        },
    )


@router.post("/record/start")
async def start_record(body: ReachyRecordStartBody) -> Response:
    if _virtual_active():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reachy_record_virtual_active",
                "message": "Cannot record while virtual mode is active.",
            },
        )
    if _record_session.get("active") or _record_session.get("captured"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reachy_record_already_active",
                "message": "A recording session is already running or awaiting save.",
            },
        )

    http_probe = await _probe_daemon_http()
    if not http_probe.get("ok"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "reachy_daemon_unavailable",
                "message": "Reachy daemon must be online to record.",
                "daemon_http": http_probe,
            },
        )

    raw_name = (body.name or "").strip()
    move_name = _slugify_move_name(raw_name or f"custom_{int(time.time())}")
    display_name = raw_name or move_name

    # Kinesthetic teaching: relax motors so the operator can hand-pose the robot.
    prev_mode: str | None = None
    compliance: dict[str, Any] = {"requested": bool(body.compliant), "applied": False}
    if body.compliant:
        try:
            prev_mode = _read_control_mode(await _fetch_daemon_state())
        except Exception:  # noqa: BLE001
            prev_mode = None
        # Reachy Mini firmware: gravity_compensation errors on this unit, so use
        # "disabled" (limp / back-drivable) for hand-posing during teaching.
        result = await _set_daemon_motor_mode("disabled")
        compliance.update({
            "applied": bool(result.get("ok")),
            "mode": "disabled",
            "previous_mode": prev_mode,
            "detail": result,
        })

    _record_session.update({
        "active": True,
        "captured": False,
        "name": move_name,
        "display_name": display_name,
        "description": body.description or display_name,
        "sample_hz": body.sample_hz,
        "started_at": time.time(),
        "frames": [],
        "compliant": bool(body.compliant),
        "control_mode": compliance.get("mode") if compliance.get("applied") else prev_mode,
        "prev_mode": prev_mode,
    })
    task = asyncio.create_task(_record_poll_loop())
    _record_session["task"] = task

    return JSONResponse(
        content={
            "ok": True,
            "active": True,
            "name": move_name,
            "display_name": display_name,
            "sample_hz": body.sample_hz,
            "category": CUSTOM_MOVE_CATEGORY,
            "compliance": compliance,
        },
    )


@router.post("/record/capture/stop")
async def stop_record_capture() -> Response:
    """Stop sampling immediately (e.g. operator hit Stop) but keep frames until save."""
    if not _record_session.get("active"):
        if _record_session.get("captured"):
            return JSONResponse(
                content={
                    "ok": True,
                    "captured": True,
                    "elapsed_s": round(_record_elapsed_from_frames(), 3),
                    "sample_count": len(_record_session.get("frames") or []),
                },
            )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reachy_record_not_active",
                "message": "No active recording capture.",
            },
        )

    await _stop_record_poll_task()
    _record_session["captured"] = True

    frames = _record_session.get("frames") or []
    return JSONResponse(
        content={
            "ok": True,
            "captured": True,
            "elapsed_s": round(_record_elapsed_from_frames(), 3),
            "sample_count": len(frames),
        },
    )


@router.post("/record/capture/resume")
async def resume_record_capture() -> Response:
    """Resume sampling into the current session (after Stop, before Save)."""
    if _record_session.get("active"):
        raise HTTPException(
            status_code=409,
            detail={"code": "reachy_record_already_capturing", "message": "Capture already running."},
        )
    if not _record_session.get("captured"):
        raise HTTPException(
            status_code=409,
            detail={"code": "reachy_record_not_captured", "message": "No captured session to resume."},
        )

    http_probe = await _probe_daemon_http()
    if not http_probe.get("ok"):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "reachy_daemon_unavailable",
                "message": "Reachy daemon must be online to record.",
            },
        )

    _record_session["captured"] = False
    _record_session["active"] = True
    task = asyncio.create_task(_record_poll_loop())
    _record_session["task"] = task

    return JSONResponse(
        content={
            "ok": True,
            "active": True,
            "captured": False,
            "sample_count": len(_record_session.get("frames") or []),
            "elapsed_s": round(_record_elapsed_from_frames(), 3),
        },
    )


@router.post("/record/discard")
async def discard_record() -> Response:
    """Drop captured frames without saving."""
    await _stop_record_poll_task()
    _record_session.update({
        "captured": False,
        "frames": [],
        "name": "",
        "display_name": "",
        "description": "",
    })
    return JSONResponse(content={"ok": True})


@router.post("/record/stop")
async def stop_record(request: Request) -> Response:
    stop_body = ReachyRecordStopBody()
    try:
        raw = await request.json()
        if isinstance(raw, dict):
            stop_body = ReachyRecordStopBody.model_validate(raw)
    except Exception:
        pass

    if not _record_session.get("active") and not _record_session.get("captured"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reachy_record_not_active",
                "message": "No recording session to save.",
            },
        )

    if _record_session.get("active"):
        await _stop_record_poll_task()
        _record_session["captured"] = True

    _record_session["captured"] = False

    # Re-stiffen motors so the recorded move can be held / played back immediately.
    restore: dict[str, Any] = {"attempted": False}
    if _record_session.get("compliant"):
        result = await _set_daemon_motor_mode("enabled")
        restore = {"attempted": True, "mode": "enabled", "detail": result}

    frames = list(_record_session.get("frames") or [])
    raw_name = (stop_body.name or "").strip()
    if raw_name:
        move_name = _slugify_move_name(raw_name)
        display_name = (stop_body.display_name or raw_name).strip() or move_name
    else:
        move_name = str(_record_session.get("name") or f"custom_{int(time.time())}")
        display_name = str(_record_session.get("display_name") or move_name)
    description = str(_record_session.get("description") or display_name)
    move_json = _frames_to_move_json(
        frames,
        description=description,
        display_name=display_name,
    )

    category_dir = LOCAL_MOVES_DIR / CUSTOM_MOVE_CATEGORY
    category_dir.mkdir(parents=True, exist_ok=True)
    out_path = category_dir / f"{move_name}.json"
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(move_json, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)

    duration_s = float(move_json["time"][-1]) if move_json["time"] else 0.0
    sample_count = len(move_json["set_target_data"])

    _record_session["frames"] = []
    _record_session["name"] = ""
    _record_session["display_name"] = ""
    _record_session["description"] = ""

    return JSONResponse(
        content={
            "ok": True,
            "move_name": move_name,
            "display_name": display_name,
            "category": CUSTOM_MOVE_CATEGORY,
            "path": str(out_path.relative_to(REALTIME_ROOT)),
            "duration_s": duration_s,
            "sample_count": sample_count,
            "restore": restore,
        },
    )


@router.get("/virtual/status")
async def get_virtual_status() -> Response:
    return JSONResponse(
        content={
            "active": _virtual_active(),
            "motor_mode": _virtual.get("motor_mode", "disabled"),
            "playback_count": len(_playback_tasks),
            "recording": bool(_record_session.get("active")),
        },
    )


@router.post("/virtual/start")
async def start_virtual_mode() -> Response:
    if _record_session.get("active") or _record_session.get("captured"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "reachy_record_active",
                "message": "Stop or save recording before entering virtual mode.",
            },
        )

    await _cancel_all_playbacks()
    _virtual["active"] = True
    _virtual["motor_mode"] = "disabled"
    _virtual["state"] = _default_virtual_state()
    return JSONResponse(
        content={
            "ok": True,
            "active": True,
            "message": "Reachy virtual mode started (no hardware).",
        },
    )


@router.post("/virtual/stop")
async def stop_virtual_mode() -> Response:
    await _cancel_all_playbacks()
    _virtual["active"] = False
    _virtual["state"] = {}
    return JSONResponse(
        content={
            "ok": True,
            "active": False,
            "message": "Reachy virtual mode stopped.",
        },
    )


@router.get("/ping")
async def reachy_ping() -> Response:
    """USB-aware debug endpoint for local Reachy Mini daemon readiness."""
    loop = asyncio.get_running_loop()

    host = _reachy_host()
    port = _reachy_port()

    resolved: dict[str, Any] = {"host": host, "port": port, "ips": []}
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        ips: list[str] = []
        for info in infos:
            addr = info[4][0]
            if addr not in ips:
                ips.append(addr)
        resolved["ips"] = ips
    except Exception as exc:
        resolved["resolve_error"] = f"{type(exc).__name__}: {exc!s}"

    http_probe = await _probe_daemon_http()
    serial_meta = await loop.run_in_executor(None, _resolve_serial_port_meta)
    serial = await loop.run_in_executor(
        None,
        lambda: _serial_status(
            check_open=not bool(http_probe["ok"]),
            port=str(serial_meta["port"]),
        ),
    )
    log_tail = _daemon_log_tail()

    return JSONResponse(
        content={
            "ok": bool(http_probe["ok"]) and bool(serial["exists"]),
            "transport": "usb_serial",
            "service": "local_daemon",
            "serial": serial,
            "serial_detection": serial_meta,
            "daemon_http": http_probe,
            "local_daemon": _local_daemon_status_payload(http_probe=http_probe),
            "virtual": {
                "active": _virtual_active(),
                "motor_mode": _virtual.get("motor_mode", "disabled"),
                "playback_count": len(_playback_tasks),
            },
            "recording": {
                "active": bool(_record_session.get("active")),
                "name": _record_session.get("name") or "",
                "sample_count": len(_record_session.get("frames") or []),
            },
            "resolution": resolved,
            "log_tail": log_tail,
            "hints": _reachy_ping_hints(
                serial=serial,
                http_probe=http_probe,
                log_tail=log_tail,
                serial_meta=serial_meta,
            ),
        }
    )


@ws_router.websocket("/ws/reachy/state")
async def websocket_reachy_state(websocket: WebSocket) -> None:
    """Bridge daemon or virtual state into BotverseX's browser origin."""
    await websocket.accept()

    raw_freq = websocket.query_params.get("frequency", "10")
    try:
        frequency = max(float(raw_freq), 1.0)
    except ValueError:
        frequency = 10.0
    interval = 1.0 / frequency

    if _virtual_active():
        try:
            while True:
                await websocket.send_json(_state_envelope(_virtual_state_dict()))
                await asyncio.sleep(interval)
        except WebSocketDisconnect:
            return
        return

    http_probe = await _probe_daemon_http(timeout_s=1.0)
    if not http_probe.get("ok"):
        try:
            while True:
                await websocket.send_json({
                    "type": "reachy_error",
                    "code": "reachy_daemon_unavailable",
                    "message": "Reachy Mini daemon is not reachable.",
                    "hint": "Start local daemon or enable virtual mode via POST /api/reachy/virtual/start.",
                    "virtual_available": True,
                    "timestamp": time.time(),
                })
                await asyncio.sleep(interval)
        except WebSocketDisconnect:
            return
        return

    query = {
        "frequency": str(int(frequency)) if frequency.is_integer() else str(frequency),
        "with_head_joints": "true",
        "with_body_yaw": "true",
        "with_antenna_positions": "true",
        "with_control_mode": "true",
        # Ask the daemon for the 21 Stewart passive-joint values solved by
        # Placo (closed-loop IK). Without these, URDF's tree-only constraint
        # leaves the 6 rods dangling at default rotation and the head floating
        # detached. With them, all 27 joints (6 stewart + 21 passive) close
        # the loop visually and the head tracks 1:1.
        "with_passive_joints": "true",
    }
    daemon_ws = f"{_ws_base_url()}/api/state/ws/full?{urlencode(query)}"

    try:
        async with websockets.connect(
            daemon_ws,
            ping_interval=20,
            ping_timeout=20,
            proxy=None,
        ) as upstream:
            while True:
                raw = await upstream.recv()
                try:
                    state = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    await websocket.send_json({
                        "type": "reachy_raw",
                        "timestamp": time.time(),
                        "raw": raw,
                    })
                    continue
                await websocket.send_json(_state_envelope(state))
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({
                "type": "reachy_error",
                "code": "reachy_state_stream_failed",
                "message": f"Cannot stream Reachy Mini state from {daemon_ws}",
                "hint": "Check that the Reachy Mini daemon is running, or use virtual mode.",
                "error": f"{type(exc).__name__}: {exc!s}",
                "exception_type": type(exc).__name__,
                "exception_repr": repr(exc),
                "timestamp": time.time(),
            })
        except Exception:
            pass


# ============== M21: Apps / Volume / DoA / Daemon lifecycle proxies ==============
#
# These endpoints forward to the Allan daemon (:8010) REST API and unlock the
# official Reachy Mini open-source ecosystem:
#   * `/api/apps/*`       — install/start/stop HuggingFace apps (e.g. Conversation App)
#   * `/api/volume/*`     — speaker + microphone volume control + test sound
#   * `/api/state/doa`    — microphone array Direction of Arrival (look-at-speaker)
#   * `/api/daemon/*`     — full daemon lifecycle (start/stop/restart/status)
#
# Source of truth: /home/amd/sdk/reachy_mini_Allan/src/reachy_mini/daemon/app/routers/
# Pattern: reuse existing `_forward_json` helper (handles 502 daemon unreachable).


# ---- Apps lifecycle (routers/apps.py) -----------------------------------------

@router.get("/apps/list-available")
async def reachy_apps_list_available(request: Request) -> Response:
    """List all available Reachy Mini apps (HF Spaces + installed + local)."""
    return await _forward_json(request, "GET", "/api/apps/list-available")


@router.get("/apps/list-available/{source_kind}")
async def reachy_apps_list_by_source(
    request: Request, source_kind: str
) -> Response:
    """List apps by source: hf_space | installed | local."""
    return await _forward_json(
        request, "GET", f"/api/apps/list-available/{source_kind}"
    )


@router.post("/apps/install")
async def reachy_apps_install(request: Request) -> Response:
    """Install a new app from a HuggingFace Space URL (background job).

    Body: AppInfo JSON (name, description, url, source_kind, extra).
    Returns: {job_id}
    """
    body = await request.json()
    return await _forward_json(request, "POST", "/api/apps/install", json_body=body)


@router.post("/apps/install-private-space")
async def reachy_apps_install_private_space(request: Request) -> Response:
    """Install a private HuggingFace space (requires HF token via daemon /api/hf-auth)."""
    body = await request.json()
    return await _forward_json(
        request, "POST", "/api/apps/install-private-space", json_body=body
    )


@router.post("/apps/remove/{app_name}")
async def reachy_apps_remove(request: Request, app_name: str) -> Response:
    """Remove an installed app (background job)."""
    return await _forward_json(request, "POST", f"/api/apps/remove/{app_name}")


@router.post("/apps/start-app/{app_name}")
async def reachy_apps_start(request: Request, app_name: str) -> Response:
    """Start an app by name. Returns AppStatus."""
    return await _forward_json(request, "POST", f"/api/apps/start-app/{app_name}")


@router.post("/apps/restart-current-app")
async def reachy_apps_restart_current(request: Request) -> Response:
    """Restart the currently running app."""
    return await _forward_json(request, "POST", "/api/apps/restart-current-app")


@router.post("/apps/stop-current-app")
async def reachy_apps_stop_current(request: Request) -> Response:
    """Stop the currently running app."""
    return await _forward_json(request, "POST", "/api/apps/stop-current-app")


@router.get("/apps/current-app-status")
async def reachy_apps_current_status(request: Request) -> Response:
    """Get the status of the currently running app (or None)."""
    return await _forward_json(request, "GET", "/api/apps/current-app-status")


@router.get("/apps/job-status/{job_id}")
async def reachy_apps_job_status(request: Request, job_id: str) -> Response:
    """Get status + logs for an install/remove/update job."""
    return await _forward_json(request, "GET", f"/api/apps/job-status/{job_id}")


@router.get("/apps/check-updates")
async def reachy_apps_check_updates(request: Request) -> Response:
    """Check installed apps for available HF updates (5min cache on daemon side)."""
    return await _forward_json(request, "GET", "/api/apps/check-updates")


@router.post("/apps/update/{app_name}")
async def reachy_apps_update(request: Request, app_name: str) -> Response:
    """Reinstall an app from HuggingFace to pull the latest version (background job)."""
    return await _forward_json(request, "POST", f"/api/apps/update/{app_name}")


@ws_router.websocket("/ws/reachy/apps-manager/{job_id}")
async def ws_reachy_apps_manager(websocket: WebSocket, job_id: str) -> None:
    """Bridge daemon `/api/apps/ws/apps-manager/{job_id}` to the browser.

    Streams live install/remove/update job status + logs as JSON envelopes.
    """
    await websocket.accept()
    daemon_ws = f"{_ws_base_url()}/api/apps/ws/apps-manager/{job_id}"
    try:
        async with websockets.connect(
            daemon_ws, ping_interval=20, ping_timeout=20, proxy=None
        ) as upstream:
            while True:
                raw = await upstream.recv()
                try:
                    payload = json.loads(raw) if isinstance(raw, str) else raw
                    await websocket.send_json({
                        "type": "reachy_apps_job",
                        "job_id": job_id,
                        "timestamp": time.time(),
                        "payload": payload,
                    })
                except (TypeError, json.JSONDecodeError):
                    await websocket.send_json({
                        "type": "reachy_apps_job_raw",
                        "job_id": job_id,
                        "timestamp": time.time(),
                        "raw": raw,
                    })
    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await websocket.send_json({
                "type": "reachy_apps_error",
                "code": "reachy_apps_ws_failed",
                "message": f"Cannot stream Reachy apps job {job_id} from daemon",
                "hint": "Check that the Reachy Mini daemon is running.",
                "error": f"{type(exc).__name__}: {exc!s}",
                "job_id": job_id,
                "timestamp": time.time(),
            })
        except Exception:
            pass


# ---- Volume control (routers/volume.py) --------------------------------------

@router.get("/volume/current")
async def reachy_volume_current(request: Request) -> Response:
    """Get current speaker output volume (0-100)."""
    return await _forward_json(request, "GET", "/api/volume/current")


@router.post("/volume/set")
async def reachy_volume_set(request: Request) -> Response:
    """Set speaker volume (body: {volume: 0-100}); plays a test sound."""
    body = await request.json()
    return await _forward_json(request, "POST", "/api/volume/set", json_body=body)


@router.post("/volume/test-sound")
async def reachy_volume_test_sound(request: Request) -> Response:
    """Play a test sound on the speaker."""
    return await _forward_json(request, "POST", "/api/volume/test-sound")


@router.get("/volume/microphone/current")
async def reachy_mic_volume_current(request: Request) -> Response:
    """Get current microphone input volume (0-100)."""
    return await _forward_json(request, "GET", "/api/volume/microphone/current")


@router.post("/volume/microphone/set")
async def reachy_mic_volume_set(request: Request) -> Response:
    """Set microphone input volume (body: {volume: 0-100})."""
    body = await request.json()
    return await _forward_json(
        request, "POST", "/api/volume/microphone/set", json_body=body
    )


# ---- State: Direction of Arrival (routers/state.py /doa) ----------------------

@router.get("/state/doa")
async def reachy_state_doa(request: Request) -> Response:
    """Get microphone array Direction of Arrival.

    Returns {angle, speech_detected} or null if audio device unavailable.
    angle in radians: 0=left, pi/2=front, pi=right.

    DOA is best-effort: daemon may 500 when ReSpeaker USB perms fail.
    Never bubble that up as 5xx — UI polls this every few seconds.
    """
    try:
        resp = await _forward_json(request, "GET", "/api/state/doa")
        if resp.status_code >= 400:
            return JSONResponse(content=None)
        return resp
    except HTTPException:
        return JSONResponse(content=None)
    except Exception:
        return JSONResponse(content=None)


# ---- Daemon lifecycle (routers/daemon.py) ------------------------------------

@router.post("/daemon/start")
async def reachy_daemon_start(request: Request) -> Response:
    """Start the daemon (query: wake_up=bool). Returns {job_id}."""
    return await _forward_json(request, "POST", "/api/daemon/start")


@router.post("/daemon/stop")
async def reachy_daemon_stop(request: Request) -> Response:
    """Stop the daemon (query: goto_sleep=bool). Returns {job_id}."""
    return await _forward_json(request, "POST", "/api/daemon/stop")


@router.post("/daemon/restart")
async def reachy_daemon_restart(request: Request) -> Response:
    """Restart the daemon. Returns {job_id}."""
    return await _forward_json(request, "POST", "/api/daemon/restart")


@router.get("/daemon/status")
async def reachy_daemon_status(request: Request) -> Response:
    """Get current daemon status (state, version, IP, backend, etc.)."""
    return await _forward_json(request, "GET", "/api/daemon/status")


# ============== M24: Official HF recorded-move datasets ==============
#
# Pollen Robotics publishes two HF datasets of pre-recorded Reachy Mini
# moves that the daemon can stream directly to the motors:
#   * pollen-robotics/reachy-mini-emotions-library — happy / sad / angry / ...
#   * pollen-robotics/reachy-mini-dances-library    — wave / dab / ...
#
# Allan fork daemon already exposes:
#   GET  /api/move/recorded-move-datasets/list/{dataset_name}
#   POST /api/move/play/recorded-move-dataset/{dataset_name}/{move_name}
# We forward both verbatim + expose a "list known datasets" helper for UI.

# Canonical Pollen Robotics HF recorded-move datasets. Surfaced by the
# /api/reachy/move/recorded-move-datasets helper so the UI doesn't need
# to hardcode them.
_KNOWN_RECORDED_MOVE_DATASETS: list[dict[str, str]] = [
    {
        "dataset": "pollen-robotics/reachy-mini-emotions-library",
        "kind": "emotions",
        "display_name": "表情库 (Emotions)",
        "description": "官方 Reachy Mini 表情动作集合 (happy / sad / angry / ...)",
    },
    {
        "dataset": "pollen-robotics/reachy-mini-dances-library",
        "kind": "dances",
        "display_name": "舞蹈库 (Dances)",
        "description": "官方 Reachy Mini 舞蹈动作集合 (wave / dab / ...)",
    },
]


@router.get("/move/recorded-move-datasets")
async def reachy_list_known_recorded_datasets() -> JSONResponse:
    """Return the canonical list of Pollen Robotics HF recorded-move datasets.

    Pure-metadata endpoint — does not hit the daemon. The UI uses this to
    render the "HF 官方动作" tab without hardcoding dataset ids.
    """
    return JSONResponse(
        content={"ok": True, "datasets": _KNOWN_RECORDED_MOVE_DATASETS}
    )


@router.get("/move/recorded-move-datasets/list/{dataset_name:path}")
async def reachy_list_recorded_moves(
    request: Request, dataset_name: str
) -> Response:
    """List available moves inside a HF recorded-move dataset."""
    return await _forward_json(
        request, "GET", f"/api/move/recorded-move-datasets/list/{dataset_name}"
    )


@router.post("/move/recorded-move-datasets/play/{dataset_name:path}/{move_name}")
async def reachy_play_recorded_move(
    request: Request, dataset_name: str, move_name: str
) -> Response:
    """Play a recorded move from a HF dataset."""
    return await _forward_json(
        request,
        "POST",
        f"/api/move/play/recorded-move-dataset/{dataset_name}/{move_name}",
    )


