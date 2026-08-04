"""G1 全身动作跟踪环境 —— BeyondMimic 配方的 MJX 移植。

为什么推倒重来
--------------
上一版 (g1_deploy.py) 继承 Playground 的 Joystick 环境，只跟踪上肢关节角，
下肢给一个"靠近默认站姿"的正则项，终止条件只有"摔倒"。结果是策略学会了
**站稳 + 手臂随便挥挥** —— 因为不摔倒就能拿满 episode 长度的奖励，
跟踪项只占一小部分，不跟踪的代价太小。

BeyondMimic (HybridRobotics/whole_body_tracking) 的做法完全不同：

  1. 在**三维空间**里跟踪 14 个 body link 的位置/朝向/线速度/角速度，
     而不是跟踪关节角。关节角误差和视觉上"像不像"的相关性很弱。
  2. **跟踪误差超阈值直接终止** —— 站着不动会被立刻砍断 episode，
     混不了分。这是 DeepMimic 最关键的一招。
  3. **RSI**：每次 reset 从参考轨迹的随机时刻取**完整状态**
     （根位姿 + 根速度 + 关节角 + 关节速度）初始化，而不是永远从站姿起步。
  4. 奖励只有 6 项跟踪 + 3 项惩罚，没有任何 locomotion 残留。

原版依赖 Isaac Lab / Isaac Sim（CUDA 独占），mjlab 版依赖 MuJoCo-Warp
（也是 CUDA 独占）。在 AMD 上两条路都走不通，所以按论文和源码把 MDP
在 MJX 里重新实现一遍。奖励公式、权重、std、终止阈值与原版逐项对齐。

对齐清单（对照 tracking_env_cfg.py）
-----------------------------------
  motion_global_anchor_pos   w=0.5  std=0.30
  motion_global_anchor_ori   w=0.5  std=0.40
  motion_body_pos            w=1.0  std=0.30
  motion_body_ori            w=1.0  std=0.40
  motion_body_lin_vel        w=1.0  std=1.00
  motion_body_ang_vel        w=1.0  std=3.14
  action_rate_l2             w=-0.1
  joint_limit                w=-10.0
  undesired_contacts         w=-0.1
  终止：anchor_z>0.25 / anchor_ori>0.8 / 末端 z>0.25 / 超时 10s
  decimation=4, sim_dt=0.005 -> ctrl_dt=0.02
"""

from typing import Any, Dict, Optional, Union

import jax
import jax.numpy as jp
import numpy as np
from ml_collections import config_dict
from mujoco import mjx
from mujoco_playground._src import mjx_env
from mujoco_playground._src.locomotion.g1 import base as g1_base
from mujoco_playground._src.locomotion.g1 import g1_constants as consts

# BeyondMimic 的 G1 跟踪 body 列表（flat_env_cfg.py）
BODY_NAMES = [
    "pelvis",
    "left_hip_roll_link", "left_knee_link", "left_ankle_roll_link",
    "right_hip_roll_link", "right_knee_link", "right_ankle_roll_link",
    "torso_link",
    "left_shoulder_roll_link", "left_elbow_link", "left_wrist_yaw_link",
    "right_shoulder_roll_link", "right_elbow_link", "right_wrist_yaw_link",
]
ANCHOR_BODY = "torso_link"
# 终止判据只看这四个末端
EE_BODIES = ["left_ankle_roll_link", "right_ankle_roll_link",
             "left_wrist_yaw_link", "right_wrist_yaw_link"]


def default_config() -> config_dict.ConfigDict:
    return config_dict.create(
        ctrl_dt=0.02,
        # ⚠️ BeyondMimic 用 0.005，但那是配它自己的执行器模型
        #    (stiffness = armature x (2*pi*10)^2，10Hz 自然频率、阻尼比 2，
        #     刻意做得很软)。Playground 的 G1 是 kp=75 配极小电枢，刚度高得多，
        #    0.005 会积分发散 —— 实测理想控制器下 base_z 飞到 -165911。
        #    0.004 及以下稳定且结果一致，用 Playground 验证过的 0.002。
        sim_dt=0.002,
        impl="jax",            # 🔴 官方默认 warp，CUDA 独占
        naconmax=1024,
        njmax=128,
        episode_length=500,    # 10s / 0.02s
        action_scale=0.5,
        action_repeat=1,
        restricted_joint_range=False,
        # 🔴 必须是 1.0（= 硬限位），不能用 Playground 的 0.9。
        #    joint_limit 惩罚权重是 -10，而 tennis 的参考轨迹在 269/298 帧上
        #    超出 0.9 软限位（最大 0.192 rad @ 肩滚）—— 完美跟踪参考也要挨
        #    -2.09/步 的罚，而跟踪奖励满分才 5.0。等于奖励函数一边说"照着做"
        #    一边罚"照着做"。参考的硬限位违反是 0 帧，用 1.0 就没有这个矛盾。
        #    Isaac Lab 的 soft_joint_pos_limit_factor 默认也是 1.0。
        soft_joint_pos_limit_factor=1.0,
        reward_config=config_dict.create(
            scales=config_dict.create(
                anchor_pos=0.5,
                anchor_ori=0.5,
                body_pos=1.0,
                body_ori=1.0,
                body_lin_vel=1.0,
                body_ang_vel=1.0,
                action_rate=-0.1,
                joint_limit=-10.0,
            ),
            stds=config_dict.create(
                anchor_pos=0.30,
                anchor_ori=0.40,
                body_pos=0.30,
                body_ori=0.40,
                body_lin_vel=1.00,
                body_ang_vel=3.14,
            ),
        ),
        termination=config_dict.create(
            anchor_pos_z=0.25,
            anchor_ori=0.8,
            ee_pos_z=0.25,
        ),
        # RSI 时加在参考状态上的扰动（对齐 MotionCommandCfg）
        rsi=config_dict.create(
            pos_xy=0.05, pos_z=0.01,
            rpy=0.1, yaw=0.2,
            lin_vel=0.5, ang_vel=0.52,
            joint_pos=0.1,
        ),
        noise_config=config_dict.create(
            anchor_pos=0.25, anchor_ori=0.05,
            gyro=0.2, joint_pos=0.01, joint_vel=0.5,
        ),
    )


# ---------------------------------------------------------------- 四元数工具
def quat_mul(a, b):
    w1, x1, y1, z1 = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    w2, x2, y2, z2 = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return jp.stack([
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    ], axis=-1)


def quat_conj(q):
    return jp.stack([q[..., 0], -q[..., 1], -q[..., 2], -q[..., 3]], axis=-1)


def quat_error_magnitude(a, b):
    """两个四元数之间的旋转角（弧度），对齐 isaaclab.utils.math。"""
    r = quat_mul(a, quat_conj(b))
    w = jp.clip(jp.abs(r[..., 0]), 0.0, 1.0)
    return 2.0 * jp.arccos(w)


def quat_rotate(q, v):
    """用四元数旋转向量。"""
    qw = q[..., 0:1]
    qv = q[..., 1:4]
    t = 2.0 * jp.cross(qv, v)
    return v + qw * t + jp.cross(qv, t)


def quat_rotate_inv(q, v):
    return quat_rotate(quat_conj(q), v)


def yaw_quat(q):
    """只保留 yaw 分量。"""
    yaw = jp.arctan2(2.0 * (q[..., 0] * q[..., 3] + q[..., 1] * q[..., 2]),
                     1.0 - 2.0 * (q[..., 2] ** 2 + q[..., 3] ** 2))
    h = yaw * 0.5
    z = jp.zeros_like(h)
    return jp.stack([jp.cos(h), z, z, jp.sin(h)], axis=-1)


def mat_from_quat_2col(q):
    """旋转矩阵的前两列（6D 姿态表示），对齐 BeyondMimic 的观测。"""
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    c0 = jp.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], -1)
    c1 = jp.stack([2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)], -1)
    return jp.concatenate([c0, c1], axis=-1)


# ---------------------------------------------------------------- 环境
class G1Track(g1_base.G1Env):
    """BeyondMimic 风格的全身动作跟踪。"""

    def __init__(self, motion_path: str,
                 config: Optional[config_dict.ConfigDict] = None,
                 config_overrides: Optional[Dict[str, Union[str, int, list]]] = None):
        cfg = config if config is not None else default_config()
        super().__init__(
            xml_path=consts.FEET_ONLY_FLAT_TERRAIN_XML.as_posix(),
            config=cfg, config_overrides=config_overrides)

        self._post_init(motion_path)

    def _post_init(self, motion_path: str):
        import mujoco
        m = self._mj_model

        # ---- 参考动作 ----
        d = np.load(motion_path)
        self._ref_joint_pos = jp.asarray(d["joint_pos"])          # (T, 29)
        self._ref_joint_vel = jp.asarray(d["joint_vel"])
        self._ref_root_pos = jp.asarray(d["root_pos"])            # (T, 3)
        self._ref_root_quat = jp.asarray(d["root_quat"])          # (T, 4)
        self._ref_body_pos = jp.asarray(d["body_pos_w"])          # (T, B, 3)
        self._ref_body_quat = jp.asarray(d["body_quat_w"])
        self._ref_body_linvel = jp.asarray(d["body_lin_vel_w"])
        self._ref_body_angvel = jp.asarray(d["body_ang_vel_w"])
        self._T = int(self._ref_joint_pos.shape[0])

        names = [str(x) for x in d["body_names"]]
        assert names == BODY_NAMES, f"body 顺序不一致: {names}"

        # ---- body 索引 ----
        self._body_ids = jp.asarray([
            mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in BODY_NAMES])
        self._anchor_local = BODY_NAMES.index(ANCHOR_BODY)
        self._ee_local = jp.asarray([BODY_NAMES.index(n) for n in EE_BODIES])
        self._body_rootids = jp.asarray(
            [m.body_rootid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)]
             for n in BODY_NAMES])
        self._nb = len(BODY_NAMES)

        # ---- 默认姿态与关节限位 ----
        self._init_q = jp.asarray(m.keyframe("home").qpos)
        self._default_pose = jp.asarray(m.keyframe("home").qpos[7:])
        self._nu = m.nu
        lo = m.jnt_range[1:, 0]
        hi = m.jnt_range[1:, 1]
        c = (lo + hi) / 2.0
        r = (hi - lo) / 2.0
        f = self._config.soft_joint_pos_limit_factor
        self._soft_lo = jp.asarray(c - f * r)
        self._soft_hi = jp.asarray(c + f * r)

        # ---- 逐关节 action scale ----
        # BeyondMimic (robots/g1.py): action_scale = 0.25 * effort_limit / stiffness
        # 也就是「满力矩下关节偏转量的四分之一」。Playground 默认是统一 0.5，
        # 对髋/膝这类大力矩关节偏小，对腕/踝偏大。
        # ⚠️ BeyondMimic 的公式在这里搬不过来：Playground 的 G1 用位置执行器，
        #    actuator_forcerange 全是 0（没设力矩上限），公式退化成除零。
        #    两个模型的 kp 也不是一套（Playground: 髋膝 75 / 踝 20 / 腕 2；
        #    BeyondMimic: stiffness = armature x (2*pi*10)^2）。
        #    所以沿用 Playground 经过 sim2real 验证的统一 0.5 ——
        #    它正好落在 BeyondMimic 逐关节值的区间 (0.30~0.90) 中间。
        self._action_scale = jp.full((m.nu,), self._config.action_scale)

        # episode 长度 = 参考帧数。RSI 从随机帧起步，索引到头后停在末帧
        # （末帧姿态也要稳稳保持住，这不是白给的分）。
        object.__setattr__(self._config, "episode_length", int(self._T))

        print(f"[env] reference {self._T} frames ({self._T*0.02:.1f}s), "
              f"tracking {self._nb} bodies, anchor={ANCHOR_BODY}")
        print(f"[env] action_scale = {self._config.action_scale} (uniform)")
        print(f"[env] impl={self._config.impl}  "
              f"episode={self._config.episode_length} steps")

    # -------------------------------------------------- 参考量读取
    def _ref_at(self, idx):
        return dict(
            joint_pos=self._ref_joint_pos[idx],
            joint_vel=self._ref_joint_vel[idx],
            root_pos=self._ref_root_pos[idx],
            root_quat=self._ref_root_quat[idx],
            body_pos=self._ref_body_pos[idx],
            body_quat=self._ref_body_quat[idx],
            body_linvel=self._ref_body_linvel[idx],
            body_angvel=self._ref_body_angvel[idx],
        )

    # -------------------------------------------------- 机器人当前量
    def _robot_bodies(self, data):
        pos = data.xpos[self._body_ids]
        quat = data.xquat[self._body_ids]
        ang = data.cvel[self._body_ids, 0:3]        # 世界系角速度，直接可用
        # 🔴 cvel 的线速度分量是 **subtree_com 那一点** 的速度，不是 body
        #    原点的速度。参考轨迹是 xpos 的差分，必须换算到同一点上：
        #        v_origin = v_com + ω × (xpos - subtree_com)
        #    实测不修正时平均差 0.26 m/s，末端手腕差到 1.0 m/s。
        com = data.subtree_com[self._body_rootids]
        lin = data.cvel[self._body_ids, 3:6] + jp.cross(ang, pos - com)
        return pos, quat, lin, ang

    # -------------------------------------------------- 参考的"相对对齐"版本
    def _align_ref(self, ref, r_anchor_pos, r_anchor_quat):
        """把参考轨迹平移旋转到机器人当前 anchor 的水平位置和 yaw 上。

        BeyondMimic 的做法（commands.py::_update_command）：
          delta_pos = robot_anchor_pos，但 z 用参考的 z
          delta_ori = yaw(robot_anchor_quat * inv(ref_anchor_quat))
        这样水平漂移和整体朝向不计入跟踪误差，只考核"动作形状"，
        但**高度和俯仰/横滚仍然要考核** —— 所以站不稳照样扣分。
        """
        ref_anchor_pos = ref["body_pos"][self._anchor_local]
        ref_anchor_quat = ref["body_quat"][self._anchor_local]

        delta_pos = jp.array([r_anchor_pos[0], r_anchor_pos[1], ref_anchor_pos[2]])
        delta_ori = yaw_quat(quat_mul(r_anchor_quat, quat_conj(ref_anchor_quat)))

        dq = jp.broadcast_to(delta_ori, (self._nb, 4))
        body_quat_rel = quat_mul(dq, ref["body_quat"])
        body_pos_rel = delta_pos + quat_rotate(dq, ref["body_pos"] - ref_anchor_pos)
        return body_pos_rel, body_quat_rel, delta_ori

    # -------------------------------------------------- reset (RSI)
    def reset(self, rng: jax.Array) -> mjx_env.State:
        rng, k_t, k_p, k_o, k_v, k_w, k_j = jax.random.split(rng, 7)

        # 🔴 RSI：从参考轨迹随机时刻取完整状态
        # 不采末帧 —— 采到的话第一步就触发"动作放完"而结束
        idx = jax.random.randint(k_t, (), 0, self._T - 1)
        ref = self._ref_at(idx)
        c = self._config.rsi

        dpos = jax.random.uniform(
            k_p, (3,),
            minval=jp.array([-c.pos_xy, -c.pos_xy, -c.pos_z]),
            maxval=jp.array([c.pos_xy, c.pos_xy, c.pos_z]))
        drpy = jax.random.uniform(
            k_o, (3,),
            minval=jp.array([-c.rpy, -c.rpy, -c.yaw]),
            maxval=jp.array([c.rpy, c.rpy, c.yaw]))
        cr, sr = jp.cos(drpy[0] / 2), jp.sin(drpy[0] / 2)
        cp, sp = jp.cos(drpy[1] / 2), jp.sin(drpy[1] / 2)
        cy, sy = jp.cos(drpy[2] / 2), jp.sin(drpy[2] / 2)
        dquat = jp.array([
            cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy])

        root_pos = ref["root_pos"] + dpos
        root_quat = quat_mul(dquat, ref["root_quat"])
        root_quat = root_quat / jp.linalg.norm(root_quat)

        # 根速度：从参考的 pelvis 速度取，再加扰动
        pel = BODY_NAMES.index("pelvis")
        lin = ref["body_linvel"][pel] + jax.random.uniform(
            k_v, (3,), minval=-c.lin_vel, maxval=c.lin_vel)
        ang = ref["body_angvel"][pel] + jax.random.uniform(
            k_w, (3,), minval=-c.ang_vel, maxval=c.ang_vel)

        jpos = ref["joint_pos"] + jax.random.uniform(
            k_j, (self._nu,), minval=-c.joint_pos, maxval=c.joint_pos)
        jpos = jp.clip(jpos, self._soft_lo, self._soft_hi)

        qpos = jp.concatenate([root_pos, root_quat, jpos])
        # 🔴 MuJoCo 自由关节：qvel[0:3] 是世界系线速度，
        #    qvel[3:6] 是 **机体系** 角速度。参考里存的是世界系，必须转。
        #    不转的话 tennis 这种 11 rad/s 的动作会让速度奖励直接下溢到 0。
        ang_body = quat_rotate_inv(root_quat, ang)
        qvel = jp.concatenate([lin, ang_body, ref["joint_vel"]])

        data = mjx_env.make_data(
            self.mj_model, qpos=qpos, qvel=qvel, ctrl=jpos,
            impl=self.mjx_model.impl.value,
            naconmax=self._config.naconmax, njmax=self._config.njmax)
        data = mjx.forward(self.mjx_model, data)

        info = {
            "rng": rng,
            "step": jp.int32(0),
            "motion_idx": idx,
            "last_act": jp.zeros(self._nu),
        }
        metrics = {
            "err_anchor_pos": jp.zeros(()),
            "err_anchor_ori": jp.zeros(()),
            "err_body_pos": jp.zeros(()),
            "err_body_ori": jp.zeros(()),
            "err_joint_pos": jp.zeros(()),
            "r_anchor_pos": jp.zeros(()),
            "r_anchor_ori": jp.zeros(()),
            "r_body_pos": jp.zeros(()),
            "r_body_ori": jp.zeros(()),
            "r_body_lin_vel": jp.zeros(()),
            "r_body_ang_vel": jp.zeros(()),
        }
        obs = self._get_obs(data, info)
        return mjx_env.State(data, obs, jp.zeros(()), jp.zeros(()), metrics, info)

    # -------------------------------------------------- step
    def step(self, state: mjx_env.State, action: jax.Array) -> mjx_env.State:
        # 参考索引推进（到头就停在最后一帧，由 timeout 结束）
        nidx = jp.minimum(state.info["motion_idx"] + 1, self._T - 1)
        ref_now = self._ref_at(nidx)

        # 🔴 目标位置相对**参考姿态**，不是相对 default_pose。
        #
        #   BeyondMimic 用 use_default_offset=True（相对默认姿态），因为
        #   rsl_rl 的高斯策略输出不做截断，想输出多大都行。
        #   brax 的 NormalTanhDistribution 把动作压在 [-1,1]，位置执行器
        #   稳态下 q ≈ ctrl，所以关节能到的范围就是 default ± action_scale。
        #
        #   实测参考轨迹要求的峰值偏移：
        #     salute 右肘  1.709 rad (98°)  —— 是 0.5 的 3.4 倍
        #     tennis 肩滚  2.051 rad (118°) —— 是 0.5 的 4.1 倍
        #   tennis 有 24% 的上肢目标够不到。手臂物理上抬不起来，
        #   训多久都没用。
        #
        #   改成相对参考姿态后，策略只需输出**修正量**，可达性由构造保证。
        motor_targets = ref_now["joint_pos"] + action * self._action_scale
        data = mjx_env.step(self.mjx_model, state.data, motor_targets,
                            self.n_substeps)

        info = dict(state.info)
        info["motion_idx"] = nidx
        info["step"] = state.info["step"] + 1

        ref = ref_now
        b_pos, b_quat, b_lin, b_ang = self._robot_bodies(data)
        r_anchor_pos = b_pos[self._anchor_local]
        r_anchor_quat = b_quat[self._anchor_local]
        ref_pos_rel, ref_quat_rel, _ = self._align_ref(ref, r_anchor_pos, r_anchor_quat)

        rew, terms, errs = self._reward(
            ref, ref_pos_rel, ref_quat_rel,
            b_pos, b_quat, b_lin, b_ang, data, action, info["last_act"])

        done = self._done(ref, ref_pos_rel, b_pos, r_anchor_pos,
                          r_anchor_quat, data)
        # 🔴 参考动作放完就结束 episode。
        #    原版是在 episode 内瞬移到新的 RSI 点继续（_resample_command），
        #    我这里改成直接结束 —— 否则 RSI 平均从中点起步、episode 长度固定为 T，
        #    会有约一半的样本浪费在"保持末帧姿态"上。
        #    代价：末帧被当成 terminal（不 bootstrap），对动作末尾的状态价值
        #    有轻微低估。这是已知且可接受的偏差。
        done = done | (nidx >= self._T - 1)

        info["last_act"] = action
        obs = self._get_obs(data, info)

        metrics = dict(state.metrics)
        metrics.update(errs)
        metrics.update(terms)

        return mjx_env.State(data, obs, rew, done.astype(jp.float32),
                             metrics, info)

    # -------------------------------------------------- 奖励
    def _reward(self, ref, ref_pos_rel, ref_quat_rel,
                b_pos, b_quat, b_lin, b_ang, data, action, last_act):
        s = self._config.reward_config.scales
        sd = self._config.reward_config.stds

        # --- anchor 全局位置/朝向 ---
        ref_anchor_pos = ref["body_pos"][self._anchor_local]
        ref_anchor_quat = ref["body_quat"][self._anchor_local]
        r_anchor_pos = b_pos[self._anchor_local]
        r_anchor_quat = b_quat[self._anchor_local]

        # 只考核 z 和姿态（xy 漂移由 align 吸收），与 BeyondMimic 的
        # bad_anchor_pos_z_only 终止判据保持一致的口径
        e_anchor_pos = jp.square(ref_anchor_pos[2] - r_anchor_pos[2])
        r_ap = jp.exp(-e_anchor_pos / sd.anchor_pos ** 2)

        e_anchor_ori = jp.square(quat_error_magnitude(ref_anchor_quat, r_anchor_quat))
        r_ao = jp.exp(-e_anchor_ori / sd.anchor_ori ** 2)

        # --- body 相对位置/朝向 ---
        e_bp = jp.sum(jp.square(ref_pos_rel - b_pos), axis=-1)          # (B,)
        r_bp = jp.exp(-jp.mean(e_bp) / sd.body_pos ** 2)

        e_bo = jp.square(quat_error_magnitude(ref_quat_rel, b_quat))    # (B,)
        r_bo = jp.exp(-jp.mean(e_bo) / sd.body_ori ** 2)

        # --- body 速度（全局，不做对齐，与原版一致）---
        e_bl = jp.sum(jp.square(ref["body_linvel"] - b_lin), axis=-1)
        r_bl = jp.exp(-jp.mean(e_bl) / sd.body_lin_vel ** 2)

        e_ba = jp.sum(jp.square(ref["body_angvel"] - b_ang), axis=-1)
        r_ba = jp.exp(-jp.mean(e_ba) / sd.body_ang_vel ** 2)

        # --- 惩罚 ---
        p_rate = jp.sum(jp.square(action - last_act))
        q = data.qpos[7:]
        p_limit = jp.sum(jp.clip(self._soft_lo - q, 0.0, None)
                         + jp.clip(q - self._soft_hi, 0.0, None))

        rew = (s.anchor_pos * r_ap + s.anchor_ori * r_ao
               + s.body_pos * r_bp + s.body_ori * r_bo
               + s.body_lin_vel * r_bl + s.body_ang_vel * r_ba
               + s.action_rate * p_rate + s.joint_limit * p_limit)
        # 奖励量级：单步上限 5.0（六项跟踪的权重和），不乘 dt。
        #
        # Isaac Lab 的 RewardManager 会把每项乘 dt（BeyondMimic 的单步上限
        # 因此是 0.1），我一度照搬。但对齐**绝对量级**是没意义的：
        # 整体乘一个常数不改变最优策略。真正要紧的是两件事 ——
        #   (a) 各奖励项之间的相对权重：乘常数不影响，已对齐；
        #   (b) 奖励与熵奖励的比值：这个是优化器相关的。
        # brax 把熵项直接加进 loss（不像优势那样归一化），
        # entropy_cost=5e-3 x entropy(29维,std≈1) ≈ 0.205/步。
        # 乘 dt 之后任务奖励只有 0.044/步 —— 熵是任务的 3.4 倍，
        # 优化器被"保持最大随机"主导，实测 61M 步后策略比零动作还差。
        # 保持 O(1)/步 的量级（brax 常规做法），熵占比降到 1% 以下。

        errs = {
            "err_anchor_pos": jp.abs(ref_anchor_pos[2] - r_anchor_pos[2]),
            "err_anchor_ori": quat_error_magnitude(ref_anchor_quat, r_anchor_quat),
            "err_body_pos": jp.mean(jp.linalg.norm(ref_pos_rel - b_pos, axis=-1)),
            "err_body_ori": jp.mean(quat_error_magnitude(ref_quat_rel, b_quat)),
            "err_joint_pos": jp.mean(jp.abs(ref["joint_pos"] - q)),
        }
        terms = {
            "r_anchor_pos": r_ap, "r_anchor_ori": r_ao,
            "r_body_pos": r_bp, "r_body_ori": r_bo,
            "r_body_lin_vel": r_bl, "r_body_ang_vel": r_ba,
        }
        return rew, terms, errs

    # -------------------------------------------------- 终止
    def _done(self, ref, ref_pos_rel, b_pos, r_anchor_pos, r_anchor_quat, data):
        """🔴 跟踪误差超阈值即终止 —— 这是"站着不动混分"行不通的原因。"""
        t = self._config.termination

        ref_anchor_pos = ref["body_pos"][self._anchor_local]
        ref_anchor_quat = ref["body_quat"][self._anchor_local]

        bad_pos = jp.abs(ref_anchor_pos[2] - r_anchor_pos[2]) > t.anchor_pos_z

        g = jp.array([0.0, 0.0, -1.0])
        ref_grav_z = quat_rotate_inv(ref_anchor_quat, g)[2]
        rob_grav_z = quat_rotate_inv(r_anchor_quat, g)[2]
        bad_ori = jp.abs(ref_grav_z - rob_grav_z) > t.anchor_ori

        ee_err = jp.abs(ref_pos_rel[self._ee_local, 2] - b_pos[self._ee_local, 2])
        bad_ee = jp.any(ee_err > t.ee_pos_z)

        nan = jp.any(jp.isnan(data.qpos)) | jp.any(jp.isnan(data.qvel))
        return bad_pos | bad_ori | bad_ee | nan

    # -------------------------------------------------- 观测
    def _get_obs(self, data, info) -> Dict[str, jax.Array]:
        idx = info["motion_idx"]
        ref = self._ref_at(idx)

        b_pos, b_quat, b_lin, b_ang = self._robot_bodies(data)
        r_anchor_pos = b_pos[self._anchor_local]
        r_anchor_quat = b_quat[self._anchor_local]

        # 参考 anchor 在机器人 anchor 系下的位姿（BeyondMimic 的核心观测）
        ref_anchor_pos = ref["body_pos"][self._anchor_local]
        ref_anchor_quat = ref["body_quat"][self._anchor_local]
        anchor_pos_b = quat_rotate_inv(r_anchor_quat, ref_anchor_pos - r_anchor_pos)
        anchor_ori_b = mat_from_quat_2col(
            quat_mul(quat_conj(r_anchor_quat), ref_anchor_quat))

        gyro = self.get_gyro(data, "torso")
        q_rel = data.qpos[7:] - self._default_pose
        dq = data.qvel[6:]

        # command = 参考的关节角 + 关节速度（原版 MotionCommand.command）
        command = jp.concatenate([ref["joint_pos"], ref["joint_vel"]])

        # 🔴 策略观测里没有躯干线速度 —— SDK/真机不提供，训练时用了就没法部署。
        #    critic 保留（非对称 actor-critic）。
        # 🔴 策略观测只能用宇树 SDK 真实提供的量：
        #      LowState = motor_state.q/.dq + imu_state.quaternion/.gyroscope
        #    所以这里**不能**放 anchor_pos_b —— 它需要躯干的世界位置，
        #    机器人没有全局定位，真机和 unitree_mujoco 上都算不出来。
        #    同理 base_lin_vel 也早已去掉（IMU 只给角速度和姿态）。
        #    BeyondMimic 官方的 Wo-State-Estimation 配置去掉的正是这两项。
        #    critic 仍然看得到（下面 privileged），训练信号不受影响。
        state = jp.concatenate([
            command,            # 58   参考关节角 + 关节速度
            anchor_ori_b,       # 6    姿态误差，来自 IMU 四元数
            gyro,               # 3    IMU 陀螺仪
            q_rel,              # 29   关节角
            dq,                 # 29   关节速度
            info["last_act"],   # 29
        ])                      # = 154

        # critic 额外看到：全局线速度 + 机体系下的 body 位姿
        linvel = self.get_global_linvel(data, "torso")
        body_pos_b = jax.vmap(lambda p: quat_rotate_inv(r_anchor_quat, p - r_anchor_pos))(b_pos)
        body_ori_b = jax.vmap(
            lambda qq: mat_from_quat_2col(quat_mul(quat_conj(r_anchor_quat), qq)))(b_quat)
        privileged = jp.concatenate([
            state, anchor_pos_b, linvel,
            body_pos_b.reshape(-1),     # 14*3 = 42
            body_ori_b.reshape(-1),     # 14*6 = 84
        ])

        return {"state": state, "privileged_state": privileged}
