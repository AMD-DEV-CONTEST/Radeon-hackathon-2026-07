"""Run a sim-trained ACT/lerobot policy on the REAL SO101 arm.

This is the hardware counterpart of ``eval_policy_so101.py``. The policy layer is
identical (same checkpoint, same preprocessor/postprocessor); only the observation
source and the action sink change:

    sim   : bundle.robot.get_qpos() (rad)      -> control_dofs_position(rad)
    real  : robot.get_observation() (deg dict) -> send_action(deg dict)

So the whole job of this file is a faithful **convention bridge**:

  1. joint ORDER   — the dataset stores a fixed 6-vector; the driver uses a dict
                     keyed ``<motor>.pos``. ``JOINT_ORDER`` pins the mapping.
  2. joint UNITS   — the driver reports/accepts DEGREES (``use_degrees=True``);
                     the dataset is in RADIANS. Converted both ways here.
  3. joint ZEROS   — sim zero (URDF) and real zero (lerobot calibration) need not
                     coincide. ``--sign`` / ``--offset-deg`` absorb per-joint sign
                     flips and zero offsets; ``--probe`` helps you measure them.
  4. camera KEYS   — cameras must be registered under the dataset's names
                     (``world`` / ``wrist``) so observations match training.

Safety: every command is clipped to ``--max-step-deg`` per control tick, the arm
is eased to the sim home pose before the policy takes over, and torque is released
on exit (``disable_torque_on_disconnect``).

Typical bring-up sequence:

    # 0) what does the arm report right now? (torque off, move it by hand)
    uv run python -m franka_fruit_pick.eval_policy_so101_real --port /dev/tty.usbmodemXXX --probe

    # 1) can we reproduce the SIM home pose on hardware? (no policy, no cameras)
    uv run python -m franka_fruit_pick.eval_policy_so101_real --port ... --home-only

    # 2) full closed-loop policy rollout
    uv run python -m franka_fruit_pick.eval_policy_so101_real --port ... \
        --cam-world 0 --cam-wrist 1 \
        --policy-path outputs/act_red_100000 \
        --repo-id omiya239532/so101_cube_red --dataset-root datasets/so101_cube_red \
        --episodes 3 --save-video
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from build_scene_so101 import SO101_HOME_QPOS, default_policy_device
from eval_policy_so101 import STATE_KEY, load_policy
from grasp_demo_so101 import GRIPPER_CLOSE, GRIPPER_IDLE, GRIPPER_OPEN

# The pose every demonstration starts and ends at: folded arm with the jaw
# RESTING OPEN. SO101_HOME_QPOS[5] is 0.0 and unused — run_pick_place drives the
# jaw with GRIPPER_IDLE — so rebuild the home vector the same way here.
HOME_QPOS = np.append(SO101_HOME_QPOS[:5], GRIPPER_IDLE)

# Dataset/sim joint order. Index i of observation.state / action corresponds to
# JOINT_ORDER[i]; the driver dict keys are f"{name}.pos".
JOINT_ORDER = [
    "shoulder_pan", "shoulder_lift", "elbow_flex",
    "wrist_flex", "wrist_roll", "gripper",
]
ARM = slice(0, 5)   # the 5 arm joints; index 5 is the gripper (different unit!)

# Dataset camera feature keys -> the names the robot config registers cameras under.
CAM_KEYS = {"observation.images.world": "world", "observation.images.wrist": "wrist"}


class JointBridge:
    """Converts between the driver's units and the dataset's radian-vector.

    The two are NOT uniform: the SO101 driver registers the 5 arm joints as
    ``MotorNormMode.DEGREES`` but the gripper as ``MotorNormMode.RANGE_0_100``
    (0 = calibrated closed, 100 = calibrated open). So:

        arm[i]  : real_deg = sign[i] * rad2deg(sim_rad) + offset_deg[i]
        gripper : real_0_100 = 100 * (sim_rad - CLOSE) / (OPEN - CLOSE), clipped

    where CLOSE/OPEN are the sim jaw angles the demonstrations were recorded with.
    """

    def __init__(self, sign: np.ndarray | None = None, offset_deg: np.ndarray | None = None,
                 grip_close_rad: float = GRIPPER_CLOSE, grip_open_rad: float = GRIPPER_OPEN):
        self.sign = np.ones(5) if sign is None else np.asarray(sign, dtype=np.float64)[:5]
        self.offset = np.zeros(5) if offset_deg is None else np.asarray(offset_deg, dtype=np.float64)[:5]
        self.g_close = float(grip_close_rad)
        self.g_open = float(grip_open_rad)

    # -- gripper unit conversion --------------------------------------------
    def _grip_to_real(self, sim_rad: float) -> float:
        frac = (sim_rad - self.g_close) / (self.g_open - self.g_close)
        return float(np.clip(frac, 0.0, 1.0) * 100.0)

    def _grip_to_sim(self, real_0_100: float) -> float:
        frac = float(np.clip(real_0_100, 0.0, 100.0)) / 100.0
        return self.g_close + frac * (self.g_open - self.g_close)

    # -- full-vector conversion ---------------------------------------------
    def to_sim_rad(self, obs: dict) -> np.ndarray:
        vals = np.array([float(obs[f"{j}.pos"]) for j in JOINT_ORDER], dtype=np.float64)
        out = np.empty(6, dtype=np.float64)
        out[ARM] = np.deg2rad((vals[ARM] - self.offset) / self.sign)
        out[5] = self._grip_to_sim(vals[5])
        return out

    def to_real(self, sim_rad) -> dict:
        q = np.asarray(sim_rad, dtype=np.float64).reshape(-1)
        vals = np.empty(6, dtype=np.float64)
        vals[ARM] = self.sign * np.rad2deg(q[ARM]) + self.offset
        vals[5] = self._grip_to_real(q[5])
        return {f"{j}.pos": float(v) for j, v in zip(JOINT_ORDER, vals)}


class SimpleCamera:
    """Minimal threaded UVC reader built directly on cv2.

    lerobot's OpenCVCamera enforces that the configured fps matches what the
    device reports, aborts if the first frame is slow to arrive, and raises on
    stale frames. Against these particular devices — a 120fps-locked wrist camera
    that ignores MJPG requests, and a top-down camera that reports 5fps while
    actually delivering ~15 — every one of those checks fires spuriously and kills
    the rollout. Raw cv2 reads have been reliable throughout, so own the loop:
    grab continuously in a thread, hand out the newest frame, never raise.
    """

    def __init__(self, index: int, width: int = 320, height: int = 240):
        import cv2
        self.index = index
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera {index} did not open")
        # NO resolution request: asking this rig's wrist camera for 320x240 selects
        # its 120 fps mode, which stalls every ~9 s (frames keep arriving but pixels
        # stop changing — one real eval ran 37% of an episode on a frozen wrist
        # image). Its native mode (1920x1080@30) soaked clean for 150 s, so capture
        # native and resize in _loop.
        self.width, self.height = width, height
        nw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        nh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[real] camera {index}: native {nw}x{nh} -> resize to {width}x{height}")
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # block until the first frame lands (or give up after ~10 s)
        deadline = time.time() + 10.0
        while self.latest() is None and time.time() < deadline:
            time.sleep(0.05)
        if self.latest() is None:
            raise RuntimeError(f"camera {index} delivered no frame within 10 s")

    def _loop(self) -> None:
        import cv2
        while not self._stop.is_set():
            ok, frame = self.cap.read()
            if ok and frame is not None:
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    # center-crop to the target aspect (16:9 native -> 4:3 target
                    # must not squash), then resize — mirrors the record launcher
                    fh, fw = frame.shape[:2]
                    want = self.width / self.height
                    if abs(fw / fh - want) > 0.01:
                        if fw / fh > want:
                            cw = int(fh * want)
                            x0 = (fw - cw) // 2
                            frame = frame[:, x0:x0 + cw]
                        else:
                            ch = int(fw / want)
                            y0 = (fh - ch) // 2
                            frame = frame[y0:y0 + ch, :]
                    frame = cv2.resize(frame, (self.width, self.height),
                                       interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                with self._lock:
                    self._frame = rgb
            else:
                time.sleep(0.01)      # transient read failure: back off, keep going

    def latest(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self.cap.release()


def parse_episode_list(spec: str | None) -> set[int] | None:
    """'0,3' / '3-5' / '0,4-6' -> {0,3} / {3,4,5} / {0,4,5,6}. None means "all"."""
    if not spec:
        return None
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(v) for v in part.split("-", 1))
            out.update(range(lo, hi + 1))
        else:
            out.add(int(part))
    return out


def probe_camera_fps(index: int, fallback: int = 30) -> int:
    """Native fps of a UVC camera. lerobot rejects a config fps the device won't
    honour (e.g. the wrist cam here is locked to 120), so ask the device first.
    The control loop rate is independent — we always read the latest frame."""
    import cv2
    cap = cv2.VideoCapture(index)
    try:
        if not cap.isOpened():
            return fallback
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        fps = cap.get(cv2.CAP_PROP_FPS)
        return int(round(fps)) if fps and fps > 1 else fallback
    finally:
        cap.release()
        # AVFoundation needs a moment before the device can be reopened, otherwise
        # the subsequent lerobot camera thread times out waiting for its first frame.
        time.sleep(0.5)


def make_robot(port: str, robot_id: str, cam_world: int | None, cam_wrist: int | None,
               width: int, height: int, fps: int, max_step_deg: float,
               cam_world_fps: int | None = None, cam_wrist_fps: int | None = None,
               cam_wrist_size: tuple[int, int] | None = None,
               cam_world_size: tuple[int, int] | None = None):
    """Build the robot handle.

    Camera fps must match what the device actually delivers (lerobot rejects a
    mismatch). ``cam_wrist_size`` lets the 120fps-locked wrist camera capture at a
    reduced resolution: AVFoundation ignores the MJPG request, so at 640x480 the
    UNCOMPRESSED 120fps stream (~74 MB/s) exhausts a shared USB controller when the
    world camera streams too. The observation is resized to the dataset resolution
    downstream, so a smaller capture stays policy-compatible.
    """
    from lerobot.cameras.opencv import OpenCVCameraConfig
    from lerobot.robots.so_follower import SO101Follower, SO101FollowerConfig

    def cam_cfg(index: int, want_fps: int | None, size: tuple[int, int] | None = None):
        native = want_fps if want_fps is not None else probe_camera_fps(index, fps)
        w, h = size if size is not None else (width, height)
        kwargs = dict(index_or_path=index, width=w, height=h, fps=native, warmup_s=3)
        if native > 60:
            kwargs["fourcc"] = "MJPG"   # best effort; ignored by AVFoundation
        return OpenCVCameraConfig(**kwargs)

    cameras = {}
    if cam_world is not None:
        cameras["world"] = cam_cfg(cam_world, cam_world_fps, cam_world_size)
    if cam_wrist is not None:
        cameras["wrist"] = cam_cfg(cam_wrist, cam_wrist_fps, cam_wrist_size)
    cfg = SO101FollowerConfig(
        port=port,
        id=robot_id,
        cameras=cameras,
        use_degrees=True,                  # dataset is radians; we convert explicitly
        max_relative_target=max_step_deg,  # driver-side safety clamp (deg per command)
        disable_torque_on_disconnect=True,
    )
    return SO101Follower(cfg)


def relax_camera_staleness(warn_after_ms: int = 1000) -> None:
    """Stop a stale camera frame from killing the rollout.

    ``SOFollower.get_observation()`` calls ``cam.read_latest()``, which raises if
    the newest buffered frame is older than 500 ms. Two things conspire against
    that budget here: ACT re-plans a 100-step chunk every ~3.3 s and occupies the
    main thread for ~310 ms, and the 120fps wrist camera intermittently stalls
    when it shares a USB controller with the world camera (frames have been seen
    2.5 s old). Aborting mid-episode is strictly worse than acting on a slightly
    old frame in a quasi-static task, so serve the last frame we have and just
    report when it gets old.
    """
    from lerobot.cameras.opencv import OpenCVCamera

    original = OpenCVCamera.read_latest
    state = {"warned": 0}

    def patched(self, max_age_ms: int = 10**9):
        try:
            return original(self, max_age_ms=warn_after_ms)
        except TimeoutError as exc:
            state["warned"] += 1
            if state["warned"] <= 3 or state["warned"] % 50 == 0:
                print(f"[real] stale frame tolerated ({exc})")
            return original(self, max_age_ms=10**9)   # serve whatever is buffered

    OpenCVCamera.read_latest = patched


def connect_with_retry(robot, attempts: int = 4, wait_s: float = 3.0) -> None:
    """Connect, retrying camera warm-up timeouts.

    The wrist UVC camera intermittently refuses to deliver its first frame right
    after a previous process released it; a short cool-off and another try clears it.
    """
    for k in range(1, attempts + 1):
        try:
            robot.connect()
            return
        except TimeoutError as exc:
            if k == attempts:
                raise
            print(f"[real] camera warm-up failed ({exc}); retry {k}/{attempts - 1} in {wait_s:.0f}s")
            # Tear down piecemeal: robot.disconnect() refuses to run when only part
            # of the stack came up, which would leave the motor bus connected and
            # make the next connect() raise DeviceAlreadyConnectedError.
            for cam in getattr(robot, "cameras", {}).values():
                try:
                    cam.disconnect()
                except Exception:
                    pass
            try:
                robot.bus.disconnect()
            except Exception:
                pass
            time.sleep(wait_s)


def ease_to(robot, bridge: JointBridge, target_rad, *, seconds: float = 3.0, fps: int = 30) -> None:
    """Ramp the arm from its present pose to `target_rad` (sim radians)."""
    start = bridge.to_sim_rad(robot.get_observation())
    target = np.asarray(target_rad, dtype=np.float64)
    n = max(1, int(seconds * fps))
    for i in range(1, n + 1):
        q = start + (target - start) * (i / n)
        robot.send_action(bridge.to_real(q))
        time.sleep(1.0 / fps)


def _resize(img, w: int, h: int) -> np.ndarray:
    import cv2
    img = np.asarray(img)
    if (img.shape[1], img.shape[0]) != (w, h):
        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(img, dtype=np.uint8)


def build_observation_real(bridge: JointBridge, pb, joint_obs: dict, cams: dict) -> dict:
    """Assemble the dataset's raw feature layout from joint state + our cameras."""
    h, w = pb.image_hw
    obs = {STATE_KEY: bridge.to_sim_rad(joint_obs).astype(np.float32)}
    for feat_key in pb.image_keys:
        name = CAM_KEYS.get(feat_key)
        cam = cams.get(name)
        if cam is None:
            raise RuntimeError(f"Dataset expects {feat_key!r} but camera {name!r} is not open.")
        obs[feat_key] = _resize(cam.latest(), w, h)
    return obs


def probe(robot, bridge: JointBridge) -> None:
    """Print the current pose in both conventions, with torque released so the arm
    can be posed by hand (connect() leaves the motors holding position)."""
    robot.bus.disable_torque()
    print("Torque OFF. Move the arm by hand; Ctrl-C to stop.\n")
    print(f"{'joint':<15}{'real(deg)':>12}{'sim(rad)':>12}")
    try:
        while True:
            raw = robot.get_observation()
            rad = bridge.to_sim_rad(raw)
            lines = [f"{j:<15}{float(raw[f'{j}.pos']):>12.2f}{rad[i]:>12.3f}"
                     for i, j in enumerate(JOINT_ORDER)]
            print("\n".join(lines))
            print(f"sim-vector: [{', '.join(f'{v:.3f}' for v in rad)}]")
            print(f"(demo home is [{', '.join(f'{v:.3f}' for v in HOME_QPOS)}])")
            print("-" * 40)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nstopped.")


def run_episode_real(robot, bridge: JointBridge, pb, cams: dict, *, task_text: str | None,
                     max_seconds: float, fps: int, frames: list | None,
                     slow: float = 1.0, smooth: float = 1.0) -> int:
    """One closed-loop rollout on hardware. Returns the number of policy steps.

    ``slow``   > 1 executes the chunk at reduced speed (each position target is
               held ``slow``× longer). Valid here because actions are position
               waypoints and the task is quasi-static — the same path is traced
               more slowly, and the 311 ms chunk-replan stall shrinks relative
               to the motion timescale.
    ``smooth`` in (0, 1] low-pass filters the commanded targets (EMA):
               cmd = smooth * action + (1 - smooth) * prev_cmd.
               1.0 = off. ~0.3-0.5 absorbs chunk-boundary jumps and dither at
               the cost of a slight tracking lag.
    """
    pb.reset()
    n_steps = int(max_seconds * fps)          # policy steps (chunk consumption)
    period = slow / fps                        # wall-clock per policy step
    cmd: np.ndarray | None = None
    for _ in range(n_steps):
        t0 = time.perf_counter()
        raw = robot.get_observation()
        obs = build_observation_real(bridge, pb, raw, cams)
        if frames is not None:
            panels = [obs[k] for k in pb.image_keys]
            frames.append(np.hstack(panels) if len(panels) > 1 else panels[0])

        action_rad = pb.select_action(obs, task_text)
        cmd = action_rad if cmd is None else smooth * action_rad + (1.0 - smooth) * cmd
        robot.send_action(bridge.to_real(cmd))

        dt = time.perf_counter() - t0
        if dt < period:
            time.sleep(period - dt)
    return n_steps


def main() -> None:
    p = argparse.ArgumentParser(description="Run a sim-trained policy on the real SO101.")
    p.add_argument("--port", required=True, help="Serial port (see: lerobot-find-port).")
    p.add_argument("--robot-id", default="so101_real", help="Calibration id used by lerobot-calibrate.")
    p.add_argument("--cam-world", type=int, default=None, help="OpenCV index of the top-down camera.")
    p.add_argument("--cam-wrist", type=int, default=None, help="OpenCV index of the wrist camera.")
    p.add_argument("--cam-world-fps", type=int, default=30,
                   help="Native fps of the top-down camera (must match the device).")
    p.add_argument("--cam-wrist-fps", type=int, default=120,
                   help="Native fps of the wrist camera (must match the device).")
    p.add_argument("--cam-wrist-capture", type=str, default=None, metavar="WxH",
                   help="Capture size for the wrist camera, e.g. '320x240'. Use when the "
                        "uncompressed 120fps stream saturates a shared USB controller; "
                        "the frame is resized to the dataset resolution for the policy.")
    p.add_argument("--cam-max-age-ms", type=int, default=1000,
                   help="Frame age above which a warning is printed. Stale frames are "
                        "used anyway — the rollout is never aborted for staleness.")
    p.add_argument("--cam-world-capture", type=str, default=None, metavar="WxH",
                   help="Capture size for the top-down camera, e.g. '320x240'. Lowers USB "
                        "bandwidth when both cameras share a controller.")
    p.add_argument("--cam-width", type=int, default=640)
    p.add_argument("--cam-height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30, help="Control loop rate (match the dataset fps).")
    p.add_argument("--max-step-deg", type=float, default=8.0,
                   help="Safety: max commanded change per joint per tick (deg).")
    p.add_argument("--sign", type=str, default=None,
                   help="Per-joint sign flips as 6 comma-separated +1/-1 (default all +1).")
    p.add_argument("--offset-deg", type=str, default=None,
                   help="Per-joint zero offsets in degrees, 6 comma-separated (default all 0).")
    # modes
    p.add_argument("--probe", action="store_true", help="Print live joint state and exit (no motion).")
    p.add_argument("--home-only", action="store_true",
                   help="Ease to the SIM home pose and hold — validates the conversion layer.")
    # policy
    p.add_argument("--policy-path", default=None)
    p.add_argument("--repo-id", default=None, help="Dataset repo id the policy was trained on.")
    p.add_argument("--dataset-root", default=None)
    p.add_argument("--device", default=default_policy_device())
    p.add_argument("--episodes", type=int, default=1)
    p.add_argument("--max-seconds", type=float, default=45.0)
    p.add_argument("--no-task", action="store_true")
    p.add_argument("--slow", type=float, default=1.0,
                   help=">1 executes the same trajectory more slowly (e.g. 2.0 = half speed).")
    p.add_argument("--smooth", type=float, default=1.0,
                   help="EMA factor on commanded targets in (0,1]; 1.0 = off, ~0.35 = smooth.")
    p.add_argument("--save-video", action="store_true")
    p.add_argument("--video-dir", default="outputs/real_videos")
    p.add_argument("--video-episodes", default=None, metavar="LIST",
                   help="Only record these episode indices, e.g. '0,3' or '3-5' or "
                        "'0,4-6'. Default: every episode (when --save-video is set).")
    p.add_argument("--ep-offset", type=int, default=0,
                   help="Index of the first episode. Use it to resume a run that died "
                        "partway (e.g. --ep-offset 3) so existing real_ep000..002.mp4 "
                        "and their results are not overwritten.")
    args = p.parse_args()

    sign = np.array([float(v) for v in args.sign.split(",")]) if args.sign else None
    offset = np.array([float(v) for v in args.offset_deg.split(",")]) if args.offset_deg else None
    bridge = JointBridge(sign, offset)

    # Cameras are managed by SimpleCamera, not lerobot: the robot handle drives
    # the motors only. See SimpleCamera's docstring for why.
    robot = make_robot(args.port, args.robot_id, None, None,
                       args.cam_width, args.cam_height, args.fps, args.max_step_deg)
    connect_with_retry(robot)
    print(f"[real] connected: {args.port} (id={args.robot_id})")

    def parse_wh(spec: str | None, default=(320, 240)):
        return tuple(int(v) for v in spec.split("x")) if spec else default

    cams: dict = {}
    if not (args.probe or args.home_only):
        for name, idx, spec in (("world", args.cam_world, args.cam_world_capture),
                                ("wrist", args.cam_wrist, args.cam_wrist_capture)):
            if idx is None:
                continue
            w, h = parse_wh(spec)
            cams[name] = SimpleCamera(idx, w, h)
            print(f"[real] camera {name}: index {idx} @ {w}x{h}")

    try:
        if args.probe:
            probe(robot, bridge)
            return

        if args.home_only:
            print(f"[real] easing to demo home {np.round(HOME_QPOS, 3).tolist()} (rad)")
            ease_to(robot, bridge, HOME_QPOS, seconds=4.0, fps=args.fps)
            reached = bridge.to_sim_rad(robot.get_observation())
            err = np.rad2deg(reached - HOME_QPOS)
            print(f"[real] reached (rad): [{', '.join(f'{v:.3f}' for v in reached)}]")
            print(f"[real] error  (deg): [{', '.join(f'{v:+.1f}' for v in err)}]")
            # Keep the hold SHORT: the folded home pose loads shoulder_lift, and the
            # STS3215 drops off the bus on sustained overload ("no status packet").
            print("[real] holding 3 s — compare the pose against the sim viewer.")
            t_end = time.time() + 3
            while time.time() < t_end:
                robot.send_action(bridge.to_real(HOME_QPOS))
                time.sleep(1.0 / args.fps)
            return

        if not (args.policy_path and args.repo_id):
            raise SystemExit("--policy-path and --repo-id are required for a policy rollout.")

        pb = load_policy(args.policy_path, args.repo_id, args.dataset_root, args.device)
        from record_dataset_so101 import TASK
        task_text = None if args.no_task else TASK
        video_eps = parse_episode_list(args.video_episodes)

        for ep in range(args.ep_offset, args.ep_offset + args.episodes):
            print(f"\n[real] --- episode {ep} --- easing to home")
            ease_to(robot, bridge, HOME_QPOS, seconds=4.0, fps=args.fps)
            input("[real] place the cube, then press Enter to start the policy...")

            # Videos are ~55 MB each; --video-episodes limits recording to the ones
            # worth keeping (e.g. "0,3" or "3-5"), so a long success-rate run does
            # not fill the disk. --save-video with no list records every episode.
            record = args.save_video and (video_eps is None or ep in video_eps)
            frames: list | None = [] if record else None
            steps = run_episode_real(robot, bridge, pb, cams, task_text=task_text,
                                     max_seconds=args.max_seconds, fps=args.fps, frames=frames,
                                     slow=args.slow, smooth=args.smooth)
            print(f"[real] episode {ep} done ({steps} policy steps)")

            if frames:
                import imageio.v2 as imageio
                out = Path(args.video_dir)
                out.mkdir(parents=True, exist_ok=True)
                path = out / f"real_ep{ep:03d}.mp4"
                imageio.mimwrite(str(path), frames, fps=args.fps, codec="libx264", quality=8)
                print(f"[real] saved {path}")
    finally:
        for cam in cams.values():
            try:
                cam.close()
            except Exception:
                pass
        # Ease to home BEFORE releasing torque: disconnect() disables the servos and
        # a raised arm otherwise drops under gravity when an episode aborts.
        try:
            ease_to(robot, JointBridge(), HOME_QPOS, seconds=3.0, fps=args.fps)
        except Exception as exc:
            print(f"[real] could not park the arm ({exc}); release torque with care")
        robot.disconnect()
        print("[real] disconnected (torque released).")


if __name__ == "__main__":
    main()
