"""unitree_mujoco 的无头录制版。

官方 simulate_python/unitree_mujoco.py 强依赖 GLFW 交互窗口：
  * 容器/服务器里必须配 X11 或 Xvfb；
  * Xvfb + 软件 GL 下窗口常常不重绘，x11grab 抓到静止帧；
  * 渲染线程和物理线程抢同一把锁，实时率不稳。

这个版本去掉交互窗口，改用 MuJoCo 离屏渲染（EGL）直接出 mp4，
DDS 桥接层行为完全不变。适合 CI、批量评测，以及把画面送进网页前端。

用法：
    MUJOCO_GL=egl python unitree_mujoco_headless.py --out run.mp4 --seconds 15
"""
import argparse
import subprocess
import sys
import threading
import time

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from unitree_sdk2py_bridge import UnitreeSdk2Bridge  # noqa: E402
from unitree_sdk2py.core.channel import ChannelFactoryInitialize  # noqa: E402
from pathlib import Path


def front_azimuth(root_quat, offset=45.0):
    """从根四元数推出「侧前方」相机方位角（度）。

    写死 azimuth 会随动作朝向变化而失效 —— 本项目就曾拍到整段背面。
    """
    import numpy as _np
    w, x, y, z = root_quat
    # 机体 +x 轴在世界系里的方向
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
                help="等控制端连上的最长秒数；连上才开始计时录制")
ap.add_argument("--init_motion", default=None,
                help="用该动作文件的首帧作为初始状态（而不是通用站立 keyframe）")
args = ap.parse_args()

mj_model = mujoco.MjModel.from_xml_path(config.ROBOT_SCENE)
mj_data = mujoco.MjData(mj_model)
mj_model.opt.timestep = config.SIMULATE_DT

if args.init_motion:
    # 🔴 从参考动作首帧起步。unitree 的通用 stand keyframe 与动作起始姿势
    #    可能差几十度，而策略的 RSI 训练扰动只有 ±0.1 rad ——
    #    用通用 keyframe 等于一上来就把策略丢进没见过的状态。
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

# 离屏渲染画布默认 640x480，超了会报错让你去改 XML 的 <visual><global offwidth>。
# 直接在运行时改模型字段，不用动第三方 XML。
mj_model.vis.global_.offwidth = max(mj_model.vis.global_.offwidth, args.width)
mj_model.vis.global_.offheight = max(mj_model.vis.global_.offheight, args.height)

locker = threading.Lock()
stop = threading.Event()

ChannelFactoryInitialize(config.DOMAIN_ID, config.INTERFACE)
bridge = UnitreeSdk2Bridge(mj_model, mj_data)
print("[init] DDS 桥接就绪，等待控制端…", flush=True)


def simulation_thread():
    # 🔴 控制端连上之前不推进物理。桥接层在没有 LowCmd 时施加零力矩，
    #    先跑物理的话机器人在等待期间就已经躺平了。
    while not bridge._cmd_ready and not stop.is_set():
        time.sleep(0.01)
    while not stop.is_set():
        t0 = time.perf_counter()
        with locker:
            bridge.ApplyPD()          # 每个仿真步重算 PD，对齐真机驱动器
            mujoco.mj_step(mj_model, mj_data)
        dt = mj_model.opt.timestep - (time.perf_counter() - t0)
        if dt > 0:
            time.sleep(dt)


def record_thread():
    # 等控制端下发第一条 LowCmd 再开录，避免录到一段静止的启动画面
    t_wait = time.perf_counter()
    while not bridge._cmd_ready:
        if time.perf_counter() - t_wait > args.wait_cmd:
            print("[rec] 等不到 LowCmd，放弃录制", flush=True)
            stop.set()
            return
        time.sleep(0.05)
    print("[rec] 控制端已连接，开始录制", flush=True)

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
    print(f"[rec] 已写出 {args.out}", flush=True)
    stop.set()


ts = threading.Thread(target=simulation_thread, daemon=True)
tr = threading.Thread(target=record_thread, daemon=True)
ts.start()
tr.start()
tr.join()
stop.set()
ts.join(timeout=2)
print(f"[done] sim_time={mj_data.time:.2f}s  base_z={mj_data.qpos[2]:.3f}", flush=True)
