"""Side-by-side live view of the REAL cameras against the SIM renderings.

The policy was trained on sim images, so the closer the real camera framing is to
the sim camera framing, the smaller the visual domain gap. This tool renders the
sim scene once (arm held at the demo home pose) and then streams the real cameras
next to it, so the physical rig can be nudged until the two line up.

Panels: [real | sim | 50/50 blend]. The blend makes misalignment obvious — the
table rim, the white target sheet and the gripper should overlap.

    uv run python -m franka_fruit_pick.align_cameras_so101 \
        --port /dev/tty.usbmodem5B7B0147591 --cam-world 0 --cam-wrist 1

Keys (in the OpenCV window): [w] world view, [r] wrist view, [s] save a PNG, [q] quit.
Torque stays ON holding the home pose so the wrist camera sees what it would at
episode start. Pass --no-arm to skip the robot entirely (world camera only).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def sim_reference(width: int, height: int) -> dict:
    """Render the sim world/wrist views with the arm at the demo home pose."""
    import cv2
    import genesis as gs

    from build_scene_so101 import build_scene_so101
    from eval_policy_so101_real import HOME_QPOS

    gs.init(backend=gs.metal)
    bundle = build_scene_so101(show_viewer=False)
    bundle.robot.set_qpos(HOME_QPOS)
    for _ in range(5):
        bundle.robot.set_qpos(HOME_QPOS)
        bundle.scene.step()
        bundle.update_wrist_cam()

    out = {}
    for name, cam in (("world", bundle.world_cam), ("wrist", bundle.wrist_cam)):
        img = cam.render(rgb=True)
        img = np.asarray(img[0] if isinstance(img, tuple) else img, dtype=np.uint8)
        out[name] = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Align the real cameras to the sim views.")
    p.add_argument("--port", default=None, help="Arm serial port (omit with --no-arm).")
    p.add_argument("--robot-id", default="so101_real")
    p.add_argument("--cam-world", type=int, default=None)
    p.add_argument("--cam-wrist", type=int, default=None)
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--no-arm", action="store_true",
                   help="Skip the robot: stream cameras only (no home pose, no wrist view).")
    p.add_argument("--out-dir", default="outputs/cam_align")
    args = p.parse_args()

    import cv2

    print("[align] rendering sim reference views ...")
    sim = sim_reference(args.width, args.height)

    robot = None
    caps: dict = {}
    if args.no_arm:
        for name, idx in (("world", args.cam_world), ("wrist", args.cam_wrist)):
            if idx is not None:
                caps[name] = cv2.VideoCapture(idx)
    else:
        from eval_policy_so101_real import HOME_QPOS, JointBridge, ease_to, make_robot

        robot = make_robot(args.port, args.robot_id, args.cam_world, args.cam_wrist,
                           args.width, args.height, args.fps, max_step_deg=8.0)
        robot.connect()
        bridge = JointBridge()
        print("[align] easing to demo home pose ...")
        ease_to(robot, bridge, HOME_QPOS, seconds=4.0, fps=args.fps)

    view = "world"
    print("[align] keys: w=world  r=wrist  s=save  q=quit")
    try:
        while True:
            if robot is not None:
                raw = robot.get_observation()
                robot.send_action(bridge.to_real(HOME_QPOS))   # keep holding home
                real = raw.get(view)
            else:
                cap = caps.get(view)
                real = None
                if cap is not None:
                    ok, frame = cap.read()
                    real = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ok else None

            if real is None:
                print(f"[align] no real image for {view!r}; press w/r to switch")
                cv2.waitKey(500)
                continue

            real = cv2.resize(np.asarray(real, dtype=np.uint8), (args.width, args.height),
                              interpolation=cv2.INTER_AREA)
            ref = sim[view]
            blend = cv2.addWeighted(real, 0.5, ref, 0.5, 0)
            panel = np.hstack([real, ref, blend])
            cv2.putText(panel, f"{view}: REAL | SIM | BLEND", (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.imshow("camera alignment", cv2.cvtColor(panel, cv2.COLOR_RGB2BGR))

            k = cv2.waitKey(1) & 0xFF
            if k == ord("q"):
                break
            if k == ord("w"):
                view = "world"
            if k == ord("r"):
                view = "wrist"
            if k == ord("s"):
                out = Path(args.out_dir)
                out.mkdir(parents=True, exist_ok=True)
                import imageio.v2 as imageio
                imageio.imwrite(str(out / f"align_{view}.png"), panel)
                print(f"[align] saved {out / f'align_{view}.png'}")
    finally:
        cv2.destroyAllWindows()
        for c in caps.values():
            c.release()
        if robot is not None:
            robot.disconnect()
            print("[align] disconnected (torque released).")


if __name__ == "__main__":
    main()
