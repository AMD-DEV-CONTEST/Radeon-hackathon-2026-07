"""Layer 2: run the trained policy with **pure NumPy inference** inside the
native MuJoCo C engine — no JAX, no MJX, no brax.

Why this matters: layer 1 (the side-by-side video) runs the policy inside the
very same MJX environment it was trained in. If anything about that environment
is wrong, layer 1 cannot reveal it. Layer 2 swaps out both the physics engine
(MJX/JAX -> MuJoCo C) and the inference stack (brax -> NumPy), so only the
policy itself carries over.

Usage:
    MUJOCO_GL=egl python layer2_numpy.py \
        --params output/train/bm_tennis/params_best \
        --motion motions_bm/tennis.npz \
        --out    output/render/layer2_tennis.mp4
"""

import argparse
import sys
import json
import subprocess
from pathlib import Path

import mujoco
import numpy as np


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


sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

BASE = C.SRC
ANCHOR = "torso_link"
BODY_NAMES = [
    "pelvis",
    "left_hip_roll_link", "left_knee_link", "left_ankle_roll_link",
    "right_hip_roll_link", "right_knee_link", "right_ankle_roll_link",
    "torso_link",
    "left_shoulder_roll_link", "left_elbow_link", "left_wrist_yaw_link",
    "right_shoulder_roll_link", "right_elbow_link", "right_wrist_yaw_link",
]
EE = ["left_ankle_roll_link", "right_ankle_roll_link",
      "left_wrist_yaw_link", "right_wrist_yaw_link"]


# ───────────────────────────── quaternion helpers (numpy)
def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([w1*w2 - x1*x2 - y1*y2 - z1*z2,
                     w1*x2 + x1*w2 + y1*z2 - z1*y2,
                     w1*y2 - x1*z2 + y1*w2 + z1*x2,
                     w1*z2 + x1*y2 - y1*x2 + z1*w2])


def qconj(q):
    return np.array([q[0], -q[1], -q[2], -q[3]])


def qrot(q, v):
    qv = q[1:4]
    t = 2.0 * np.cross(qv, v)
    return v + q[0] * t + np.cross(qv, t)


def qrot_inv(q, v):
    return qrot(qconj(q), v)


def yaw_quat(q):
    yaw = np.arctan2(2*(q[0]*q[3] + q[1]*q[2]), 1 - 2*(q[2]**2 + q[3]**2))
    h = yaw / 2
    return np.array([np.cos(h), 0.0, 0.0, np.sin(h)])


def quat_err(a, b):
    r = qmul(a, qconj(b))
    return 2.0 * np.arccos(np.clip(abs(r[0]), 0.0, 1.0))


def mat2col(q):
    w, x, y, z = q
    c0 = np.array([1 - 2*(y*y + z*z), 2*(x*y + w*z), 2*(x*z - w*y)])
    c1 = np.array([2*(x*y - w*z), 1 - 2*(x*x + z*z), 2*(y*z + w*x)])
    return np.concatenate([c0, c1])


# ───────────────────────────── pure-numpy policy
class NumpyPolicy:
    """4-layer MLP with swish, tanh-squashed mean. Zero JAX dependency."""

    def __init__(self, npz):
        d = np.load(npz)
        self.mean = d["norm_mean"]
        self.std = d["norm_std"]
        self.W = [d[f"w{i}"] for i in range(int(d["n_layers"]))]
        self.b = [d[f"b{i}"] for i in range(int(d["n_layers"]))]

    @staticmethod
    def _swish(x):
        return x / (1.0 + np.exp(-x))

    def __call__(self, obs):
        x = (obs - self.mean) / self.std
        for i in range(len(self.W) - 1):
            x = self._swish(x @ self.W[i] + self.b[i])
        out = x @ self.W[-1] + self.b[-1]
        return np.tanh(out[: out.shape[-1] // 2])      # mean of the Gaussian


def export_numpy(params_dir: Path, out_npz: Path):
    """brax checkpoint -> plain .npz (runs once, needs JAX only here)."""
    from orbax import checkpoint as ocp
    raw = ocp.PyTreeCheckpointer().restore(params_dir.absolute())
    items = [raw[k] for k in sorted(raw.keys())] if isinstance(raw, dict) else list(raw)
    norm, policy = items[0], items[1]

    mean = np.asarray(norm["mean"]["state"])
    std = np.asarray(norm["std"]["state"])

    layers = policy["params"] if "params" in policy else policy
    keys = sorted(layers.keys(), key=lambda k: int("".join(filter(str.isdigit, k)) or 0))
    out = {"norm_mean": mean, "norm_std": std, "n_layers": len(keys)}
    for i, k in enumerate(keys):
        out[f"w{i}"] = np.asarray(layers[k]["kernel"])
        out[f"b{i}"] = np.asarray(layers[k]["bias"])
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_npz, **out)
    n = sum(v.size for k, v in out.items() if k.startswith(("w", "b")))
    print(f"[export] {out_npz}  {len(keys)} layers, {n:,} parameters, "
          f"obs dim {mean.shape[0]}")
    return out_npz


# ───────────────────────────── main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True)
    ap.add_argument("--motion", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--action_scale", type=float, default=0.5)
    ap.add_argument("--steps", type=int, default=0)
    args = ap.parse_args()

    name = Path(args.motion).stem
    npz = C.DEPLOY_OUT / f"track_{name}.npz"
    export_numpy(Path(args.params), npz)
    pol = NumpyPolicy(npz)

    # native MuJoCo, same XML the env used
    from mujoco_playground._src.locomotion.g1 import base, g1_constants as consts
    m = mujoco.MjModel.from_xml_string(
        Path(consts.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
    m.opt.timestep = 0.002
    d = mujoco.MjData(m)
    print(f"[sim] native MuJoCo (C engine), sim_dt={m.opt.timestep}, "
          f"nq={m.nq} nu={m.nu}")

    ref = np.load(args.motion)
    T = ref["joint_pos"].shape[0]
    bid = [mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in BODY_NAMES]
    a_i = BODY_NAMES.index(ANCHOR)
    ee_i = [BODY_NAMES.index(n) for n in EE]
    pel = BODY_NAMES.index("pelvis")
    default_pose = m.keyframe("home").qpos[7:].copy()
    gyro_adr = m.sensor_adr[mujoco.mj_name2id(
        m, mujoco.mjtObj.mjOBJ_SENSOR, "gyro_torso")]

    # start exactly on reference frame 0
    d.qpos[0:3] = ref["root_pos"][0]
    d.qpos[3:7] = ref["root_quat"][0]
    d.qpos[7:] = ref["joint_pos"][0]
    d.qvel[0:3] = ref["body_lin_vel_w"][0, pel]
    d.qvel[3:6] = qrot_inv(ref["root_quat"][0], ref["body_ang_vel_w"][0, pel])
    d.qvel[6:] = ref["joint_vel"][0]
    mujoco.mj_forward(m, d)

    last_act = np.zeros(m.nu)
    total = args.steps or (T - 1)
    frames, errs = [], []
    alive = 0

    for t in range(total):
        idx = min(t + 1, T - 1)
        r_pos = np.stack([d.xpos[b] for b in bid])
        r_quat = np.stack([d.xquat[b] for b in bid])
        ra_pos, ra_quat = r_pos[a_i], r_quat[a_i]
        fa_pos = ref["body_pos_w"][idx, a_i]
        fa_quat = ref["body_quat_w"][idx, a_i]

        # 154 维 —— 与 g1_track._get_obs 逐项对齐。
        # 没有 anchor_pos_b：它需要躯干世界位置，真机拿不到。
        obs = np.concatenate([
            ref["joint_pos"][idx], ref["joint_vel"][idx],          # 58
            mat2col(qmul(qconj(ra_quat), fa_quat)),                # 6
            d.sensordata[gyro_adr:gyro_adr + 3],                   # 3
            d.qpos[7:] - default_pose,                             # 29
            d.qvel[6:],                                            # 29
            last_act,                                              # 29
        ]).astype(np.float32)

        act = pol(obs)
        d.ctrl[:] = ref["joint_pos"][idx] + act * args.action_scale
        for _ in range(10):                                        # ctrl_dt 0.02
            mujoco.mj_step(m, d)
        last_act = act
        alive = t + 1

        # same alignment the reward uses, so the numbers are comparable
        r_pos = np.stack([d.xpos[b] for b in bid])
        r_quat = np.stack([d.xquat[b] for b in bid])
        dq_ = yaw_quat(qmul(r_quat[a_i], qconj(fa_quat)))
        dp = np.array([r_pos[a_i][0], r_pos[a_i][1], fa_pos[2]])
        rel = dp + np.stack([qrot(dq_, p - fa_pos)
                             for p in ref["body_pos_w"][idx]])
        errs.append(np.linalg.norm(rel - r_pos, axis=-1).mean())
        frames.append(d.qpos.copy())

        # BeyondMimic termination thresholds
        if (abs(fa_pos[2] - r_pos[a_i][2]) > 0.25
                or abs(qrot_inv(fa_quat, np.array([0, 0, -1.]))[2]
                       - qrot_inv(r_quat[a_i], np.array([0, 0, -1.]))[2]) > 0.8
                or np.any(np.abs(rel[ee_i, 2] - r_pos[ee_i, 2]) > 0.25)):
            break

    print()
    print(f"{'Layer 2  native MuJoCo + NumPy inference':<46}")
    print("-" * 62)
    print(f"{'Motion completed':<26}{alive:>6}/{total} "
          f"({alive/total*100:5.1f}%)")
    print(f"{'Body position error':<26}{np.mean(errs):>13.4f} m")

    if args.out:
        W = H = 640
        m.vis.global_.offwidth = max(m.vis.global_.offwidth, W * 2)
        m.vis.global_.offheight = max(m.vis.global_.offheight, H)
        r = mujoco.Renderer(m, height=H, width=W)
        cam = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(cam)
        cam.distance, cam.elevation = 3.0, -8
        cam.azimuth = front_azimuth(ref['root_quat'][0])
        dd = mujoco.MjData(m)

        def draw(q):
            dd.qpos[:] = q
            dd.qvel[:] = 0
            mujoco.mj_forward(m, dd)
            cam.lookat[:] = [q[0], q[1], 0.8]
            r.update_scene(dd, camera=cam)
            return r.render().astype(np.uint8)

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-s", f"{W*2}x{H}", "-r", "25", "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", args.out],
            stdin=subprocess.PIPE)
        for k in range(0, len(frames), 2):
            i = min(k + 1, T - 1)
            rq = np.concatenate([ref["root_pos"][i], ref["root_quat"][i],
                                 ref["joint_pos"][i]])
            p.stdin.write(np.hstack([draw(rq), draw(frames[k])]).tobytes())
        p.stdin.close()
        p.wait()
        print(f"{'Video':<26}{args.out}")


if __name__ == "__main__":
    main()
