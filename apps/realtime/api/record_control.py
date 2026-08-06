"""Dataset recording — thin wrapper around the official ``lerobot-record`` CLI.

Same design philosophy as ``teleop_control.py``:
  * We do NOT re-implement the record loop. MakerMods spawns
    ``lerobot-record`` with the right flags and lets it own both serial
    ports + cameras + parquet writer + optional HF push.
  * We arbitrate with ``port_lock_manager`` so a running teleop session
    cannot accidentally race recording on the same ``/dev/ttyACM*``.
  * We surface a single-session API that the Step 4 wizard drives:

        POST /api/recording/start        → RecordingSession
        POST /api/recording/stop         → RecordingSession
        GET  /api/recording/status       → RecordingSession

The CLI writes datasets under
``~/.cache/huggingface/lerobot/<repo_id>/`` — that's the same place every
other LeRobot tool looks, including Step 5 training.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ._cli_process import CLIProcess, resolve_cli_binary
from .camera import stop_all_streams as _stop_all_camera_streams, _probe_status as _probe_camera_status
from .port_lock import port_lock_manager, PortInUseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recording", tags=["recording"])


# ---------------------------------------------------------------------------
# Schemas.
# ---------------------------------------------------------------------------


class CameraSpec(BaseModel):
    """Minimal OpenCV camera config — forwarded as-is to ``lerobot-record``."""

    name: str = Field(..., description="Used as the feature name in the dataset (e.g. 'top').")
    index_or_path: int | str = Field(
        ..., description="V4L2 index (0, 1, ...) or device path (/dev/video0)."
    )
    width: int = 640
    height: int = 480
    fps: int = 30


class StartRequest(BaseModel):
    # Hardware
    leader_port: str = Field(..., description="Serial device for the leader arm.")
    follower_port: str = Field(..., description="Serial device for the follower arm.")
    leader_id: Optional[str] = Field(
        None,
        description=(
            "Calibration id for the leader. If omitted we use "
            "BOTVERSEX_LEADER_DEVICE_ID or ``single_leader``."
        ),
    )
    follower_id: Optional[str] = Field(
        None,
        description=(
            "Calibration id for the follower. If omitted we use "
            "BOTVERSEX_FOLLOWER_DEVICE_ID or ``single_follower``."
        ),
    )
    cameras: List[CameraSpec] = Field(
        default_factory=list,
        description="Zero or more cameras. Zero is legal — MLP-only datasets don't need frames.",
    )

    # Dataset
    repo_id: str = Field(
        ...,
        description=(
            "HuggingFace-style id — e.g. ``amd/pick-block``. "
            "Dataset is written to ~/.cache/huggingface/lerobot/<repo_id>/."
        ),
    )
    single_task: str = Field(
        ...,
        description="Short natural-language description of the task (shown to SmolVLA later).",
    )
    num_episodes: int = Field(5, ge=1, le=200)
    episode_time_s: int = Field(30, ge=5, le=600)
    reset_time_s: int = Field(5, ge=0, le=120)
    fps: int = Field(30, ge=5, le=60)

    # Push-to-hub is OFF by default — we want the data local first, the
    # wizard's Step 5 will push explicitly if the user asks.
    push_to_hub: bool = False


class SessionStatus(BaseModel):
    running: bool
    session_id: Optional[str] = None
    pid: Optional[int] = None
    returncode: Optional[int] = None
    started_at: Optional[float] = None

    # Mirror of the subprocess log tail, for the UI.
    log_tail: List[str] = Field(default_factory=list)
    last_error: Optional[str] = None

    # Best-effort parsed progress — filled in by ``_parse_progress`` from
    # the same log stream. Safe to treat as advisory only.
    current_episode: Optional[int] = None
    total_episodes: Optional[int] = None
    dataset_dir: Optional[str] = None
    repo_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _expected_calibration_dir(device_type: str) -> Path:
    """Same rule ``teleop_control`` uses.

    ``~/.cache/huggingface/lerobot/calibration/<robots|teleoperators>/so101_<follower|leader>/``
    """
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    subdir = "teleoperators" if device_type == "leader" else "robots"
    return base / "lerobot" / "calibration" / subdir / f"so101_{device_type}"


def _resolve_device_id(device_type: str, explicit: Optional[str]) -> str:
    """Priority: request param → env var → hard-coded default.

    The default (``single_leader`` / ``single_follower``) matches MakerMods
    so datasets recorded here can be read by their tooling without renames.
    """
    if explicit:
        return explicit
    env_var = {
        "leader": "BOTVERSEX_LEADER_DEVICE_ID",
        "follower": "BOTVERSEX_FOLLOWER_DEVICE_ID",
    }[device_type]
    if (v := os.environ.get(env_var)):
        return v
    return f"single_{device_type}"


_PROGRESS_RE_EP = re.compile(r"episode\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_PROGRESS_RE_DIR = re.compile(r"dataset.*?:\s*(\S+huggingface/lerobot/\S+)", re.IGNORECASE)


def _parse_progress(log_tail: List[str]) -> Dict[str, Any]:
    """Best-effort: pick episode counters / dataset path out of CLI chatter.

    We aren't parsing a stable protocol — the CLI just logs prose. Extending
    this is cheap, but failing to extract anything must never fail the
    status endpoint.
    """
    current: Optional[int] = None
    total: Optional[int] = None
    dataset_dir: Optional[str] = None
    for line in reversed(log_tail):
        if current is None and (m := _PROGRESS_RE_EP.search(line)):
            try:
                current = int(m.group(1))
                total = int(m.group(2))
            except ValueError:
                pass
        if dataset_dir is None and (m := _PROGRESS_RE_DIR.search(line)):
            dataset_dir = m.group(1)
        if current is not None and dataset_dir is not None:
            break
    return {
        "current_episode": current,
        "total_episodes": total,
        "dataset_dir": dataset_dir,
    }


# ---------------------------------------------------------------------------
# CLI subprocess wrapper.
# ---------------------------------------------------------------------------


class _RecordCLI(CLIProcess):
    role = "lerobot-record"

    # Once we see a line like ``Recording episode 1/5`` the CLI has
    # opened both serial ports, both cameras, allocated the parquet file
    # and started streaming. Perfect "I'm alive" signal.
    ready_patterns = (
        re.compile(r"recording\s+episode", re.IGNORECASE),
        re.compile(r"start\s+recording", re.IGNORECASE),
        re.compile(r"\bfps\b", re.IGNORECASE),
    )

    def __init__(self, req: StartRequest, leader_id: str, follower_id: str) -> None:
        super().__init__()
        self.req = req
        self.leader_id = leader_id
        self.follower_id = follower_id

    def build_cmd(self) -> List[str]:
        cameras_dict = {
            cam.name: {
                "type": "opencv",
                # lerobot's OpenCV camera accepts either an int index or a
                # string path — just forward what the UI sent.
                "index_or_path": cam.index_or_path,
                "width": cam.width,
                "height": cam.height,
                "fps": cam.fps,
            }
            for cam in self.req.cameras
        }
        leader_dir = _expected_calibration_dir("leader")
        follower_dir = _expected_calibration_dir("follower")
        return [
            resolve_cli_binary("lerobot-record"),
            "--robot.type=so101_follower",
            f"--robot.port={self.req.follower_port}",
            f"--robot.id={self.follower_id}",
            f"--robot.calibration_dir={follower_dir}",
            f"--robot.cameras={json.dumps(cameras_dict)}",
            "--teleop.type=so101_leader",
            f"--teleop.port={self.req.leader_port}",
            f"--teleop.id={self.leader_id}",
            f"--teleop.calibration_dir={leader_dir}",
            f"--dataset.repo_id={self.req.repo_id}",
            f"--dataset.single_task={self.req.single_task}",
            f"--dataset.num_episodes={self.req.num_episodes}",
            f"--dataset.episode_time_s={self.req.episode_time_s}",
            f"--dataset.reset_time_s={self.req.reset_time_s}",
            f"--dataset.fps={self.req.fps}",
            f"--dataset.push_to_hub={'true' if self.req.push_to_hub else 'false'}",
            "--display_data=false",
        ]


# ---------------------------------------------------------------------------
# Module-level single-session state.
# ---------------------------------------------------------------------------


_session: Optional[_RecordCLI] = None
_held_ports: List[str] = []
_lock: Optional[asyncio.Lock] = None
_reaped_session_ids: set[str] = set()  # sessions we've already released locks for


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _reap_if_dead(sess: _RecordCLI) -> bool:
    """If ``sess`` has exited, release any port leases we acquired for it.

    Safe to call many times (tracked in ``_reaped_session_ids``). Called
    from every entry point that observes session state (``_snapshot``,
    ``start_recording``, ``stop_recording``) so the system self-heals as
    soon as *anyone* looks at it — closes the window where ``lerobot-record``
    crashes in the middle of an episode and leaves ``port_lock_manager``
    with a dangling "recording" lease.
    """
    global _held_ports
    if sess.is_alive():
        return False
    if sess.session_id in _reaped_session_ids:
        return True

    # Release by explicit port list first: ``release_for_process`` is a
    # no-op if the session died between ``acquire`` and ``register_process``
    # (process_id was never registered), whereas ``release(ports)`` only
    # needs the port lease to exist.
    ports = list(_held_ports) if _held_ports else []
    try:
        if ports:
            # schedule on the running loop if we're in async context,
            # otherwise do it synchronously through a new loop. Called
            # from both sync (status probes) and async contexts.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(port_lock_manager.release(ports))
            except RuntimeError:
                asyncio.run(port_lock_manager.release(ports))
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(port_lock_manager.release_for_process(sess.session_id))
        except RuntimeError:
            asyncio.run(port_lock_manager.release_for_process(sess.session_id))
    except Exception as exc:
        logger.warning("record: reap: lock release failed for %s: %s", sess.session_id, exc)

    # Also drop any lingering preview streams we might still be serving;
    # once recording is dead the UI will want fresh preview access.
    try:
        _stop_all_camera_streams(0.5)
    except Exception as exc:
        logger.warning("record: reap: stop_all_streams failed: %s", exc)

    _reaped_session_ids.add(sess.session_id)
    _held_ports = []
    logger.info("record: reaped dead session %s (rc=%s)", sess.session_id, sess.returncode)
    return True


def _snapshot() -> SessionStatus:
    sess = _session
    if sess is None:
        return SessionStatus(running=False)
    # Self-healing: if the CLI has died, free the locks right now so the
    # next teleop/record call isn't blocked by a phantom "in use by recording".
    _reap_if_dead(sess)
    tail = sess.log_tail
    progress = _parse_progress(tail)
    return SessionStatus(
        running=sess.is_alive(),
        session_id=sess.session_id,
        pid=sess.pid,
        returncode=sess.returncode,
        started_at=sess.started_at,
        log_tail=tail,
        last_error=sess.last_error,
        current_episode=progress["current_episode"],
        total_episodes=progress["total_episodes"] or sess.req.num_episodes,
        dataset_dir=progress["dataset_dir"],
        repo_id=sess.req.repo_id,
    )


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@router.post("/start", response_model=SessionStatus)
async def start_recording(req: StartRequest) -> SessionStatus:
    """Spawn ``lerobot-record``. Holds both serial ports via port_lock_manager.

    Returns 409 if either port is already held (e.g. teleop is running).
    The UI is expected to ask the user to stop teleop first.
    """
    global _session, _held_ports

    leader_id = _resolve_device_id("leader", req.leader_id)
    follower_id = _resolve_device_id("follower", req.follower_id)

    async with _get_lock():
        # Reap a dead prior session so stale lock state from a failed run
        # doesn't poison the next start attempt ("port in use by recording").
        # Covers both paths:
        #   (a) ``release_for_process`` — works when register_process ran
        #   (b) ``release(ports)``      — works when the CLI died between
        #       ``acquire`` and ``register_process`` (process map is empty)
        if _session is not None and not _session.is_alive():
            logger.info("record: reaping dead session %s before new start", _session.session_id)
            try:
                await port_lock_manager.release_for_process(_session.session_id)
            except Exception as exc:  # best-effort
                logger.warning("record: failed to release stale process lock: %s", exc)
            if _held_ports:
                try:
                    await port_lock_manager.release(_held_ports)
                except Exception as exc:
                    logger.warning("record: failed to release ports directly: %s", exc)
            _session = None
            _held_ports = []

        if _session and _session.is_alive():
            raise HTTPException(
                status_code=409,
                detail={"code": "recording_already_running", "message": "Recording already in progress."},
            )

        # ------------------------------------------------------------------
        # Camera pre-flight — the #1 source of "lerobot-record launched then
        # died" in the wild. Two sub-checks, cheap, run in a thread so the
        # event loop stays responsive:
        #   1) validate that every camera.index_or_path in the request is
        #      actually backed by an openable V4L2 device RIGHT NOW.
        #   2) tear down any MJPEG / WS preview we're serving, so the CLI
        #      doesn't fight us over /dev/videoN. Mirrors MakerMods'
        #      `_stop_all_streams` called just before subprocess launch.
        # ------------------------------------------------------------------
        if req.cameras:
            probe = await asyncio.to_thread(_probe_camera_status)
            # Build a {index -> node} lookup for O(1) membership tests.
            by_index: Dict[Any, Dict[str, Any]] = {
                n["index"]: n for n in probe.get("nodes", [])
            }
            missing: List[Dict[str, Any]] = []
            fps_adjustments: List[Dict[str, Any]] = []
            for cam in req.cameras:
                raw_id = cam.index_or_path
                # Only validate int-style indices here; if the user passed a
                # ``/dev/videoN`` string we trust them (lerobot-record also
                # accepts paths and will fail loudly on its own).
                try:
                    idx = int(raw_id)
                except (TypeError, ValueError):
                    continue
                node = by_index.get(idx)
                if node is None or not node.get("readable"):
                    missing.append(
                        {
                            "name": cam.name,
                            "requested_index": idx,
                            "opened": bool(node and node.get("opened")),
                            "present": node is not None,
                        }
                    )
                    continue

                # Align per-camera FPS to what OpenCV actually reports. Some
                # UVC cams are hard-locked at 25fps and lerobot raises if we
                # ask for 30 ("failed to set fps=30 (actual_fps=25.0)").
                actual_fps = int(round(float(node.get("fps") or 0)))
                if actual_fps > 0 and cam.fps != actual_fps:
                    fps_adjustments.append(
                        {
                            "name": cam.name,
                            "index": idx,
                            "requested_fps": cam.fps,
                            "actual_fps": actual_fps,
                        }
                    )
                    cam.fps = actual_fps

            if missing:
                # Suggest the first usable index so the UI can show a "use N"
                # button without another round-trip.
                usable = [
                    n["index"] for n in probe.get("nodes", [])
                    if n.get("readable")
                ]
                raise HTTPException(
                    status_code=412,
                    detail={
                        "code": "camera_unavailable",
                        "message": (
                            "One or more cameras cannot be opened for recording. "
                            "The camera may have been unplugged, its index may "
                            "have changed, or another app (browser preview / OBS / "
                            "Zoom) is still holding it."
                        ),
                        "missing": missing,
                        "available_indices": usable,
                    },
                )

            if fps_adjustments:
                logger.info("record: camera fps adjusted to hardware limits: %s", fps_adjustments)
                # Keep dataset fps <= the slowest camera fps to avoid
                # inconsistent timing assumptions in downstream tooling.
                req.fps = min(req.fps, min(c.fps for c in req.cameras if c.fps > 0))

            # Tear down any preview we're still serving. This is a no-op when
            # nothing is open. Short 1.5s drain keeps the first click snappy.
            stopped = await asyncio.to_thread(_stop_all_camera_streams, 1.5)
            if stopped:
                logger.info(
                    "record: stopped %d preview stream(s) before spawning CLI: %s",
                    len(stopped), [s["device"] for s in stopped],
                )
            # Small extra settle; V4L2 sometimes needs a breath to release
            # the device even after cap.release() returns.
            await asyncio.sleep(0.3)

        # Log exactly what we're about to hand to lerobot-record so the UI
        # can show the effective resolution of Step 1's selection (addresses
        # "is it really using index 1 or index 0?" confusion).
        logger.info(
            "record: starting with leader=%s(id=%s) follower=%s(id=%s) cameras=%s",
            req.leader_port, leader_id, req.follower_port, follower_id,
            [(c.name, c.index_or_path) for c in req.cameras],
        )

        ports = [req.leader_port, req.follower_port]
        # Build the session up-front so we can tag the lock with its id
        # BEFORE start(). Closes the "acquire-then-crash-before-register"
        # race: even if start() raises, the lease is tagged with our id,
        # so the reap path can release it via release_for_process.
        sess = _RecordCLI(req, leader_id=leader_id, follower_id=follower_id)
        try:
            await port_lock_manager.acquire(
                ports, owner="recording", mode="subprocess", process_id=sess.session_id,
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

        try:
            await asyncio.to_thread(sess.start, 12.0)
        except Exception as exc:
            # Release by both paths just in case — release_for_process works
            # because we passed process_id to acquire() above.
            try:
                await port_lock_manager.release_for_process(sess.session_id)
            except Exception:
                pass
            try:
                await port_lock_manager.release(ports)
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"start failed: {exc}") from exc

        _session = sess
        _held_ports = ports
        # process_id already tagged at acquire(); this is a no-op-safe call
        # that also refreshes _process_ports in case acquire didn't receive it
        # (older clients of this function path).
        await port_lock_manager.register_process(sess.session_id, ports)
        return _snapshot()


@router.post("/stop", response_model=SessionStatus)
async def stop_recording() -> SessionStatus:
    global _session, _held_ports
    async with _get_lock():
        sess = _session
        if sess is None:
            return SessionStatus(running=False)
        await asyncio.to_thread(sess.stop, 8.0)
        # Give the kernel a beat to actually release the tty before we drop
        # our lock — otherwise a fast retry can race with a half-closed fd.
        await asyncio.sleep(0.5)
        # Double-barrel release: release_for_process relies on _process_ports
        # being populated, which isn't guaranteed if the CLI crashed before
        # register_process; release(ports) handles that case.
        ports_to_release = list(_held_ports)
        try:
            await port_lock_manager.release_for_process(sess.session_id)
        except Exception as exc:
            logger.warning("record/stop: release_for_process failed: %s", exc)
        if ports_to_release:
            try:
                await port_lock_manager.release(ports_to_release)
            except Exception as exc:
                logger.warning("record/stop: release(ports) failed: %s", exc)
        _held_ports = []
        _reaped_session_ids.add(sess.session_id)
        snap = _snapshot()
        # Keep _session around for a short moment so the UI can read the
        # final returncode / log tail; it'll be overwritten on the next
        # /start. (MakerMods does the same.)
        return snap


@router.get("/status", response_model=SessionStatus)
async def get_status() -> SessionStatus:
    return _snapshot()


class ResetResponse(BaseModel):
    released_ports: List[str] = Field(default_factory=list)
    stopped_streams: int = 0
    previous_session_id: Optional[str] = None
    previous_returncode: Optional[int] = None
    previous_last_error: Optional[str] = None
    now_running: bool = False


@router.post("/reset", response_model=ResetResponse)
async def reset_recording() -> ResetResponse:
    """Emergency 'unstick' button for the UI.

    Forces release of any serial-port leases tagged 'recording', tears down
    every preview stream, and clears the local session reference. Does NOT
    touch an actually-running recording (returns ``now_running=true`` in
    that case so the UI can surface a confirmation dialog).

    Why this exists: when ``lerobot-record`` crashes in the middle of an
    episode (e.g. Leader bus glitch), resources can leak. Rather than
    asking the user to SSH in and kill processes, we expose a single
    idempotent endpoint they can hit from the browser.
    """
    global _session, _held_ports
    async with _get_lock():
        sess = _session
        if sess is not None and sess.is_alive():
            # Don't yank the rug out from under an active recording — the
            # caller should /stop first.
            return ResetResponse(
                previous_session_id=sess.session_id,
                previous_returncode=sess.returncode,
                previous_last_error=sess.last_error,
                now_running=True,
            )

        released: List[str] = []
        prev_sid = sess.session_id if sess else None
        prev_rc = sess.returncode if sess else None
        prev_err = sess.last_error if sess else None

        # Release by both paths for every "recording"-tagged lease, so this
        # works whether register_process ran or not.
        status = port_lock_manager.get_status()
        recording_ports = [
            raw for raw, info in status.items() if info.get("owner") == "recording"
        ]
        if sess is not None:
            try:
                await port_lock_manager.release_for_process(sess.session_id)
            except Exception as exc:
                logger.warning("record/reset: release_for_process failed: %s", exc)
        if recording_ports:
            try:
                await port_lock_manager.release(recording_ports)
                released.extend(recording_ports)
            except Exception as exc:
                logger.warning("record/reset: release(ports) failed: %s", exc)
        if _held_ports:
            try:
                await port_lock_manager.release(_held_ports)
                released.extend(p for p in _held_ports if p not in released)
            except Exception:
                pass

        stopped = await asyncio.to_thread(_stop_all_camera_streams, 0.8)

        if sess is not None:
            _reaped_session_ids.add(sess.session_id)
        _session = None
        _held_ports = []

        return ResetResponse(
            released_ports=released,
            stopped_streams=len(stopped),
            previous_session_id=prev_sid,
            previous_returncode=prev_rc,
            previous_last_error=prev_err,
            now_running=False,
        )


# Small helper endpoint for the UI: "do I have a dataset ready for Step 5?"
# We check ~/.cache/huggingface/lerobot/<repo_id>/ exists and has a meta
# folder. Not required for correctness, just nicer ergonomics.


class DatasetCheckResponse(BaseModel):
    exists: bool
    repo_id: str
    path: Optional[str] = None
    num_episodes: Optional[int] = None


@router.get("/dataset_check", response_model=DatasetCheckResponse)
async def dataset_check(repo_id: str) -> DatasetCheckResponse:
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    root = base / "lerobot" / repo_id
    if not root.is_dir():
        return DatasetCheckResponse(exists=False, repo_id=repo_id)

    num_eps: Optional[int] = None
    # LeRobotDataset v2.1 writes meta/info.json with total_episodes.
    info = root / "meta" / "info.json"
    if info.is_file():
        try:
            num_eps = int(json.loads(info.read_text()).get("total_episodes") or 0)
        except Exception:
            num_eps = None
    return DatasetCheckResponse(
        exists=True, repo_id=repo_id, path=str(root), num_episodes=num_eps,
    )
