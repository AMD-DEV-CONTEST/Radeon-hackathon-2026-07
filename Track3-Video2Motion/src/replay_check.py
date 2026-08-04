"""纯运动学回放自检：把参考轨迹直接写进 qpos 渲染，不跑物理。

目的：肉眼确认关节映射和符号约定是否正确。
如果视频里的动作和原始人类动作一致，说明桥接层没问题。

视频写出走 ffmpeg 管道，不依赖 imageio / cv2。
"""

import argparse
import subprocess

import mujoco
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", required=True)
    ap.add_argument("--motion", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    args = ap.parse_args()

    m = mujoco.MjModel.from_xml_path(args.xml)
    d = mujoco.MjData(m)

    ref = np.load(args.motion)
    root_pos = ref["root_pos"]
    root_quat = ref["root_quat"]
    joint_pos = ref["joint_pos"]
    fps = float(ref["fps"])
    T = root_pos.shape[0]

    print(f"frames={T}  fps={fps}")
    print(f"model nq={m.nq}  reference joints={joint_pos.shape[1]}")

    expected_nq = 7 + joint_pos.shape[1]
    if m.nq != expected_nq:
        print(f"WARN nq mismatch: model {m.nq}, reference implies {expected_nq}")

    renderer = mujoco.Renderer(m, height=args.height, width=args.width)

    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultCamera(cam)
    cam.distance = 3.5
    cam.elevation = -15
    cam.azimuth = 135

    # 原始 RGB 帧直接管道喂给 ffmpeg
    proc = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{args.width}x{args.height}",
            "-r", str(int(fps)),
            "-i", "-",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            args.out,
        ],
        stdin=subprocess.PIPE,
    )

    for t in range(T):
        d.qpos[0:3] = root_pos[t]
        d.qpos[3:7] = root_quat[t]
        d.qpos[7:] = joint_pos[t]

        # 只算前向运动学，不推进物理
        mujoco.mj_forward(m, d)

        cam.lookat[:] = d.qpos[0:3]
        renderer.update_scene(d, camera=cam)
        proc.stdin.write(renderer.render().astype(np.uint8).tobytes())

        if t % 50 == 0:
            print(f"  rendering {t}/{T}", flush=True)

    proc.stdin.close()
    proc.wait()
    print(f"OK  saved {args.out}")


if __name__ == "__main__":
    main()
