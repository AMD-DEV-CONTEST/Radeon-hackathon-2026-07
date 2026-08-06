"""Headless recording version of unitree_mujoco.

The upstream simulate_python/unitree_mujoco.py requires an interactive GLFW
window:
  * containers and servers need X11 or Xvfb configured;
  * under Xvfb with software GL the window often fails to redraw, and x11grab
    captures frozen frames;
  * the render and physics threads contend for one lock, so the real-time
    factor is unstable.

This version drops the interactive window and renders offscreen through EGL
straight to mp4. The DDS bridge behaves exactly as before. Suitable for CI,
batch evaluation, and feeding video to a web front end.

Usage:
    MUJOCO_GL=egl python unitree_mujoco_headless.py --out run.mp4 --seconds 15
"""
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from unitree_sdk2py_bridge import UnitreeSdk2Bridge  # noqa: E402
from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # noqa: E402


def front_azimuth(root_quat, offset=45.0):
    """Camera azimuth, in degrees, for a three-quarter front view derived from
    the root quaternion.

    A hardcoded azimuth breaks whenever the motion faces a different way — in
    this project it once filmed an entire clip from behind.
    """
    import numpy as _np
    w, x, y, z = root_quat
    # Direction of the body +x axis in world coordinates.
    fwd = _np.array([1 - 2 * (y * y + z * z),
                     2 * (x * y + w * z),
                     2 * (x * z - w * y)])
    facing = _np.degrees(_np.arctan2(fwd[1], fwd[0]))
    return facing + 180.0 + offset


ap = argparse.ArgumentParser()
ap.add_argument("--out", default="headless.mp4")
ap.add_argument("--seconds", type=float, default=15.0)
ap.add_argument("--fps", type=int, default=25)
ap.add_argument("--width", type=int, default=960)
ap.add_argument("--height", type=int, default=720)
ap.add_argument("--wait_cmd", type=float, default=60.0,
                help="max seconds to wait for the controller before giving up")
ap.add_argument("--init_motion", default=None,
                help="start from the motion first frame instead of the generic keyframe")
args = ap.parse_args()

mj_model = mujoco.MjModel.from_xml_path(config.ROBOT_SCENE)
mj_data = mujoco.MjData(mj_model)
mj_model.opt.timestep = config.SIMULATE_DT

if args.init_motion:
    # Start from the motion's first frame. Unitree's generic stand keyframe can
    # differ from it by tens of degrees, while the policy was only trained with
    # RSI perturbations of +/-0.1 rad, so the generic keyframe drops the policy
    # straight into a state it has never seen.
    _ref = np.load(args.init_motion)
    mj_data.qpos[0:3] = _ref["root_pos"][0]
    mj_data.qpos[3:7] = _ref["root_quat"][0]
    mj_data.qpos[7:] = _ref["joint_pos"][0]
    mj_data.qvel[:] = 0.0
    print(f"[init] motion first frame, base_z={mj_data.qpos[2]:.4f} "
          f"({args.init_motion})", flush=True)
elif mj_model.nkey > 0:
    mujoco.mj_resetDataKeyframe(mj_model, mj_data, 0)
    print(f"[init] stand keyframe, base_z={mj_data.qpos[2]:.4f}", flush=True)
mujoco.mj_forward(mj_model, mj_data)

# The offscreen framebuffer defaults to 640x480, and exceeding it raises an
# error telling you to edit <visual><global offwidth> in the XML. Set the model
# field at runtime instead, so no third-party XML has to be touched.
mj_model.vis.global_.offwidth = max(mj_model.vis.global_.offwidth, args.width)
mj_model.vis.global_.offheight = max(mj_model.vis.global_.offheight, args.height)

locker = threading.Lock()
stop = threading.Event()

ChannelFactoryInitialize(config.DOMAIN_ID, config.INTERFACE)
bridge = UnitreeSdk2Bridge(mj_model, mj_data)
print("[init] DDS bridge ready, waiting for the controller...", flush=True)


def simulation_thread():
    # Do not advance the physics until the controller connects. With no LowCmd
    # the bridge applies zero torque, so stepping early leaves the robot lying
    # on the floor before the run even begins.
    while not bridge._cmd_ready and not stop.is_set():
        time.sleep(0.01)
    while not stop.is_set():
        t0 = time.perf_counter()
        with locker:
            bridge.ApplyPD()          # recompute PD every physics step, as the
                                      # real motor drivers do
            mujoco.mj_step(mj_model, mj_data)
        dt = mj_model.opt.timestep - (time.perf_counter() - t0)
        if dt > 0:
            time.sleep(dt)


def record_thread():
    # Wait for the controller's first LowCmd before recording, so the clip does
    # not open on a motionless startup screen.
    t_wait = time.perf_counter()
    while not bridge._cmd_ready:
        if time.perf_counter() - t_wait > args.wait_cmd:
            print("[rec] no LowCmd received; giving up on recording", flush=True)
            stop.set()
            return
        time.sleep(0.05)
    print("[rec] controller connected; recording", flush=True)

    r = mujoco.Renderer(mj_model, height=args.height, width=args.width)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance, cam.elevation = 3.2, -10
    cam.azimuth = (front_azimuth(_ref['root_quat'][0])
                   if args.init_motion else 135.0)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-s", f"{args.width}x{args.height}",
         "-r", str(args.fps), "-i", "-", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", args.out],
        stdin=subprocess.PIPE)

    n = int(args.seconds * args.fps)
    period = 1.0 / args.fps
    t_next = time.perf_counter()
    for _ in range(n):
        with locker:
            cam.lookat[:] = [mj_data.qpos[0], mj_data.qpos[1], 0.65]
            r.update_scene(mj_data, camera=cam)
        proc.stdin.write(r.render().astype(np.uint8).tobytes())
        t_next += period
        d = t_next - time.perf_counter()
        if d > 0:
            time.sleep(d)

    proc.stdin.close()
    proc.wait()
    # Close the renderer while the interpreter is still whole. Leaving it
    # to __del__ runs the EGL teardown after module globals have been
    # cleared, which prints 'Exception ignored ... TypeError: NoneType
    # object is not callable' — alarming in a log, and harmless only if
    # you already know that.
    r.close()
    print(f"[rec] written {args.out}", flush=True)
    stop.set()


ts = threading.Thread(target=simulation_thread, daemon=True)
tr = threading.Thread(target=record_thread, daemon=True)
ts.start()
tr.start()
tr.join()
stop.set()
ts.join(timeout=2)
print(f"[done] sim_time={mj_data.time:.2f}s  base_z={mj_data.qpos[2]:.3f}", flush=True)
