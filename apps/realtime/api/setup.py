"""Setup / preflight endpoints (M9.1).

Exposes hardware-preflight helpers used by the new SO-101 onboarding wizard
(``/robots/so101``):

  GET  /api/setup/ports
       List serial ports and probe each for a Feetech motor controller via a
       raw PING packet. Does NOT depend on the lerobot library, so it works
       on a minimal realtime venv too.

  POST /api/setup/wiggle
       Briefly wiggle a single joint (default: gripper joint 6, ±5 deg × 2)
       so the user can physically identify which arm is connected to which
       USB port. Requires lerobot (FollowerArmWriter). Returns 501 if the
       lerobot motor SDK is not importable — the wizard treats that as a
       non-fatal "skip" and lets the user continue without wiggle.

  GET  /api/setup/health
       Lightweight realtime-side status probe (serial perms, video device
       count, lerobot availability). Aggregated by the API service into the
       full /api/v1/setup/status response.

All endpoints are single-shot, non-blocking and safe to hit at any time.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import platform
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])


# ---------------------------------------------------------------------------
# Port scanning (no lerobot dependency)
# ---------------------------------------------------------------------------


def _list_serial_devices() -> List[str]:
    """Return sorted list of candidate serial device paths."""
    system = platform.system()
    if system == "Linux":
        paths = sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")))
    elif system == "Darwin":
        paths = sorted(glob.glob("/dev/cu.usbmodem*"))
    elif system == "Windows":
        try:
            import serial.tools.list_ports  # type: ignore

            paths = sorted(p.device for p in serial.tools.list_ports.comports())
        except Exception:
            paths = []
    else:
        paths = []
    return paths


def _feetech_checksum(packet: bytes) -> int:
    # Feetech/Dynamixel checksum: ~(sum of id,length,params)
    s = 0
    for b in packet[2:]:
        s = (s + b) & 0xFF
    return (~s) & 0xFF


def _build_ping(motor_id: int) -> bytes:
    # 0xFF 0xFF <ID> <LEN=0x02> <INSTR=0x01 PING> <CHECKSUM>
    body = bytes([motor_id, 0x02, 0x01])
    checksum = _feetech_checksum(b"\xff\xff" + body)
    return b"\xff\xff" + body + bytes([checksum])


def _probe_feetech_on_port(
    port: str, motor_ids: List[int], timeout_s: float = 0.15
) -> Dict[str, Any]:
    """Raw-protocol probe: returns dict with motor_ids that responded.

    No lerobot dependency. Uses pyserial only. Each PING is tiny (6 bytes out,
    6 bytes in) so 6 motors * ~30ms = ~200ms per port worst case.
    """
    try:
        import serial  # type: ignore
    except ImportError:
        return {"port": port, "motor_ids": [], "error": "pyserial not installed"}

    result: Dict[str, Any] = {"port": port, "motor_ids": [], "error": None}
    try:
        # 1_000_000 baud is the Feetech SO-101 default. If the user flashed a
        # different baud, PING will fail silently and the port is reported as
        # "no Feetech" — same behaviour as lerobot-find-port, good enough.
        ser = serial.Serial(port, baudrate=1_000_000, timeout=timeout_s, write_timeout=timeout_s)
    except Exception as exc:
        result["error"] = f"open_failed: {exc}"
        return result

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        found: List[int] = []
        for mid in motor_ids:
            try:
                ser.write(_build_ping(mid))
                ser.flush()
                # Expect 6 bytes status: FF FF ID LEN ERR CHK
                resp = ser.read(6)
                if len(resp) == 6 and resp[0] == 0xFF and resp[1] == 0xFF and resp[2] == mid:
                    found.append(mid)
            except Exception:
                pass
        result["motor_ids"] = found
    finally:
        try:
            ser.close()
        except Exception:
            pass
    return result


class PortInfo(BaseModel):
    port: str
    description: str = "Serial device"
    motor_count: int = 0
    motor_ids: List[int] = Field(default_factory=list)
    looks_like_feetech: bool = False
    # M21: Reachy Mini detection (Dynamixel body_rotation motor id=10)
    looks_like_reachy: bool = False
    # M21: convenience label for Setup UI ("reachy_mini" | "so101" | "unknown")
    robot_guess: str = "unknown"
    error: Optional[str] = None


class PortsResponse(BaseModel):
    ports: List[PortInfo]
    scanned_count: int
    platform: str


@router.get("/ports", response_model=PortsResponse)
async def list_ports() -> PortsResponse:
    """Enumerate serial ports and probe each for a Feetech controller or Reachy Mini."""
    devices = _list_serial_devices()
    motor_ids = [1, 2, 3, 4, 5, 6]
    ports: List[PortInfo] = []

    # Run blocking probes in a thread; we scan sequentially (one at a time)
    # because parallel serial writes to the same USB hub hurt more than help.
    loop = asyncio.get_event_loop()
    # M21: lazy import to avoid pulling reachy SDK path when nothing is plugged in.
    try:
        from .reachy_proxy import _ping_reachy_motor_on_port, _reachy_sdk_path
        reachy_sdk_available = _reachy_sdk_path().exists()
    except Exception:
        reachy_sdk_available = False
        _ping_reachy_motor_on_port = None  # type: ignore[assignment]

    for dev in devices:
        probe = await loop.run_in_executor(None, _probe_feetech_on_port, dev, motor_ids)
        found = probe.get("motor_ids") or []
        looks_feetech = bool(found)
        looks_reachy = False
        # Only spend ~2.5s on the Reachy Dynamixel probe when the Feetech probe
        # came back empty AND the Allan SDK is installed (otherwise every
        # unresponsive ttyACM would block the scan).
        if not looks_feetech and reachy_sdk_available and _ping_reachy_motor_on_port is not None:
            try:
                looks_reachy = await loop.run_in_executor(
                    None, _ping_reachy_motor_on_port, dev
                )
            except Exception:
                looks_reachy = False
        if looks_feetech:
            robot_guess = "so101"
            description = "Feetech Motor Controller (SO-101 / STS3215)"
        elif looks_reachy:
            robot_guess = "reachy_mini"
            description = "Reachy Mini (Dynamixel body_rotation id=10)"
        elif probe.get("error"):
            robot_guess = "unknown"
            description = "Serial Device (error)"
        else:
            robot_guess = "unknown"
            description = "USB Serial Device"
        ports.append(
            PortInfo(
                port=dev,
                description=description,
                motor_count=len(found),
                motor_ids=found,
                looks_like_feetech=looks_feetech,
                looks_like_reachy=looks_reachy,
                robot_guess=robot_guess,
                error=probe.get("error"),
            )
        )

    return PortsResponse(
        ports=ports,
        scanned_count=len(devices),
        platform=platform.system(),
    )


# ---------------------------------------------------------------------------
# Wiggle (needs lerobot FollowerArmWriter)
# ---------------------------------------------------------------------------


class WiggleRequest(BaseModel):
    port: str
    # offset_ticks: raw encoder steps (Feetech sts3215 = 4096 ticks / 360°).
    # 200 ticks ≈ 17.6°, same default as MakerMods LeRobot-UI — small enough
    # to be safe indoors, big enough to be obviously visible.
    offset_ticks: int = 200
    cycles: int = 3


class WiggleResponse(BaseModel):
    ok: bool
    message: str
    port: str
    available: bool  # whether lerobot motor SDK was available
    # Best-effort voltage readback so the UI can hint "this port is ~11.9V,
    # likely the powered Follower". Informational only — we DO NOT gate wiggle
    # on voltage (MakerMods upstream doesn't either), because a Leader running
    # on USB 5V→7.6V is perfectly capable of moving its gripper.
    present_voltage_v: Optional[float] = None


def _do_wiggle_blocking(req: WiggleRequest) -> Dict[str, Any]:
    """MakerMods-style minimal wiggle.

    Open a lerobot FeetechMotorsBus with ONLY the gripper motor, read the
    current raw tick, and drive ±offset_ticks around it for a few cycles.
    We intentionally skip FollowerArmWriter here: that class is designed for
    real teleop/training (with torque management, voltage preflight, temp
    checks), all of which are overkill — and actively wrong — for "just let
    me identify which arm is which" flow. The Leader arm lives on USB power
    (~7.6V) and our old preflight would refuse to enable torque, leaving the
    user staring at a broken button.
    """
    # Lazy-import so unit tests that don't exercise hardware never touch the
    # motor stack. Also lets us emit a targeted "sdk missing" message.
    try:
        from lerobot.motors import Motor, MotorNormMode  # type: ignore
        from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore
    except ImportError as exc:
        return {
            "ok": False,
            "available": False,
            "message": (
                f"lerobot motor stack not importable: {exc}. "
                "Install with `pip install 'feetech-servo-sdk>=1,<2'` "
                "inside the realtime venv and restart the realtime service."
            ),
        }

    bus = FeetechMotorsBus(
        port=req.port,
        motors={"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)},
    )
    try:
        try:
            bus.connect()
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            low = text.lower()
            if "scservo_sdk" in low or "no module named" in low:
                msg = (
                    "`feetech-servo-sdk` is not installed in the realtime "
                    "venv. Run `pip install 'feetech-servo-sdk>=1,<2'` then "
                    "restart realtime."
                )
            elif "permission denied" in low or "[errno 13]" in low:
                msg = (
                    f"cannot open {req.port}: permission denied. Add your "
                    "user to `dialout` group: `sudo usermod -aG dialout $USER` "
                    "then log out/in."
                )
            elif "no such file" in low or "[errno 2]" in low:
                msg = f"{req.port} disappeared — replug the USB cable and rescan."
            elif "busy" in low or "[errno 16]" in low:
                msg = f"{req.port} is already in use (stop any teleop/record first)."
            elif "missing motor" in low or "motor check" in low or "no status packet" in low:
                msg = (
                    f"no motor responded on {req.port}. Is the arm powered on "
                    "and the USB controller connected?"
                )
            else:
                msg = f"connect failed on {req.port}: {text}"
            return {"ok": False, "available": True, "message": msg}

        # Informational voltage read (sts3215 reports voltage in 0.1V units).
        voltage: Optional[float] = None
        try:
            v_raw = bus.sync_read("Present_Voltage", "gripper", normalize=False)
            voltage = float(v_raw["gripper"]) * 0.1
        except Exception:
            voltage = None  # non-fatal

        try:
            positions = bus.sync_read("Present_Position", "gripper", normalize=False)
            current = int(positions["gripper"])
        except Exception as exc:
            return {
                "ok": False,
                "available": True,
                "message": f"read gripper position failed: {exc}",
                "present_voltage_v": voltage,
            }

        offset = max(50, min(int(req.offset_ticks), 400))
        cycles = max(1, min(int(req.cycles), 5))

        if current - offset < 0 or current + offset > 4095:
            return {
                "ok": False,
                "available": True,
                "message": (
                    f"gripper position {current} is too close to the mechanical "
                    "end-stop; gently rotate the gripper away from the extreme "
                    "and try again."
                ),
                "present_voltage_v": voltage,
            }

        for _ in range(cycles):
            bus.write("Goal_Position", "gripper", current + offset, normalize=False)
            time.sleep(0.3)
            bus.write("Goal_Position", "gripper", current - offset, normalize=False)
            time.sleep(0.3)
        bus.write("Goal_Position", "gripper", current, normalize=False)
        time.sleep(0.2)

        return {
            "ok": True,
            "available": True,
            "message": "wiggle complete",
            "present_voltage_v": voltage,
        }
    except Exception as exc:  # pragma: no cover - hardware
        return {
            "ok": False,
            "available": True,
            "message": f"wiggle error: {type(exc).__name__}: {exc}",
        }
    finally:
        # Never let cleanup mask the real error (mirrors MakerMods' handling).
        try:
            if getattr(bus, "is_connected", False):
                bus.disconnect()
        except Exception:
            logger.warning("wiggle: disconnect() failed", exc_info=True)


@router.post("/wiggle", response_model=WiggleResponse)
async def wiggle(req: WiggleRequest) -> WiggleResponse:
    """Wiggle the gripper on the given port so the user can visually ID the arm.

    Intentionally does NOT enforce voltage/temperature preflight — the Leader
    arm runs on USB power (~7.6V) and would otherwise be rejected, leaving
    users confused. Matches MakerMods LeRobot-UI behaviour.
    """
    if req.offset_ticks < 50 or req.offset_ticks > 400:
        raise HTTPException(400, "offset_ticks must be between 50 and 400")
    if req.cycles < 1 or req.cycles > 5:
        raise HTTPException(400, "cycles must be between 1 and 5")

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _do_wiggle_blocking, req),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        return WiggleResponse(
            ok=False,
            available=True,
            message=(
                "wiggle timed out after 15s. The arm may not be responding — "
                "check power, USB cable, or that another process isn't holding "
                "the port."
            ),
            port=req.port,
        )

    return WiggleResponse(
        ok=bool(result.get("ok")),
        available=bool(result.get("available")),
        message=str(result.get("message", "")),
        port=req.port,
        present_voltage_v=result.get("present_voltage_v"),
    )


# ---------------------------------------------------------------------------
# Realtime-side health summary
# ---------------------------------------------------------------------------


class RealtimeHealth(BaseModel):
    realtime_ok: bool = True
    platform: str
    python_version: str
    lerobot_available: bool
    pytorch_available: bool
    opencv_available: bool
    video_device_count: int  # /dev/video* nodes present
    # M12: split the V4L2 probe into "can OpenCV actually use this device"
    # vs "it exists but is held by someone else". Lets /api/v1/setup/status
    # render camera_busy and camera_unavailable as distinct issues.
    camera_usable_count: int = 0
    camera_busy_count: int = 0
    serial_device_count: int
    dialout_member: Optional[bool]  # None on non-Linux
    rocm_probe_ok: Optional[bool]  # None = not probed (no torch)
    rocm_probe_message: Optional[str] = None


def _probe_rocm() -> Dict[str, Any]:
    """Probe CUDA/ROCm in an isolated child process.

    On some gfx1151 stacks, touching torch.cuda in-process can hard-crash the
    interpreter (SIGSEGV) instead of raising a Python exception. Running the
    probe out-of-process keeps /api/setup/health safe: a crash only kills the
    child and realtime stays alive.
    """
    import json
    import subprocess

    code = """
import json
out = {"ok": None, "message": "unknown"}
try:
    import torch
except Exception as e:
    out = {"ok": None, "message": f"torch not importable: {e}"}
else:
    try:
        if not torch.cuda.is_available():
            out = {"ok": False, "message": "torch.cuda.is_available() is False"}
        else:
            x = torch.randn(4, 4, device="cuda")
            _ = float((x @ x).sum().item())
            out = {"ok": True, "message": "CUDA kernel launched successfully"}
    except Exception as e:
        out = {"ok": False, "message": f"{type(e).__name__}: {e}"}
print(json.dumps(out, ensure_ascii=True))
"""

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=6,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "rocm probe timed out (>6s)"}
    except Exception as exc:
        return {"ok": False, "message": f"rocm probe launch failed: {type(exc).__name__}: {exc}"}

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = stderr[-1] if stderr else ""
        return {
            "ok": False,
            "message": f"rocm probe child exited rc={proc.returncode}" + (f" ({tail})" if tail else ""),
        }

    try:
        out = json.loads((proc.stdout or "").strip() or "{}")
        return {"ok": out.get("ok"), "message": str(out.get("message", ""))}
    except Exception as exc:
        return {"ok": False, "message": f"rocm probe parse failed: {type(exc).__name__}: {exc}"}



def _in_dialout_group() -> Optional[bool]:
    if platform.system() != "Linux":
        return None
    try:
        import grp

        gr = grp.getgrnam("dialout")
        try:
            import pwd

            me = pwd.getpwuid(os.getuid()).pw_name
        except Exception:
            me = os.environ.get("USER") or ""
        if me and me in gr.gr_mem:
            return True
        # Also check supplementary groups
        return os.getgid() == gr.gr_gid or gr.gr_gid in os.getgroups()
    except Exception:
        return None


_ROCM_CACHE: Dict[str, Any] = {"expires_at": 0.0, "value": None}
_ROCM_CACHE_TTL_S = 60.0


@router.get("/health", response_model=RealtimeHealth)
async def realtime_health() -> RealtimeHealth:
    # lerobot probe (cheap, just import)
    try:
        import lerobot.motors.feetech  # type: ignore  # noqa: F401

        lerobot_ok = True
    except Exception:
        lerobot_ok = False

    try:
        import torch  # type: ignore  # noqa: F401

        pt_ok = True
    except Exception:
        pt_ok = False

    try:
        import cv2  # type: ignore  # noqa: F401

        cv_ok = True
    except Exception:
        cv_ok = False

    video_count = len(glob.glob("/dev/video*"))
    # Do not run OpenCV V4L2 opens here — Setup polls /health every few seconds and
    # probing cameras blocks the whole realtime process for 10–30s. Use
    # GET /api/camera/status for detailed readiness instead.
    usable = 0
    busy = 0

    serial_count = len(await asyncio.to_thread(_list_serial_devices))
    now = time.monotonic()
    if _ROCM_CACHE["value"] is not None and now < float(_ROCM_CACHE["expires_at"]):
        rocm = _ROCM_CACHE["value"]
    else:
        try:
            rocm = await asyncio.wait_for(asyncio.to_thread(_probe_rocm), timeout=1.5)
        except asyncio.TimeoutError:
            rocm = {"ok": False, "message": "rocm probe skipped (health poll timeout)"}
        _ROCM_CACHE["value"] = rocm
        _ROCM_CACHE["expires_at"] = now + _ROCM_CACHE_TTL_S

    return RealtimeHealth(
        realtime_ok=True,
        platform=platform.platform(),
        python_version=sys.version.split()[0],
        lerobot_available=lerobot_ok,
        pytorch_available=pt_ok,
        opencv_available=cv_ok,
        video_device_count=video_count,
        camera_usable_count=usable,
        camera_busy_count=busy,
        serial_device_count=serial_count,
        dialout_member=_in_dialout_group(),
        rocm_probe_ok=rocm["ok"],
        rocm_probe_message=rocm["message"],
    )
