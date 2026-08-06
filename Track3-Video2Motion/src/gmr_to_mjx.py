"""GMR pkl -> npz for MJX training.

Verified: GMR's g1_mocap_29dof.xml and menagerie's g1_mjx.xml agree exactly on
joint names, joint order and actuator order, so the two can be matched by index.

Fields written:
  root_pos   [T,3]   base position
  root_quat  [T,4]   base quaternion (w,x,y,z)
  joint_pos  [T,29]  joint angles, in the MJX model's joint order
  fps        scalar
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
    """Linear resampling. Quaternions are lerped and renormalised, which is
    accurate enough for the small angles between adjacent frames."""
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
            f"joint count mismatch: GMR={dof_pos.shape[1]} vs MJX={len(names)}"
        )

    norms = np.linalg.norm(root_quat, axis=1)
    print(f"[check] quaternion norm min={norms.min():.4f} max={norms.max():.4f}")
    if not np.allclose(norms, 1.0, atol=1e-3):
        print("  WARN quaternions not unit-norm; normalising")
        root_quat = root_quat / norms[:, None]

    # GMR's root_rot is xyzw (scalar last); MuJoCo's qpos[3:7] expects wxyz
    # (scalar first), so the order has to be swapped. The evidence: read as
    # wxyz, the body z axis points along world +Y and the robot lies down;
    # read as xyzw it points along world +Z and the robot stands.
    print("[reorder] root_rot: xyzw -> wxyz (MuJoCo convention)")
    root_quat = root_quat[:, [3, 0, 1, 2]]

    # Sanity check after swapping: standing, body z should be close to world +z.
    w, x, y, z = root_quat[0]
    body_z = np.array([2 * (x * z + w * y),
                       2 * (y * z - w * x),
                       1 - 2 * (x * x + y * y)])
    print(f"  body z-axis in world frame, first frame = {np.round(body_z, 3)}")
    if body_z[2] < 0.8:
        print("  WARN body z-axis does not point up; orientation may still be wrong")
    else:
        print("  OK orientation is upright")

    # Joint-limit check.
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

    # Start at the xy origin, which generalises better during training.
    rp[:, :2] -= rp[0, :2]

    # Ground alignment: shift so the lowest sole across the whole trajectory
    # sits exactly at z=0. Without it the robot starts in the air, and the
    # landing impact buckles the already-soft ankles (kp=20).
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
