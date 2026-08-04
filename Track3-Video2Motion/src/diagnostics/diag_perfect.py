"""完美跟踪者检验。

把机器人状态**精确**设成参考轨迹的某一帧，此时所有跟踪奖励都应该接近 1。
任何一项明显偏离 1，就说明该项的坐标系/参考点/单位约定还有 bug ——
在这种状态下策略再好也拿不到分，训练必然跑偏。
"""
import sys
from pathlib import Path

import jax
import jax.numpy as jp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import g1_track  # noqa: E402
from g1_track import BODY_NAMES, quat_rotate_inv  # noqa: E402
from mujoco_playground._src import mjx_env  # noqa: E402
from mujoco import mjx  # noqa: E402

MOTION = sys.argv[1] if len(sys.argv) > 1 else "motions_bm/tennis.npz"
env = g1_track.G1Track(MOTION)
ref_np = np.load(MOTION)
pel = BODY_NAMES.index("pelvis")


def probe(t):
    ref = env._ref_at(t)
    root_pos = ref["root_pos"]
    root_quat = ref["root_quat"]
    lin = ref["body_linvel"][pel]
    ang_w = ref["body_angvel"][pel]
    ang_b = quat_rotate_inv(root_quat, ang_w)

    qpos = jp.concatenate([root_pos, root_quat, ref["joint_pos"]])
    qvel = jp.concatenate([lin, ang_b, ref["joint_vel"]])
    data = mjx_env.make_data(
        env.mj_model, qpos=qpos, qvel=qvel, ctrl=ref["joint_pos"],
        impl=env.mjx_model.impl.value,
        naconmax=env._config.naconmax, njmax=env._config.njmax)
    data = mjx.forward(env.mjx_model, data)

    b_pos, b_quat, b_lin, b_ang = env._robot_bodies(data)
    rp, rq = b_pos[env._anchor_local], b_quat[env._anchor_local]
    pos_rel, quat_rel, _ = env._align_ref(ref, rp, rq)
    _, terms, errs = env._reward(ref, pos_rel, quat_rel, b_pos, b_quat,
                                 b_lin, b_ang, data,
                                 jp.zeros(29), jp.zeros(29))
    # 逐 body 的角速度误差
    e_ang = jp.linalg.norm(ref["body_angvel"] - b_ang, axis=-1)
    e_lin = jp.linalg.norm(ref["body_linvel"] - b_lin, axis=-1)
    return terms, errs, np.asarray(e_ang), np.asarray(e_lin)


print(f"{'帧':>5} " + " ".join(f"{k.replace('r_',''):>13}" for k in
      ["r_anchor_pos", "r_anchor_ori", "r_body_pos", "r_body_ori",
       "r_body_lin_vel", "r_body_ang_vel"]))
print("-" * 90)
for t in (0, 50, 100, 150, 200, 250):
    terms, errs, ea, el = probe(t)
    print(f"{t:>5} " + " ".join(
        f"{float(terms[k]):>13.4f}" for k in
        ["r_anchor_pos", "r_anchor_ori", "r_body_pos", "r_body_ori",
         "r_body_lin_vel", "r_body_ang_vel"]))

print()
terms, errs, ea, el = probe(100)
print("第 100 帧，逐 body 速度误差（完美状态下应≈0）：")
print(f"{'body':<26} {'|Δang| rad/s':>13} {'|Δlin| m/s':>12} {'参考|ang|':>11}")
for k, n in enumerate(BODY_NAMES):
    print(f"{n:<26} {ea[k]:>13.4f} {el[k]:>12.4f} "
          f"{np.linalg.norm(ref_np['body_ang_vel_w'][100, k]):>11.4f}")
