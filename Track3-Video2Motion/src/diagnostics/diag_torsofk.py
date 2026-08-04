"""校验 deploy_track.TorsoFK：只用 SDK 能拿到的量，能不能算准躯干姿态和角速度？

真值来自完整仿真状态（xquat[torso] 和 gyro_torso 传感器）。
FK 的输入只有：pelvis 四元数、29 个关节角、pelvis 角速度、29 个关节速度 ——
全是 LowState 里有的。
"""
import sys
from pathlib import Path

import mujoco
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from deploy_track import TorsoFK, qconj, qmul  # noqa: E402

from mujoco_playground._src.locomotion.g1 import base, g1_constants as C  # noqa: E402

m = mujoco.MjModel.from_xml_string(
    Path(C.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
d = mujoco.MjData(m)
fk = TorsoFK()

pel = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
tor = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, "torso_link")


def sens(name):
    i = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SENSOR, name)
    a = m.sensor_adr[i]
    return d.sensordata[a:a + m.sensor_dim[i]].copy()


ref = np.load(str(C.MOTIONS_BM) + "/salute.npz")
rng = np.random.default_rng(0)

print(f"{'frame':>6} {'|dquat| deg':>12} {'|dgyro| rad/s':>15}  {'waist angles (deg)'}")
print("-" * 74)
eq, eg = [], []
for t in range(0, 150, 15):
    # 随机一个非平凡状态：参考姿态 + 扰动，腰关节故意给大角度
    q = ref["joint_pos"][t] + rng.uniform(-0.15, 0.15, 29)
    q[12:15] += rng.uniform(-0.5, 0.5, 3)          # waist yaw/roll/pitch
    dq = ref["joint_vel"][t] + rng.uniform(-1.0, 1.0, 29)
    d.qpos[0:3] = [0, 0, 0.79]
    d.qpos[3:7] = ref["root_quat"][t]
    d.qpos[7:] = q
    d.qvel[0:3] = rng.uniform(-.3, .3, 3)
    d.qvel[3:6] = rng.uniform(-.8, .8, 3)          # pelvis body-frame ang vel
    d.qvel[6:] = dq
    mujoco.mj_forward(m, d)

    truth_q = d.xquat[tor].copy()
    truth_g = sens("gyro_torso")

    # FK 只拿 SDK 能给的：pelvis 四元数(=xquat[pelvis])、q、pelvis gyro、dq
    est_q, est_g = fk(d.xquat[pel].copy(), q, sens("gyro_pelvis"), dq)

    r = qmul(est_q, qconj(truth_q))
    ang = np.degrees(2 * np.arccos(np.clip(abs(r[0]), 0, 1)))
    dg = np.linalg.norm(est_g - truth_g)
    eq.append(ang)
    eg.append(dg)
    print(f"{t:>6} {ang:>12.4f} {dg:>15.4f}  "
          f"{np.round(np.degrees(q[12:15]), 1)}")

print("-" * 74)
print(f"{'mean':>6} {np.mean(eq):>12.4f} {np.mean(eg):>15.4f}")
print(f"{'max':>6} {np.max(eq):>12.4f} {np.max(eg):>15.4f}")
print()
print("Pass: orientation error < 0.01 deg and angular-rate error < 0.05 rad/s.")
print("Anything larger means the FK frame or velocity convention is wrong.")
