"""把 GMR 重定向结果补成 BeyondMimic 格式的动作文件。

我们的 npz 只有 root_pos / root_quat / joint_pos。BeyondMimic 的奖励是
在**三维空间**里算的，需要每个 body link 的位置、朝向、线速度、角速度，
以及关节速度。这些全部可以用 MuJoCo 正运动学 + 差分补出来
（BeyondMimic 自己的 csv_to_npz.py 做的也是这件事）。

输出字段：
    fps                 标量
    joint_pos           (T, 29)
    joint_vel           (T, 29)
    body_pos_w          (T, B, 3)
    body_quat_w         (T, B, 4)   wxyz
    body_lin_vel_w      (T, B, 3)
    body_ang_vel_w      (T, B, 3)   世界系
    body_names          (B,)

用法：
    python motion_prep.py --inp motions_mjx/tennis.npz --out motions_bm/tennis.npz
"""

import argparse
from pathlib import Path

import mujoco
import numpy as np

# BeyondMimic 的 G1 配置里跟踪这 14 个 link（flat_env_cfg.py）
BODY_NAMES = [
    "pelvis",
    "left_hip_roll_link",
    "left_knee_link",
    "left_ankle_roll_link",
    "right_hip_roll_link",
    "right_knee_link",
    "right_ankle_roll_link",
    "torso_link",
    "left_shoulder_roll_link",
    "left_elbow_link",
    "left_wrist_yaw_link",
    "right_shoulder_roll_link",
    "right_elbow_link",
    "right_wrist_yaw_link",
]
ANCHOR_BODY = "torso_link"


def load_model(xml):
    from mujoco_playground._src import mjx_env
    xd = Path(xml).parent
    assets = {}
    mjx_env.update_assets(assets, xd)
    mjx_env.update_assets(assets, xd / "assets")
    mjx_env.update_assets(assets, mjx_env.MENAGERIE_PATH / "unitree_g1" / "assets")
    return mujoco.MjModel.from_xml_string(Path(xml).read_text(), assets)


def quat_diff_to_angvel(q0, q1, dt):
    """两帧四元数(wxyz)之差 → 世界系角速度。

    q_rel = q1 * conj(q0)，取其旋转矢量再除以 dt。
    """
    w0, x0, y0, z0 = q0
    w1, x1, y1, z1 = q1
    # conj(q0)
    cw, cx, cy, cz = w0, -x0, -y0, -z0
    # q1 * conj(q0)
    rw = w1 * cw - x1 * cx - y1 * cy - z1 * cz
    rx = w1 * cx + x1 * cw + y1 * cz - z1 * cy
    ry = w1 * cy - x1 * cz + y1 * cw + z1 * cx
    rz = w1 * cz + x1 * cy - y1 * cx + z1 * cw
    if rw < 0.0:                      # 取短弧
        rw, rx, ry, rz = -rw, -rx, -ry, -rz
    n = np.sqrt(rx * rx + ry * ry + rz * rz)
    if n < 1e-9:
        return np.zeros(3)
    angle = 2.0 * np.arctan2(n, rw)
    return (np.array([rx, ry, rz]) / n) * (angle / dt)


def central_diff(x, dt):
    """中心差分，端点用单边差分。x: (T, ...)"""
    v = np.zeros_like(x)
    v[1:-1] = (x[2:] - x[:-2]) / (2.0 * dt)
    v[0] = (x[1] - x[0]) / dt
    v[-1] = (x[-1] - x[-2]) / dt
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", required=True)
    ap.add_argument("--out", required=True)
    from mujoco_playground._src.locomotion.g1 import g1_constants as _c
    ap.add_argument("--xml", default=_c.FEET_ONLY_FLAT_TERRAIN_XML.as_posix())
    args = ap.parse_args()

    d_in = np.load(args.inp)
    joint_pos = d_in["joint_pos"].astype(np.float64)      # (T, 29)
    root_pos = d_in["root_pos"].astype(np.float64)        # (T, 3)
    root_quat = d_in["root_quat"].astype(np.float64)      # (T, 4) wxyz
    fps = float(d_in["fps"])
    dt = 1.0 / fps
    T, nj = joint_pos.shape

    m = load_model(args.xml)
    data = mujoco.MjData(m)
    bids = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in BODY_NAMES]
    missing = [n for n, i in zip(BODY_NAMES, bids) if i < 0]
    if missing:
        raise SystemExit(f"bodies not found in model: {missing}")
    B = len(bids)

    body_pos = np.zeros((T, B, 3))
    body_quat = np.zeros((T, B, 4))

    # ---- 正运动学：逐帧摆好 qpos，读 body 世界位姿 ----
    for t in range(T):
        data.qpos[0:3] = root_pos[t]
        data.qpos[3:7] = root_quat[t]
        data.qpos[7:] = joint_pos[t]
        data.qvel[:] = 0.0
        mujoco.mj_forward(m, data)
        for k, bid in enumerate(bids):
            body_pos[t, k] = data.xpos[bid]
            body_quat[t, k] = data.xquat[bid]

    # ---- 速度：位置用中心差分，姿态用四元数差 ----
    body_lin_vel = central_diff(body_pos, dt)
    body_ang_vel = np.zeros((T, B, 3))
    for k in range(B):
        for t in range(T):
            t0, t1 = max(t - 1, 0), min(t + 1, T - 1)
            span = (t1 - t0) * dt
            if span < 1e-9:
                continue
            body_ang_vel[t, k] = quat_diff_to_angvel(
                body_quat[t0, k], body_quat[t1, k], span)

    joint_vel = central_diff(joint_pos, dt)

    # ---- 贴地：整条轨迹平移，使最低脚踝 link 的最低点落在 z=0 ----
    #      GMR 的输出高度是按人体尺度来的，直接用会悬空或穿模。
    ankle_idx = [BODY_NAMES.index("left_ankle_roll_link"),
                 BODY_NAMES.index("right_ankle_roll_link")]
    # 用第一帧标定脚踝 link 原点到脚底的偏移
    data.qpos[0:3] = root_pos[0]
    data.qpos[3:7] = root_quat[0]
    data.qpos[7:] = joint_pos[0]
    mujoco.mj_forward(m, data)
    sole_off = min(
        min(data.geom_xpos[g][2] for g in range(m.ngeom)
            if m.geom_bodyid[g] == bids[a]) if any(
                m.geom_bodyid[g] == bids[a] for g in range(m.ngeom))
        else data.xpos[bids[a]][2]
        for a in ankle_idx)
    shift = sole_off - 0.0
    body_pos[:, :, 2] -= shift
    root_pos_adj = root_pos.copy()
    root_pos_adj[:, 2] -= shift

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        args.out,
        fps=np.float32(fps),
        joint_pos=joint_pos.astype(np.float32),
        joint_vel=joint_vel.astype(np.float32),
        root_pos=root_pos_adj.astype(np.float32),
        root_quat=root_quat.astype(np.float32),
        body_pos_w=body_pos.astype(np.float32),
        body_quat_w=body_quat.astype(np.float32),
        body_lin_vel_w=body_lin_vel.astype(np.float32),
        body_ang_vel_w=body_ang_vel.astype(np.float32),
        body_names=np.array(BODY_NAMES),
        anchor_body=np.array(ANCHOR_BODY),
    )

    print(f"OK  {args.out}")
    print(f"    {T} frames @ {fps:.1f} fps = {T/fps:.2f}s, {B} tracked bodies")
    print(f"    ground alignment shift {shift:+.4f} m")
    print(f"    root_z       {root_pos_adj[:,2].min():.3f} .. {root_pos_adj[:,2].max():.3f}")
    print(f"    body_z       {body_pos[:,:,2].min():.3f} .. {body_pos[:,:,2].max():.3f}")
    print(f"    |lin_vel|    max {np.linalg.norm(body_lin_vel,axis=-1).max():.2f} m/s")
    print(f"    |ang_vel|    max {np.linalg.norm(body_ang_vel,axis=-1).max():.2f} rad/s")
    print(f"    |joint_vel|  max {np.abs(joint_vel).max():.2f} rad/s")


if __name__ == "__main__":
    main()
