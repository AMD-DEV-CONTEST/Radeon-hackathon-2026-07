"""Teleop control — thin wrapper around the official `lerobot-teleoperate` CLI.

Design decision (2026-04):
    We do NOT write our own leader→follower loop anymore. MakerMods' working
    SO-101 UI just spawns

        lerobot-teleoperate
            --robot.type=so101_follower
            --robot.port=<follower serial>
            --robot.id=<follower calibration id>
            --teleop.type=so101_leader
            --teleop.port=<leader serial>
            --teleop.id=<leader calibration id>
            --display_data=false

    and lets the official CLI do everything — reading the leader, writing
    the follower, torque management, safety limits, graceful shutdown,
    accepting cached calibration. Every time we tried to replace that loop
    with our own `sender/` subprocess pair or an in-process FeetechMotorsBus,
    we either fought the high-level classes (SOFollower/SOLeader auto-
    calibrate, torque-management) or we reintroduced bugs the CLI doesn't
    have. So we stopped.

    What this module does:
        * Resolves a unique calibration id per arm (so the CLI finds
          ~/.cache/huggingface/lerobot/calibration/{robots|teleoperators}/
          so101_*/<id>.json and doesn't block on the "Press ENTER to use
          provided calibration" prompt).
        * Spawns ONE `lerobot-teleoperate` subprocess (in a new process
          group so we can SIGTERM the whole tree on stop).
        * Pipes a few newlines to stdin — this auto-accepts any residual
          interactive prompt the CLI might throw at us (same trick
          MakerMods uses, see process_manager.py in their repo).
        * Merges stderr into stdout with PYTHONUNBUFFERED=1 and keeps a
          rolling log tail so the wizard UI can show recent output.

    What this module does NOT do (and used to):
        * `sender/` subprocesses, /ws/teleop fan-in, /ws/ui fan-out — all
          gone. The CLI owns both serial ports directly, so we cannot tap
          live joint values without racing it. Step 3 URDF preview goes
          static while teleop runs — same trade-off MakerMods accepts.
        * PID tuning, EEPROM rewrites, seed-goal, soft-start ramp,
          configure_motors — all gone. The CLI handles them.

Public HTTP surface (unchanged, so the frontend needs no changes):
    POST /api/teleop/start    -> SessionStatus
    POST /api/teleop/stop     -> SessionStatus
    GET  /api/teleop/status   -> SessionStatus
    POST /api/teleop/release_torque -> ReleaseTorqueResponse
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .port_lock import port_lock_manager, PortInUseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teleop", tags=["teleop"])

REALTIME_ROOT = Path(__file__).resolve().parent.parent  # apps/realtime
CLI_LOG_TAIL_LINES = 60  # what we surface to the UI

# Regex to strip ANSI escape sequences (e.g. cursor-up codes from
# lerobot-teleoperate's live FPS banner) so the status panel shows readable
# text instead of `\x1b[2J\x1b[H...`. Same pattern MakerMods uses.
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


# ---------------------------------------------------------------------------
# Request / response schemas — kept identical to the previous sender-based
# implementation so the frontend doesn't need to change.
# ---------------------------------------------------------------------------


class StartRequest(BaseModel):
    leader_port: str = Field(..., description="serial device of the leader arm, e.g. /dev/ttyACM0")
    follower_port: str = Field(..., description="serial device of the follower arm, e.g. /dev/ttyACM1")
    # Kept for wire compat with the old sender-based start endpoint. The
    # official CLI manages follower torque itself (enables on first write,
    # disables on SIGTERM), so this flag is currently ignored.
    torque_on_start: bool = True
    # If true, skip the leader/follower alignment pre-check. The CLI will
    # still start, but the follower may jerk on first tick. Intended as an
    # escape hatch for the user who KNOWS their arms are aligned and wants
    # to bypass the guard (e.g. after a re-check that we couldn't see
    # because of a race with something else holding the port).
    force: bool = False


class AlignmentMismatch(BaseModel):
    motor: str
    delta_pct: float
    delta_deg: float
    hint: str


class AlignmentReport(BaseModel):
    ok: bool
    tolerance: float
    mismatches: List[AlignmentMismatch]
    skipped: bool = False


class AlignmentCheckRequest(BaseModel):
    leader_port: str
    follower_port: str


class ProcessStatus(BaseModel):
    role: str
    alive: bool
    pid: Optional[int]
    returncode: Optional[int]
    stderr_tail: List[str]


class SessionStatus(BaseModel):
    running: bool
    session_id: Optional[str] = None
    leader_port: Optional[str] = None
    follower_port: Optional[str] = None
    started_at: Optional[float] = None
    uptime_s: Optional[float] = None
    processes: List[ProcessStatus] = []


class ReleaseTorqueRequest(BaseModel):
    port: str = Field(..., description="serial device of the arm to release, e.g. /dev/ttyACM1")


class ReleaseTorqueResponse(BaseModel):
    ok: bool
    message: str
    motors_released: int = 0


# ---------------------------------------------------------------------------
# Calibration id resolution — identical semantics to the old module. Mirrors
# sender.lerobot_calibration.resolve_device_id.
# ---------------------------------------------------------------------------


def _expected_calibration_dir(device_type: str) -> Path:
    """Return the absolute path lerobot-teleoperate should scan for <id>.json.

    We resolve this from the CURRENT process env (the uvicorn/realtime
    process), then pass it explicitly via --{robot,teleop}.calibration_dir,
    so the subprocess env's HOME / HF_HOME cannot matter. Layout matches
    `lerobot/utils/constants.py`:

        $HF_LEROBOT_CALIBRATION   (full override, rare)
        OR  $HF_LEROBOT_HOME/calibration
        OR  $HF_HOME/lerobot/calibration
        OR  ~/.cache/huggingface/lerobot/calibration   (default)

    Within that root:
        robots/so101_follower/   — follower JSON lives here
        teleoperators/so101_leader/ — leader JSON lives here
    """
    explicit = os.environ.get("HF_LEROBOT_CALIBRATION")
    if explicit:
        root = Path(explicit).expanduser()
    else:
        hf_home = os.environ.get("HF_LEROBOT_HOME") or os.environ.get("HF_HOME")
        if hf_home:
            base = Path(hf_home).expanduser()
            root = base / "calibration" if base.name != "lerobot" else base / "calibration"
            # HF_HOME=~/.cache/huggingface → +/lerobot/calibration
            if os.environ.get("HF_LEROBOT_HOME") is None:
                root = Path(hf_home).expanduser() / "lerobot" / "calibration"
        else:
            root = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"

    if device_type == "leader":
        return root / "teleoperators" / "so101_leader"
    if device_type == "follower":
        return root / "robots" / "so101_follower"
    raise ValueError(f"device_type must be 'leader' or 'follower', got {device_type!r}")


# ---------------------------------------------------------------------------
# Arm alignment pre-flight
# ---------------------------------------------------------------------------
#
# Why this exists:
#     lerobot-teleoperate's first write cycle slams follower.Goal_Position to
#     whatever the leader's current Present_Position maps to. If the two arms
#     are far apart, the follower jerks hard to catch up — e.g. wrist_flex
#     travels 20-60 degrees in one 16ms tick, which looks and feels like the
#     joint "jumping on start". MakerMods' UI sidesteps this by asking the
#     operator to align the two arms by hand before pressing play. We enforce
#     the same pre-check here so the experience is consistent and the user
#     gets an actionable error instead of a startled robot.
#
# What "aligned" means:
#     Each joint's raw tick position, after being normalised to the -100..+100
#     range by its own calibration, must differ between leader and follower
#     by less than ALIGN_TOLERANCE_PCT. 5% of the calibrated range is roughly
#     5-8 degrees depending on joint span — generous enough that the operator
#     doesn't need a protractor, tight enough that the first-tick jerk is
#     below what the motor accelerates through in 16ms.
#
# Why read raw ticks and normalise ourselves instead of asking the bus to do
# it:
#     Reading `Present_Position` with `normalize=True` requires the bus to
#     hold a valid `calibration` dict, which is exactly what we want to
#     compare against. Doing it by hand also makes the error message a
#     domain-specific "degrees off" number the user can act on.

ALIGN_TOLERANCE_PCT = 5.0  # each joint must be within 5% of range

# Ticks-per-360° on sts3215 is 4096 (12-bit absolute encoder). We convert
# "ticks off" to "degrees off" via this factor so error messages are in
# units the user can eyeball on the arm.
_TICKS_PER_DEG = 4096 / 360.0


def _read_raw_pose(
    port: str,
    device_id: str,
    device_type: str,
    motor_names: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Open the arm read-only, read every motor's Present_Position, close.

    Returns an empty dict on any failure — callers should treat that as
    "can't verify alignment, proceed at your own risk" and log a warning.
    We intentionally do NOT raise: alignment is a best-effort safety net,
    not something that should block an otherwise-working teleop start
    (e.g. if the read races with something else holding the port).
    """
    try:
        from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore
        sender_path = str(REALTIME_ROOT)
        if sender_path not in sys.path:
            sys.path.insert(0, sender_path)
        from sender.lerobot_calibration import build_motors_dict  # type: ignore
    except ImportError as exc:
        logger.warning("alignment check: cannot import lerobot motors: %s", exc)
        return {}

    # Build a bus WITHOUT calibration (we only need raw ticks — passing
    # calibration would make sync_read normalise, which we don't want here).
    selected_names = list(motor_names) if motor_names else None
    bus = FeetechMotorsBus(port=port, motors=build_motors_dict(selected_names))
    try:
        try:
            bus.connect()
        except Exception as exc:
            msg = str(exc)
            # Leader arm can physically miss id=6 (gripper) while the
            # calibration file still lists it. Retry once without gripper so
            # alignment check can still proceed on shared joints.
            if (
                device_type == "leader"
                and selected_names
                and "gripper" in selected_names
                and "Missing motor IDs" in msg
                and "6" in msg
            ):
                retry_names = [n for n in selected_names if n != "gripper"]
                bus = FeetechMotorsBus(port=port, motors=build_motors_dict(retry_names))
                try:
                    bus.connect()
                except Exception:
                    logger.warning(
                        "alignment check: cannot open %s for %s (%s): %s",
                        port,
                        device_type,
                        device_id,
                        exc,
                    )
                    return {}
            else:
                logger.warning(
                    "alignment check: cannot open %s for %s (%s): %s",
                    port,
                    device_type,
                    device_id,
                    exc,
                )
                return {}
        try:
            raw = bus.sync_read("Present_Position", normalize=False)
            return {name: int(v) for name, v in raw.items()}
        except Exception as exc:
            logger.warning("alignment check: sync_read failed on %s: %s", port, exc)
            return {}
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


def _load_calibration_dict(device_type: str, device_id: str) -> Dict[str, Dict[str, int]]:
    """Read a calibration JSON and return {motor: {range_min, range_max, ...}}.

    Used to compute per-joint normalised positions for the alignment check.
    Returns {} if the file can't be read so the caller can fall back
    gracefully.
    """
    path = _expected_calibration_dir(device_type) / f"{device_id}.json"
    if not path.is_file():
        return {}
    try:
        import json
        with path.open("r") as fh:
            raw = json.load(fh)
        return {
            name: {
                "range_min": int(entry["range_min"]),
                "range_max": int(entry["range_max"]),
            }
            for name, entry in raw.items()
        }
    except Exception as exc:
        logger.warning("alignment check: cannot parse %s: %s", path, exc)
        return {}


def _alignment_report(
    leader_port: str,
    follower_port: str,
    leader_id: str,
    follower_id: str,
) -> Dict[str, object]:
    """Compute per-joint alignment between leader and follower.

    Returns a dict with:
        ok:           True iff every joint is within ALIGN_TOLERANCE_PCT
        tolerance:    the threshold used (for the frontend to echo back)
        mismatches:   list of {motor, delta_pct, delta_deg, hint}
                      one entry per offending joint; empty if ok
        skipped:      True if we couldn't read either arm (caller should
                      log a warning but proceed — see _read_raw_pose)

    The list is sorted biggest-delta-first so the UI can highlight the
    worst offender. `hint` tells the user which direction to nudge
    (simple "A is higher than B" phrasing; the wizard can translate).
    """
    leader_cal = _load_calibration_dict("leader", leader_id)
    follower_cal = _load_calibration_dict("follower", follower_id)
    if not leader_cal or not follower_cal:
        return {
            "ok": True,
            "tolerance": ALIGN_TOLERANCE_PCT,
            "mismatches": [],
            "skipped": True,
        }

    leader_pose = _read_raw_pose(leader_port, leader_id, "leader", list(leader_cal.keys()))
    follower_pose = _read_raw_pose(
        follower_port, follower_id, "follower", list(follower_cal.keys())
    )
    if not leader_pose or not follower_pose:
        return {
            "ok": True,  # fail-open — don't block teleop if the read failed
            "tolerance": ALIGN_TOLERANCE_PCT,
            "mismatches": [],
            "skipped": True,
        }

    mismatches: List[Dict[str, object]] = []
    # Iterate leader's motor order (the raw sync_read dicts use arbitrary
    # insertion order; it happens to match the Motor dict but don't rely
    # on that across SDK versions).
    for motor in leader_cal:
        if motor not in follower_cal or motor not in leader_pose or motor not in follower_pose:
            continue

        l_span = leader_cal[motor]["range_max"] - leader_cal[motor]["range_min"]
        f_span = follower_cal[motor]["range_max"] - follower_cal[motor]["range_min"]
        if l_span <= 0 or f_span <= 0:
            continue  # shouldn't happen after a good calibration

        # Normalise each arm to [0..1] within its own range. Using the
        # joint's own window means calibration differences between the
        # two physical motors don't falsely inflate the delta.
        l_pct = (leader_pose[motor] - leader_cal[motor]["range_min"]) / l_span
        f_pct = (follower_pose[motor] - follower_cal[motor]["range_min"]) / f_span
        delta_pct = (l_pct - f_pct) * 100.0

        if abs(delta_pct) <= ALIGN_TOLERANCE_PCT:
            continue

        # Translate the tick delta to degrees on the follower scale —
        # slightly more intuitive than "5% off". We use tick counts
        # (not normalized ratios) because degrees ultimately come from
        # encoder ticks.
        l_ticks_at_follower = (
            follower_cal[motor]["range_min"] + l_pct * f_span
        )
        delta_ticks = l_ticks_at_follower - follower_pose[motor]
        delta_deg = delta_ticks / _TICKS_PER_DEG

        direction = "further in +" if delta_deg > 0 else "further in -"
        mismatches.append({
            "motor": motor,
            "delta_pct": round(delta_pct, 1),
            "delta_deg": round(delta_deg, 1),
            # "leader is ahead of follower by X°" — user moves leader
            # toward follower, not the other way around.
            "hint": (
                f"move LEADER's {motor} about {abs(delta_deg):.0f}° "
                f"({direction.split()[-1]} direction) to meet the follower"
            ),
        })

    mismatches.sort(key=lambda e: abs(e["delta_pct"]), reverse=True)  # type: ignore[arg-type]
    return {
        "ok": not mismatches,
        "tolerance": ALIGN_TOLERANCE_PCT,
        "mismatches": mismatches,
        "skipped": False,
    }


def _seed_follower_goal_to_present(port: str, device_id: str) -> bool:
    """Set every follower motor's `Goal_Position` to its current `Present_Position`.

    Why this exists:
        When lerobot-teleoperate spawns and enables torque on the follower,
        the STS3215 kernel keeps pushing toward whatever `Goal_Position` is
        currently in EEPROM — which, after a prior SIGTERM, is the LAST
        goal the CLI wrote, typically ~100-200 ticks away from where the
        follower physically ended up (because torque was cut mid-motion).
        That ~200-tick gap, multiplied by the hardest joint's gear ratio
        and hit all at once at 60 Hz, draws a big enough peak current to
        trip one of our motors (ID=4 / wrist_flex — the weakest link on
        this specific arm) right off the RS-485 bus. We diagnosed this on
        2026-04-21 after every other joint came back healthy but ID=4
        kept disappearing from `_handshake()`'s ping list the instant
        torque engaged.

        Writing Goal = Present ONE TIME before torque turns on removes
        that startup spike entirely. No ramp, no soft-start — just "the
        goal is where you are right now, stay put". Once the CLI takes
        over on the next tick the leader's pose drives everything
        normally.

    This is safe to call while torque is OFF (which it is — we run this
    before spawning the CLI, and the CLI is what turns torque on).
    Writing Goal_Position with torque off is a pure EEPROM write; the
    motor doesn't move.

    Returns True on success. False on any failure (port busy, motor
    missing, etc.) — callers can log and continue; at worst we're back to
    the old "CLI jerks on start" behaviour we had before this fix.
    """
    try:
        from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore
        sender_path = str(REALTIME_ROOT)
        if sender_path not in sys.path:
            sys.path.insert(0, sender_path)
        from sender.lerobot_calibration import build_motors_dict  # type: ignore
    except ImportError as exc:
        logger.warning("seed-goal: cannot import lerobot motors: %s", exc)
        return False

    bus = FeetechMotorsBus(port=port, motors=build_motors_dict())
    try:
        try:
            bus.connect()
        except Exception as exc:
            logger.warning("seed-goal: cannot open %s: %s", port, exc)
            return False

        # Read current raw ticks, write them back as the new goal. We do
        # this per-motor rather than sync_write in a batch so one dead
        # motor (e.g. ID=4 dropping off again) doesn't abort the whole
        # seed — the other 5 motors get their seed regardless.
        present = bus.sync_read("Present_Position", normalize=False)
        seeded = 0
        for motor, val in present.items():
            try:
                bus.write("Goal_Position", motor, int(val), normalize=False)
                seeded += 1
            except Exception as exc:
                logger.warning("seed-goal: failed to seed %s: %s", motor, exc)
        logger.info(
            "seed-goal: set Goal = Present on %d/%d follower motors before CLI spawn",
            seeded, len(present),
        )
        return seeded == len(present)
    finally:
        try:
            bus.disconnect()
        except Exception:
            pass


def _resolve_device_id(device_type: str) -> Optional[str]:
    """Pick a calibration `id` to hand to lerobot-teleoperate.

    `device_type` is "leader" or "follower". We need a unique id BEFORE
    spawning so we can fail fast with a 412 Precondition Failed (wizard
    redirects user to Step 2 calibration) instead of letting the CLI block
    on an interactive prompt that nobody can answer.
    """
    sender_path = str(REALTIME_ROOT)
    if sender_path not in sys.path:
        sys.path.insert(0, sender_path)
    try:
        from sender.lerobot_calibration import resolve_device_id  # type: ignore
    except Exception as exc:  # pragma: no cover - dev convenience
        logger.warning("cannot import sender.lerobot_calibration: %s", exc)
        return None
    return resolve_device_id(device_type)


# ---------------------------------------------------------------------------
# Single CLI subprocess
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Dependency pre-check — run BEFORE any subprocess spawn or in-process loop
# construction so the user gets a structured error instead of a buried
# "FileNotFoundError" on a SIGKILL'd subprocess.
# ---------------------------------------------------------------------------


def _teleop_mode() -> str:
    """Resolve teleop execution mode.

    BOTVERSEX_TELEOP_MODE env var:
      - "inprocess" (default) → run leader→follower loop in this process,
        broadcast joint_update to /ws/ui so the URDF viewer stays live.
      - "cli"                 → spawn `lerobot-teleoperate` subprocess.
        Live URDF preview is NOT available in this mode (CLI owns both
        ports); kept as an escape hatch for parity with MakerMods.
    """
    mode = os.environ.get("BOTVERSEX_TELEOP_MODE", "inprocess").strip().lower()
    return "cli" if mode == "cli" else "inprocess"


def _check_teleop_dependencies(mode: str) -> List[str]:
    """Return a list of missing dependency names (empty = all good)."""
    missing: List[str] = []
    if mode == "cli":
        # Need the `lerobot-teleoperate` entry point on disk OR PATH.
        bin_path = _cli_binary()
        exists = (
            os.path.isfile(bin_path)
            or shutil.which("lerobot-teleoperate") is not None
        )
        if not exists:
            missing.append("lerobot")
    else:
        # In-process mode needs lerobot.motors.feetech importable.
        try:
            import lerobot.motors.feetech  # noqa: F401
        except Exception:
            missing.append("lerobot")
    return missing


def _cli_binary() -> str:
    """Path to `lerobot-teleoperate` inside the realtime venv.

    Hitting the venv binary explicitly (not PATH) is critical: uvicorn may
    be started from a different shell where lerobot isn't on PATH, and we
    MUST call the one in our own venv so feetech-servo-sdk etc. resolve.
    """
    bin_dir = os.path.dirname(sys.executable)
    candidate = os.path.join(bin_dir, "lerobot-teleoperate")
    if os.path.isfile(candidate):
        return candidate
    # Fallback lets developers run the service outside a venv.
    return "lerobot-teleoperate"


class _TeleopCLIProcess:
    """Owns one `lerobot-teleoperate` subprocess + a log tail reader thread.

    Lifecycle:
        __init__ → start() → (running) → stop() → (stopped)

    Thread model:
        * start() is called from the FastAPI executor (it's blocking — we
          spawn the subprocess and sleep a beat).
        * A daemon reader thread drains stdout line-by-line into the ring
          buffer so the wizard's 2-second status poll has fresh output.
        * stop() blocks until SIGTERM drains (up to `timeout`) or SIGKILL
          hits. Callers should also run stop() in an executor.
    """

    def __init__(
        self,
        leader_port: str,
        follower_port: str,
        leader_id: str,
        follower_id: str,
    ) -> None:
        self.leader_port = leader_port
        self.follower_port = follower_port
        self.leader_id = leader_id
        self.follower_id = follower_id

        self.session_id = f"teleop-{uuid.uuid4().hex[:8]}"
        self.started_at = time.time()

        self._proc: Optional[subprocess.Popen] = None
        self._log: Deque[str] = deque(maxlen=CLI_LOG_TAIL_LINES)
        self._reader: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    def _log_line(self, s: str) -> None:
        s = _ANSI_ESCAPE_RE.sub("", s).rstrip()
        if not s:
            return
        stamp = time.strftime("%H:%M:%S")
        self._log.append(f"{stamp} {s}")
        # Also forward to stdout so `tail -f /tmp/botversex_realtime.log`
        # shows live output — the default uvicorn log config occasionally
        # swallows `logger.info()` under --reload.
        print(f"[teleop-cli] {stamp} {s}", flush=True)

    def _build_cmd(self) -> List[str]:
        # Arguments chosen to mirror MakerMods' backend
        # (build_teleoperation_command) PLUS explicit --*.calibration_dir so
        # we don't depend on the subprocess's HOME / HF_HOME env to resolve
        # ~/.cache/huggingface/lerobot/calibration. Under systemd / setsid-
        # launched uvicorn those vars can silently be wrong, which makes
        # SOLeader.__init__ see `self.calibration = {}` and fall through to
        # record_ranges_of_motion (the "min == max" crash we chased on
        # 2026-04-21). Passing calibration_dir explicitly is cheap and
        # removes one whole class of failure mode.
        leader_dir = _expected_calibration_dir("leader")
        follower_dir = _expected_calibration_dir("follower")
        return [
            _cli_binary(),
            "--robot.type=so101_follower",
            f"--robot.port={self.follower_port}",
            f"--robot.id={self.follower_id}",
            f"--robot.calibration_dir={follower_dir}",
            "--teleop.type=so101_leader",
            f"--teleop.port={self.leader_port}",
            f"--teleop.id={self.leader_id}",
            f"--teleop.calibration_dir={leader_dir}",
            "--display_data=false",
        ]

    # ------------------------------------------------------------------
    def start(self, ready_timeout_s: float = 8.0) -> None:
        """Spawn the CLI. Raises RuntimeError if it dies before looking healthy.

        Readiness heuristic (same 2-stage gate MakerMods effectively uses):
            1. Wait up to `ready_timeout_s` for EITHER the process to exit
               (→ error) OR for us to see a known "running" marker in the
               log tail.
            2. If no marker appears but the process is still alive, accept
               it as ready — the CLI sometimes prints nothing until the
               first physical movement.
        """
        cmd = self._build_cmd()
        self._log_line("spawn: " + " ".join(shlex.quote(x) for x in cmd))

        # Inherit env, force unbuffered Python output, disable rerun sink
        # (we run `--display_data=false` already, but RERUN=off belt-and-
        # suspenders it so the CLI doesn't even try to start a rerun TCP
        # server at :9876 which would fight MakerMods if that's also open).
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["RERUN"] = "off"

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # merge so one reader drains both
                text=True,
                bufsize=1,
                # New process group so we can SIGTERM/SIGKILL the whole tree
                # on stop(). lerobot-teleoperate itself doesn't spawn
                # children today, but this is future-proofing and costs us
                # nothing.
                start_new_session=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{cmd[0]} not found ({exc}). Is the realtime venv set up? "
                "`pip install lerobot` inside apps/realtime/.venv/."
            ) from exc

        # Feed a few newlines so any residual interactive prompt (e.g.
        # `Press ENTER to use provided calibration file`) gets auto-
        # accepted and the CLI proceeds into the read/write loop. MakerMods
        # does the exact same thing in their process_manager.py — without
        # it the CLI silently blocks forever and /start appears to hang.
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.write("\n\n\n")
                self._proc.stdin.flush()
                self._proc.stdin.close()
        except Exception as exc:  # non-fatal
            self._log_line(f"[WARN] failed to feed stdin newlines: {exc}")

        # Start the reader thread.
        self._reader = threading.Thread(
            target=self._drain_output,
            daemon=True,
            name=f"teleop-cli-reader-{self.session_id}",
        )
        self._reader.start()

        # 2-stage readiness gate.
        t0 = time.time()
        ready_patterns = (
            re.compile(r"teleoperat", re.IGNORECASE),
            re.compile(r"\bconnected\b", re.IGNORECASE),
            re.compile(r"\bfps\b", re.IGNORECASE),
        )
        while time.time() - t0 < ready_timeout_s:
            rc = self._proc.poll()
            if rc is not None:
                tail = "\n    ".join(self._log) or "(no output)"
                raise RuntimeError(
                    f"lerobot-teleoperate exited with code {rc} before it "
                    f"was ready. Recent output:\n    {tail}"
                )
            recent = "\n".join(list(self._log)[-20:])
            if any(p.search(recent) for p in ready_patterns):
                self._log_line("CLI looks ready")
                return
            time.sleep(0.1)

        # No explicit marker but proc is alive → assume ready.
        if self._proc.poll() is None:
            self._log_line(
                f"no ready marker after {ready_timeout_s:.1f}s — assuming ready"
            )
            return
        rc = self._proc.poll()
        tail = "\n    ".join(self._log) or "(no output)"
        raise RuntimeError(
            f"lerobot-teleoperate exited with code {rc} during startup. "
            f"Recent output:\n    {tail}"
        )

    def _drain_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._log_line(line)
                low = line.lower()
                if any(
                    tok in low
                    for tok in ("traceback", "error:", "permission denied", "not found")
                ):
                    self._last_error = line
        except Exception as exc:
            self._log_line(f"[reader] drain failed: {exc}")

    # ------------------------------------------------------------------
    def stop(self, timeout_s: float = 6.0) -> None:
        """SIGTERM the process group, fall back to SIGKILL after `timeout_s`.

        lerobot-teleoperate installs its own SIGTERM handler that disables
        follower torque before exiting, so a clean SIGTERM is the correct
        call. SIGKILL leaves motors torqued — last resort only.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            self._log_line("already exited" if proc else "not started")
            return
        try:
            pgid = os.getpgid(proc.pid)
            self._log_line(f"SIGTERM pgid={pgid}")
            os.killpg(pgid, signal.SIGTERM)
        except Exception as exc:
            self._log_line(f"[WARN] SIGTERM failed: {exc}; falling back to proc.terminate()")
            try:
                proc.terminate()
            except Exception:
                pass

        t0 = time.time()
        while time.time() - t0 < timeout_s:
            if proc.poll() is not None:
                self._log_line(f"exited cleanly rc={proc.returncode}")
                return
            time.sleep(0.1)

        self._log_line(
            "[WARN] did not exit after SIGTERM — sending SIGKILL "
            "(motors may stay torqued; call /release_torque to recover)"
        )
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def is_alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)

    def to_process_status(self) -> ProcessStatus:
        proc = self._proc
        return ProcessStatus(
            role="lerobot-teleoperate",
            alive=self.is_alive(),
            pid=proc.pid if proc else None,
            returncode=proc.returncode if proc else None,
            stderr_tail=list(self._log),
        )


# ---------------------------------------------------------------------------
# In-process teleop loop — keeps Step 3 URDF preview live during teleop.
# ---------------------------------------------------------------------------
#
# Why this exists:
#   The CLI subprocess (_TeleopCLIProcess) owns both serial ports, so we
#   cannot tap leader joints from outside without serial collisions. That
#   makes the URDF viewer in Step 3 go static the moment teleop starts —
#   confusing to users who expect to see the virtual model mirror the real
#   arm.
#
#   This in-process variant runs the leader→follower loop in our own
#   process using the same `LeaderArmReader` + `FollowerArmWriter` pair
#   the legacy `sender/` subprocesses used. Because we own both buses,
#   we can also broadcast each frame to /ws/ui, so the URDF viewer stays
#   live exactly like it did before the CLI migration.
#
# Trade-off:
#   We re-introduce a small amount of code that lerobot-teleoperate
#   handles for free (torque lifecycle, calibration loading). The reader/
#   writer modules already encapsulate that. If we hit the same bugs the
#   2026-04 doc warned about (SOFollower/SOLeader auto-calibrate, torque
#   races), set BOTVERSEX_TELEOP_MODE=cli to fall back.


class _TeleopInProcessLoop:
    """Owns a leader→follower loop in the realtime process.

    Lifecycle:
        __init__ → start() → (running) → stop() → (stopped)

    Threading:
        * start() opens both serial buses and spawns one daemon worker
          thread that runs the read→write→broadcast cycle at ~60 Hz.
        * stop() sets a stop-event, joins the thread (with timeout),
          disables follower torque, closes both buses.
        * Broadcasts to /ws/ui go through `asyncio.run_coroutine_threadsafe`
          on the FastAPI event loop captured at start() time.
    """

    role = "lerobot-inprocess-teleop"
    LOOP_HZ = 60.0  # leader read + follower write rate
    BROADCAST_HZ = 30.0  # /ws/ui push rate (cheaper than LOOP_HZ)

    def __init__(
        self,
        leader_port: str,
        follower_port: str,
        leader_id: str,
        follower_id: str,
    ) -> None:
        self.leader_port = leader_port
        self.follower_port = follower_port
        self.leader_id = leader_id
        self.follower_id = follower_id

        self.session_id = f"teleop-{uuid.uuid4().hex[:8]}"
        self.started_at = time.time()

        self._reader: Any = None  # LeaderArmReader; lazy import in start()
        self._writer: Any = None  # FollowerArmWriter
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._log: Deque[str] = deque(maxlen=CLI_LOG_TAIL_LINES)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._returncode: Optional[int] = None
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    def _log_line(self, s: str) -> None:
        s = s.rstrip()
        if not s:
            return
        stamp = time.strftime("%H:%M:%S")
        self._log.append(f"{stamp} {s}")
        print(f"[teleop-inproc] {stamp} {s}", flush=True)

    # ------------------------------------------------------------------
    def start(
        self,
        ready_timeout_s: float = 8.0,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        """Open both buses, enable follower torque, spawn worker thread.

        `loop` MUST be the FastAPI event loop captured by the request
        handler before it offloads start() to a worker thread. Calling
        `asyncio.get_event_loop()` here would fail with "no current event
        loop in thread" on Python 3.10+ since `start()` runs on the
        ThreadPoolExecutor, not the loop thread.

        Raises RuntimeError on any setup failure so the caller can release
        port locks and surface a clear error to the UI.
        """
        if loop is None:
            # Fallback: try to grab a running loop if start() was called
            # synchronously on the loop thread (rare; mostly tests).
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError as exc:
                raise RuntimeError(
                    "in-process teleop start() needs the FastAPI event "
                    "loop; pass loop=asyncio.get_running_loop() from the "
                    "request handler before calling run_in_executor."
                ) from exc
        self._loop = loop

        # Lazy imports — keeps this module importable even when the
        # `sender/` package or `lerobot` aren't available yet.
        sender_path = str(REALTIME_ROOT)
        if sender_path not in sys.path:
            sys.path.insert(0, sender_path)
        from sender.reader import LeaderArmReader  # type: ignore
        from sender.writer import FollowerArmWriter  # type: ignore

        # Telemetry off — we don't need voltage/temp readouts in the
        # tight teleop loop, and they cost ~3-5 ms/frame.
        reader = LeaderArmReader(
            port=self.leader_port,
            device_id=self.leader_id,
            read_telemetry=False,
        )
        if not reader.connect():
            raise RuntimeError(
                f"leader connect failed: {reader._last_connect_error or 'unknown'}"
            )
        self._reader = reader

        writer = FollowerArmWriter(
            port=self.follower_port,
            device_id=self.follower_id,
            warmup_seconds=0.4,
        )
        if not writer.connect():
            try:
                reader.disconnect()
            finally:
                pass
            raise RuntimeError(
                f"follower connect failed: {writer._last_connect_error or 'unknown'}"
            )
        self._writer = writer

        if not writer.enable_torque():
            try:
                writer.disconnect()
            finally:
                pass
            try:
                reader.disconnect()
            finally:
                pass
            raise RuntimeError(
                f"follower torque enable failed: "
                f"{writer._last_torque_error or 'unknown'}"
            )

        self._thread = threading.Thread(
            target=self._run,
            name=f"teleop-inproc-{self.session_id}",
            daemon=True,
        )
        self._thread.start()
        self._log_line(
            f"in-process loop started (leader={self.leader_id}, "
            f"follower={self.follower_id})"
        )

    # ------------------------------------------------------------------
    def _run(self) -> None:
        """Worker thread: read leader → write follower → broadcast to UI."""
        # Lazy import to keep module-load cheap and avoid circulars.
        from sender.joint_angles import (  # type: ignore
            MOTOR_NAME_TO_ID,
            normalized_to_rad,
        )
        from .websocket import manager, JointData

        target_dt = 1.0 / self.LOOP_HZ
        broadcast_interval = 1.0 / self.BROADCAST_HZ
        last_broadcast = 0.0
        consecutive_errors = 0

        try:
            while not self._stop_event.is_set():
                t0 = time.time()
                try:
                    frame = self._reader.read()
                    if frame.errors:
                        # Reader collected per-cycle errors but didn't
                        # raise — log first one and keep going.
                        self._log_line(f"read warn: {frame.errors[0]}")
                    if frame.positions_normalized:
                        self._writer.write_positions(frame.positions_normalized)
                        consecutive_errors = 0

                        if t0 - last_broadcast >= broadcast_interval:
                            last_broadcast = t0
                            joints_rad: Dict[str, float] = {}
                            for name, val in frame.positions_normalized.items():
                                mid = MOTOR_NAME_TO_ID.get(name)
                                if mid is None:
                                    continue
                                try:
                                    joints_rad[str(mid)] = float(
                                        normalized_to_rad(name, val)
                                    )
                                except Exception:
                                    continue
                            self._dispatch_broadcast(
                                joints_rad, t0, manager, JointData
                            )
                except Exception as exc:
                    consecutive_errors += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    self._log_line(f"loop error: {exc}")
                    if consecutive_errors >= 30:
                        # ~0.5 s of solid failures → bail out so /status
                        # reflects "dead" instead of looping forever.
                        self._log_line(
                            "too many consecutive read/write errors; stopping loop"
                        )
                        self._returncode = 1
                        break

                elapsed = time.time() - t0
                if elapsed < target_dt:
                    # Use stop_event.wait so /stop takes effect promptly.
                    self._stop_event.wait(target_dt - elapsed)
        finally:
            if self._returncode is None:
                self._returncode = 0
            self._cleanup()

    def _dispatch_broadcast(
        self,
        joints_rad: Dict[str, float],
        ts: float,
        manager: Any,
        JointData: Any,
    ) -> None:
        """Update manager state and push a joint_update frame to /ws/ui."""
        try:
            jd = JointData(
                j1=float(joints_rad.get("1", 0.0)),
                j2=float(joints_rad.get("2", 0.0)),
                j3=float(joints_rad.get("3", 0.0)),
                j4=float(joints_rad.get("4", 0.0)),
                j5=float(joints_rad.get("5", 0.0)),
                j6=float(joints_rad.get("6", 0.0)),
                timestamp=ts,
            )
            manager.update_data(jd)
        except Exception as exc:
            self._log_line(f"manager.update_data failed: {exc}")

        payload = {
            "type": "joint_update",
            "robot_id": getattr(manager, "last_robot_id", "so101-001"),
            "timestamp": ts,
            "joints": joints_rad,
            "meta": {"source": "leader_arm", "transport": "inprocess"},
        }
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(manager.broadcast(payload), self._loop)
        except RuntimeError:
            # Loop closed mid-shutdown — ignore.
            pass
        except Exception as exc:
            self._log_line(f"broadcast dispatch failed: {exc}")

    def _cleanup(self) -> None:
        try:
            if self._writer is not None:
                self._writer.disable_torque()
        except Exception as exc:
            self._log_line(f"disable_torque failed: {exc}")
        try:
            if self._writer is not None:
                self._writer.disconnect()
        except Exception:
            pass
        try:
            if self._reader is not None:
                self._reader.disconnect()
        except Exception:
            pass
        self._log_line("cleanup done; both arms disconnected, follower torque off")

    # ------------------------------------------------------------------
    def stop(self, timeout_s: float = 6.0) -> None:
        """Signal the worker to exit and wait up to `timeout_s` for it."""
        if self._thread is None:
            self._log_line("not started")
            return
        if not self._thread.is_alive():
            self._log_line("already exited")
            return
        self._log_line("stop requested; signalling worker thread")
        self._stop_event.set()
        self._thread.join(timeout=timeout_s)
        if self._thread.is_alive():
            # Worker is stuck in a serial read; the SDK's read has a short
            # timeout so this should be rare. Force-cleanup the buses so
            # the next /start can re-open them.
            self._log_line(
                "[WARN] worker thread did not exit in time; forcing cleanup"
            )
            self._cleanup()

    # ------------------------------------------------------------------
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def to_process_status(self) -> ProcessStatus:
        return ProcessStatus(
            role=self.role,
            alive=self.is_alive(),
            pid=os.getpid() if self.is_alive() else None,
            returncode=self._returncode,
            stderr_tail=list(self._log),
        )


# ---------------------------------------------------------------------------
# Module-level single-session state (matches the old sender contract)
# ---------------------------------------------------------------------------


_session: Optional[Any] = None  # _TeleopCLIProcess | _TeleopInProcessLoop
_lock: Optional[asyncio.Lock] = None  # created lazily on first use


def _get_lock() -> asyncio.Lock:
    """Lazy-init the asyncio.Lock so importing this module doesn't pin a loop.

    Must only be called from inside an async handler (there we're on the
    uvicorn loop and asyncio.Lock() will bind to it correctly).
    """
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _snapshot_session_status() -> SessionStatus:
    sess = _session  # atomic read — GIL-safe
    if sess is None:
        return SessionStatus(running=False)
    proc = sess.to_process_status()
    return SessionStatus(
        running=proc.alive,
        session_id=sess.session_id,
        leader_port=sess.leader_port,
        follower_port=sess.follower_port,
        started_at=sess.started_at,
        uptime_s=max(0.0, time.time() - sess.started_at),
        processes=[proc],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start", response_model=SessionStatus)
async def start_teleop(req: StartRequest) -> SessionStatus:
    global _session

    if req.leader_port == req.follower_port:
        raise HTTPException(400, "leader_port and follower_port must differ")

    # Dependency pre-check: fail fast with a structured error the wizard UI
    # can render with a copy-paste fix command, instead of letting the spawn
    # path raise FileNotFoundError or ImportError mid-flight.
    mode = _teleop_mode()
    missing = _check_teleop_dependencies(mode)
    if missing:
        venv_pip = os.path.join(os.path.dirname(sys.executable), "pip")
        fix_hint = (
            f"{venv_pip} install lerobot[feetech]"
            if os.path.isfile(venv_pip)
            else "pip install lerobot[feetech]  # inside apps/realtime/.venv"
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "missing_dependency",
                "message": (
                    f"teleop ({mode} mode) cannot start because required "
                    f"package(s) are not installed: {', '.join(missing)}"
                ),
                "missing": missing,
                "mode": mode,
                "fix_hint": fix_hint,
            },
        )

    lock = _get_lock()
    async with lock:
        # Reap dead session so a crashed run doesn't block restart.
        # Important: also release port locks tied to the dead session ID.
        # Otherwise /start can fail with `port_in_use` while /status says
        # `running=false`, because the in-memory lock outlives the subprocess.
        if _session is not None and not _session.is_alive():
            dead_session_id = _session.session_id
            dead_ports = [_session.leader_port, _session.follower_port]
            logger.info("reaping dead session %s before new start", dead_session_id)
            # Normal path: leases are associated with session_id.
            await port_lock_manager.release_for_process(dead_session_id)
            # Crash-window fallback: if the process died before register_process(),
            # leases may exist without process_id. Release by explicit ports too.
            await port_lock_manager.release(dead_ports)
            _session = None

        # Defensive GC: if no active teleop session exists but requested ports are
        # still marked as owned by "teleop", clear stale locks so UI-only restart
        # works without a full realtime process restart.
        if _session is None:
            stale_ports: list[str] = []
            for p in (req.leader_port, req.follower_port):
                busy, owner = port_lock_manager.is_port_busy(p)
                if busy and owner == "teleop":
                    stale_ports.append(p)
            if stale_ports:
                logger.warning("clearing stale teleop port locks: %s", stale_ports)
                await port_lock_manager.release(stale_ports)

        if _session is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "teleop session already running",
                    "session_id": _session.session_id,
                    "hint": "POST /api/teleop/stop first",
                },
            )

        leader_id = _resolve_device_id("leader")
        follower_id = _resolve_device_id("follower")
        leader_dir = _expected_calibration_dir("leader")
        follower_dir = _expected_calibration_dir("follower")
        logger.info(
            "teleop calibration: leader id=%s dir=%s  follower id=%s dir=%s",
            leader_id, leader_dir, follower_id, follower_dir,
        )

        # Pre-flight: if the JSON file we're going to hand to the CLI
        # doesn't actually exist on disk at the path we're about to pass,
        # fail NOW with a clear 412 instead of letting the subprocess
        # silently fall through to record_ranges_of_motion (which then
        # dies with `min == max` because nobody is moving the arm).
        if leader_id is not None:
            _jf = leader_dir / f"{leader_id}.json"
            if not _jf.is_file():
                raise HTTPException(
                    status_code=412,
                    detail={
                        "message": (
                            f"leader calibration file not found: {_jf}. "
                            "Run Step 2 calibration first, or set "
                            "BOTVERSEX_LEADER_DEVICE_ID to an id that exists."
                        ),
                    },
                )
        if follower_id is not None:
            _jf = follower_dir / f"{follower_id}.json"
            if not _jf.is_file():
                raise HTTPException(
                    status_code=412,
                    detail={
                        "message": (
                            f"follower calibration file not found: {_jf}. "
                            "Run Step 2 calibration first, or set "
                            "BOTVERSEX_FOLLOWER_DEVICE_ID to an id that exists."
                        ),
                    },
                )
        if follower_id is None:
            raise HTTPException(
                status_code=412,
                detail={
                    "message": (
                        "follower arm has no lerobot calibration under "
                        "~/.cache/huggingface/lerobot/calibration/robots/so101_follower/. "
                        "Run Step 2 calibration first."
                    ),
                    "hint": "Use the Step 2 wizard to calibrate the follower arm.",
                },
            )
        if leader_id is None:
            raise HTTPException(
                status_code=412,
                detail={
                    "message": (
                        "leader arm has no lerobot calibration under "
                        "~/.cache/huggingface/lerobot/calibration/teleoperators/so101_leader/. "
                        "Run Step 2 calibration first."
                    ),
                    "hint": "Use the Step 2 wizard to calibrate the leader arm.",
                },
            )

        # Arm alignment pre-flight — see _alignment_report docstring. We
        # block with a structured 412 so the wizard can render a useful
        # dialog ("nudge leader's wrist_flex about 24° in the + direction"),
        # not a bare "error" toast. Skipped entirely if the operator set
        # force=True (see StartRequest.force).
        if not req.force:
            loop_pre = asyncio.get_running_loop()
            report = await loop_pre.run_in_executor(
                None,
                _alignment_report,
                req.leader_port,
                req.follower_port,
                leader_id,
                follower_id,
            )
            if report.get("skipped"):
                logger.warning(
                    "alignment check skipped (could not read one of the arms); "
                    "proceeding without pre-check"
                )
            elif not report.get("ok"):
                raise HTTPException(
                    status_code=412,
                    detail={
                        "code": "arms_not_aligned",
                        "message": (
                            "Leader and follower arms are not aligned. Move "
                            "the LEADER arm by hand so its joints roughly "
                            "match the follower, then try again. Or pass "
                            "force=true to override (the follower may jerk)."
                        ),
                        "alignment": report,
                    },
                )

        # Seed follower Goal_Position = Present_Position BEFORE the CLI
        # spawns. Eliminates the first-tick current spike that trips weak
        # motors off the RS-485 bus on this arm (see docstring). Best-
        # effort — if the read/write fails we still let the CLI start;
        # the user just sees the old startup jerk.
        loop_seed = asyncio.get_running_loop()
        seeded_ok = await loop_seed.run_in_executor(
            None, _seed_follower_goal_to_present, req.follower_port, follower_id,
        )
        if not seeded_ok:
            logger.warning(
                "seed-goal: follower seeding did not complete cleanly; "
                "CLI will still start but first-tick jerk may return"
            )

        # Record the ports with port_lock_manager so another feature (e.g.
        # recording in Step 4) can't race us on the same /dev/ttyACM*.
        # Acquired here (before spawn) and released either in /stop or on
        # the failure path below.
        teleop_ports = [req.leader_port, req.follower_port]
        try:
            await port_lock_manager.acquire(
                teleop_ports, owner="teleop", mode="subprocess",
            )
        except PortInUseError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "port_in_use",
                    "message": str(exc),
                    "port": exc.port,
                    "owner": exc.owner,
                },
            ) from exc

        # Choose execution mode. In-process keeps URDF preview live; CLI
        # is the legacy path. Both expose the same public methods.
        sess: Any
        if mode == "inprocess":
            sess = _TeleopInProcessLoop(
                leader_port=req.leader_port,
                follower_port=req.follower_port,
                leader_id=leader_id,
                follower_id=follower_id,
            )
            logger.info(
                "starting in-process teleop loop (URDF preview will stream "
                "joint_update to /ws/ui)"
            )
        else:
            sess = _TeleopCLIProcess(
                leader_port=req.leader_port,
                follower_port=req.follower_port,
                leader_id=leader_id,
                follower_id=follower_id,
            )
            logger.info(
                "starting CLI teleop subprocess (URDF preview will be static "
                "during teleop)"
            )
        # Spawn is blocking (up to ~8s waiting for readiness). Offload to
        # the executor so other /status polls on the loop stay responsive.
        # We must capture the running loop HERE (we're on the loop thread)
        # and pass it down — the executor's worker thread has no current
        # loop, so the in-process variant can't grab it itself.
        loop = asyncio.get_running_loop()
        start_call = (
            (lambda: sess.start(loop=loop))
            if isinstance(sess, _TeleopInProcessLoop)
            else sess.start
        )
        try:
            await loop.run_in_executor(None, start_call)
        except RuntimeError as exc:
            await port_lock_manager.release(teleop_ports)
            # Surface the CLI's own stderr tail so the UI can show why.
            raise HTTPException(
                status_code=500,
                detail={"message": str(exc), "mode": mode},
            ) from exc
        except Exception as exc:
            await port_lock_manager.release(teleop_ports)
            logger.exception("unexpected failure starting teleop (mode=%s)", mode)
            raise HTTPException(
                status_code=500,
                detail={
                    "message": f"{type(exc).__name__}: {exc}",
                    "mode": mode,
                },
            ) from exc

        await port_lock_manager.register_process(sess.session_id, teleop_ports)
        _session = sess
        # `torque_on_start` is accepted for wire compat. In CLI mode the CLI
        # manages torque itself; in-process mode enables follower torque in
        # `_TeleopInProcessLoop.start()` before the worker thread spins.
        if req.torque_on_start is False:
            logger.info(
                "torque_on_start=False requested but is currently ignored "
                "(both CLI and in-process modes always engage follower torque)."
            )
    return _snapshot_session_status()


@router.post("/stop", response_model=SessionStatus)
async def stop_teleop() -> SessionStatus:
    global _session
    lock = _get_lock()
    async with lock:
        if _session is None:
            return SessionStatus(running=False)
        logger.info("stopping session %s", _session.session_id)
        sess = _session
        # Offload the blocking wait to the executor so concurrent /status
        # polls stay responsive during the 1-6s shutdown window.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, sess.stop)
        status = _snapshot_session_status()
        # Give the kernel a beat to actually close the tty before we drop
        # our port lock — otherwise a fast /start after /stop can race.
        await asyncio.sleep(0.3)
        await port_lock_manager.release_for_process(sess.session_id)
        _session = None
    status.running = False
    status.session_id = None
    return status


@router.post("/alignment_check", response_model=AlignmentReport)
async def alignment_check(req: AlignmentCheckRequest) -> AlignmentReport:
    """Preview per-joint leader/follower offset BEFORE starting teleop.

    Safe to call at any time the arms are free (no active teleop session
    holding the ports). Opens each arm read-only, reads Present_Position,
    closes. Does not enable torque, does not write anything.

    The wizard calls this after the user clicks "Check alignment" on
    Step 3. If any joint is outside tolerance, the returned mismatches
    list tells them which joint and by roughly how many degrees. Same
    structure as the 412 detail from /start so the frontend can share
    one renderer.
    """
    if req.leader_port == req.follower_port:
        raise HTTPException(400, "leader_port and follower_port must differ")

    # Don't race the CLI: if teleop is running it owns both ports, and
    # our read would either fail (EBUSY) or worse, collide on the bus.
    current = _session
    if current is not None and current.is_alive():
        raise HTTPException(
            409,
            detail=(
                "a teleop session is currently running and owns both serial "
                "ports; stop it before checking alignment"
            ),
        )

    leader_id = _resolve_device_id("leader")
    follower_id = _resolve_device_id("follower")
    if not leader_id or not follower_id:
        raise HTTPException(
            status_code=412,
            detail="leader/follower calibration missing — run Step 2 first",
        )

    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(
        None,
        _alignment_report,
        req.leader_port,
        req.follower_port,
        leader_id,
        follower_id,
    )
    return AlignmentReport(**report)  # type: ignore[arg-type]


@router.get("/status", response_model=SessionStatus)
async def get_status() -> SessionStatus:
    # Lock-free on purpose — reading _session is atomic under the GIL and
    # a torn view of a _TeleopCLIProcess's fields is harmless (we'd just
    # report slightly stale status for one poll).
    return _snapshot_session_status()


# ---------------------------------------------------------------------------
# Torque rescue — same as before, independent of the CLI wrapper.
# ---------------------------------------------------------------------------


def _release_torque_blocking(port: str) -> Dict[str, object]:
    """Open the given serial port, write Torque_Enable=0 to all 6 motors.

    Used as a rescue when a previous teleop session died hard (SIGKILL, OOM,
    USB unplug) before it could disable torque. Safe to call any time —
    it's a no-op if torque was already off.
    """
    try:
        from lerobot.motors.feetech import FeetechMotorsBus  # type: ignore
        sender_path = str(REALTIME_ROOT)
        if sender_path not in sys.path:
            sys.path.insert(0, sender_path)
        from sender.lerobot_calibration import build_motors_dict  # type: ignore
    except ImportError as exc:
        return {
            "ok": False,
            "message": f"lerobot motors SDK not importable: {exc}",
            "motors_released": 0,
        }

    motors = build_motors_dict()
    bus = FeetechMotorsBus(port=port, motors=motors)
    try:
        try:
            bus.connect()
        except Exception as exc:
            return {
                "ok": False,
                "message": f"cannot open {port}: {type(exc).__name__}: {exc}",
                "motors_released": 0,
            }

        released = 0
        for name in motors:
            try:
                bus.write("Torque_Enable", name, 0, normalize=False)
                released += 1
            except Exception as exc:
                logger.warning("release torque on %s failed: %s", name, exc)
        return {
            "ok": released > 0,
            "message": (
                f"released torque on {released}/{len(motors)} motors — "
                "you can now move the arm by hand."
                if released > 0
                else "no motors responded; check power and USB cable."
            ),
            "motors_released": released,
        }
    finally:
        try:
            if getattr(bus, "is_connected", False):
                bus.disconnect()
        except Exception:
            pass


@router.post("/release_torque", response_model=ReleaseTorqueResponse)
async def release_torque(req: ReleaseTorqueRequest) -> ReleaseTorqueResponse:
    """Force-release torque on an arm that got stuck locked.

    Refuses to run while an active teleop session holds the same port —
    caller should /stop first. This avoids confusing state (we'd open the
    port while the CLI is still using it, causing EBUSY and worse).
    """
    current = _session
    if current is not None and (
        current.leader_port == req.port or current.follower_port == req.port
    ):
        raise HTTPException(
            409,
            detail=(
                f"{req.port} is currently held by teleop session "
                f"{current.session_id}; stop teleop first, then call "
                "/release_torque."
            ),
        )
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _release_torque_blocking, req.port)
    return ReleaseTorqueResponse(
        ok=bool(result.get("ok")),
        message=str(result.get("message", "")),
        motors_released=int(result.get("motors_released", 0)),
    )
