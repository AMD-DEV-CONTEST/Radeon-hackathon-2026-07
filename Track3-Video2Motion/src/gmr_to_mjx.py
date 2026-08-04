"""GMR pkl -> MJX 训练用 npz

已验证：GMR 的 g1_mocap_29dof.xml 与 menagerie 的 g1_mjx.xml
关节名、顺序、执行器顺序完全一致，故可直接按下标对接。

输出 npz 字段：
  root_pos   [T,3]   基座位置
  root_quat  [T,4]   基座四元数 (w,x,y,z)
  joint_pos  [T,29]  关节角，顺序 = MJX 模型关节顺序
  fps        标量
"""

import argparse
import pickle

import mujoco
import numpy as np


def load_gmr(pkl_path):
    d = pickle.load(open(pkl_path, "rb"))
    return (
        np.asarray(d["root_pos"], dtype=np.float64),
        np.asarray(d["root_rot"], dtype=np.float64),
        np.asarray(d["dof_pos"], dtype=np.float64),
        int(d["fps"]),
    )


def mjx_joint_names(xml_path):
    m = mujoco.MjModel.from_xml_path(xml_path)
    names = []
    for i in range(m.njnt):
        if m.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE:
            continue
        names.append(mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i))
    return names, m


def resample(arr, src_fps, tgt_fps, is_quat=False):
    """线性重采样。四元数用线性插值后归一化（相邻帧小角度差下足够精确）。"""
    T = arr.shape[0]
    dur = T / src_fps
    T_new = int(round(dur * tgt_fps))

    t_src = np.linspace(0.0, dur, T, endpoint=False)
    t_tgt = np.linspace(0.0, dur, T_new, endpoint=False)

    out = np.stack(
        [np.interp(t_tgt, t_src, arr[:, i]) for i in range(arr.shape[1])], axis=1
    )
    if is_quat:
        out /= np.linalg.norm(out, axis=1, keepdims=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmr_pkl", required=True)
    ap.add_argument("--mjx_xml", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tgt_fps", type=float, default=50.0)
    args = ap.parse_args()

    root_pos, root_quat, dof_pos, src_fps = load_gmr(args.gmr_pkl)
    print(f"[load] {args.gmr_pkl}")
    print(f"  frames={root_pos.shape[0]}  fps={src_fps}  joints={dof_pos.shape[1]}")

    names, m = mjx_joint_names(args.mjx_xml)
    print(f"[mjx] joints={len(names)}  nq={m.nq}  nu={m.nu}")

    if dof_pos.shape[1] != len(names):
        raise SystemExit(
            f"关节数不匹配: GMR={dof_pos.shape[1]} vs MJX={len(names)}"
        )

    norms = np.linalg.norm(root_quat, axis=1)
    print(f"[check] quaternion norm min={norms.min():.4f} max={norms.max():.4f}")
    if not np.allclose(norms, 1.0, atol=1e-3):
        print("  WARN quaternions not unit-norm; normalising")
        root_quat = root_quat / norms[:, None]

    # 🔴 关键：GMR 的 root_rot 是 xyzw（标量在后）
    #    MuJoCo 的 qpos[3:7] 要 wxyz（标量在前），必须换序
    #    实测依据：按 wxyz 解释时机体 z 轴指向世界 +Y（机器人躺着），
    #             按 xyzw 解释才指向世界 +Z（站立）
    print("[reorder] root_rot: xyzw -> wxyz (MuJoCo convention)")
    root_quat = root_quat[:, [3, 0, 1, 2]]

    # 换序后自检：站立时机体 z 轴应接近世界 +z
    w, x, y, z = root_quat[0]
    body_z = np.array([2 * (x * z + w * y),
                       2 * (y * z - w * x),
                       1 - 2 * (x * x + y * y)])
    print(f"  body z-axis in world frame, first frame = {np.round(body_z, 3)}")
    if body_z[2] < 0.8:
        print("  WARN body z-axis does not point up; orientation may still be wrong")
    else:
        print("  OK orientation is upright")

    # 关节限位检查
    lo, hi = [], []
    for i in range(m.njnt):
        if m.jnt_type[i] == mujoco.mjtJoint.mjJNT_FREE:
            continue
        lo.append(m.jnt_range[i][0])
        hi.append(m.jnt_range[i][1])
    lo, hi = np.array(lo), np.array(hi)

    n_over = int(((dof_pos < lo) | (dof_pos > hi)).sum())
    print(f"[check] samples outside joint limits: {n_over} / {dof_pos.size}")
    if n_over:
        print("  clipping into range")
        dof_pos = np.clip(dof_pos, lo, hi)

    print(f"[resample] {src_fps} -> {args.tgt_fps} fps")
    rp = resample(root_pos, src_fps, args.tgt_fps)
    rq = resample(root_quat, src_fps, args.tgt_fps, is_quat=True)
    jp = resample(dof_pos, src_fps, args.tgt_fps)

    # 平移到 xy 原点起步，训练时更好泛化
    rp[:, :2] -= rp[0, :2]

    # 🔴 贴地校正：让整段轨迹里最低的脚底刚好落在 z=0
    #    不做的话机器人起步悬空，落地冲击会把本就偏软的脚踝(kp=20)压屈
    d_probe = mujoco.MjData(m)
    min_clear = 1e9
    for t in range(0, rp.shape[0], max(1, rp.shape[0] // 60)):
        d_probe.qpos[0:3] = rp[t]
        d_probe.qpos[3:7] = rq[t]
        d_probe.qpos[7:] = jp[t]
        mujoco.mj_forward(m, d_probe)
        zs = [d_probe.geom_xpos[i][2] for i in range(m.ngeom)
              if m.geom_type[i] != mujoco.mjtGeom.mjGEOM_PLANE]
        min_clear = min(min_clear, min(zs))
    print(f"[ground] lowest sole z = {min_clear:+.4f}; shifting whole trajectory")
    rp[:, 2] -= min_clear

    np.savez(
        args.out,
        root_pos=rp.astype(np.float32),
        root_quat=rq.astype(np.float32),
        joint_pos=jp.astype(np.float32),
        fps=np.float32(args.tgt_fps),
        joint_names=np.array(names),
    )
    print(f"[save] {args.out}")
    print(f"  frames={rp.shape[0]}  duration={rp.shape[0]/args.tgt_fps:.2f}s")
    print(f"  root_z range=[{rp[:,2].min():.3f}, {rp[:,2].max():.3f}]")
    print(f"  joint angle range=[{jp.min():.3f}, {jp.max():.3f}]")


if __name__ == "__main__":
    main()
