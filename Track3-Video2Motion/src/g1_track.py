"""Whole-body motion tracking for the G1 — BeyondMimic's recipe ported to MJX.

Why the first design was abandoned
----------------------------------
The previous version (g1_deploy.py) inherited Playground's Joystick
environment, tracked upper-body joint angles only, regularised the legs
towards a default standing pose, and terminated on falling alone. The policy
learned to **stand still and wave its arms around**: not falling already
earned a full-length episode, tracking was a small share of the per-step
reward, and ignoring it cost almost nothing.

BeyondMimic (HybridRobotics/whole_body_tracking) is structured differently:

  1. Track the position, orientation, linear and angular velocity of 14 body
     links **in 3-D**, rather than joint angles. Joint-angle error correlates
     poorly with whether the motion looks right.
  2. **Terminate as soon as tracking error exceeds a threshold** — standing
     still has its episode cut short immediately and cannot accumulate
     reward. This is DeepMimic's central idea.
  3. **RSI**: every reset draws a **full state** (root pose, root velocity,
     joint angles, joint velocities) from a random frame of the reference,
     instead of always starting from a standing pose.
  4. Six tracking terms and three penalties, with no locomotion leftovers.

The original depends on Isaac Lab / Isaac Sim (CUDA-only) and the mjlab
reproduction on MuJoCo-Warp (also CUDA-only), so neither runs on AMD. The MDP
is therefore reimplemented on MJX from the paper and source, matching reward
formulas, weights, stds and termination thresholds term by term.

Alignment against tracking_env_cfg.py
-------------------------------------
  motion_global_anchor_pos   w=0.5  std=0.30
  motion_global_anchor_ori   w=0.5  std=0.40
  motion_body_pos            w=1.0  std=0.30
  motion_body_ori            w=1.0  std=0.40
  motion_body_lin_vel        w=1.0  std=1.00
  motion_body_ang_vel        w=1.0  std=3.14
  action_rate_l2             w=-0.1
  joint_limit                w=-10.0
  undesired_contacts         w=-0.1
  termination: anchor_z>0.25 / anchor_ori>0.8 / end-effector z>0.25 / 10 s timeout
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

# The G1 bodies BeyondMimic tracks (flat_env_cfg.py).
BODY_NAMES = [
    "pelvis",
    "left_hip_roll_link", "left_knee_link", "left_ankle_roll_link",
    "right_hip_roll_link", "right_knee_link", "right_ankle_roll_link",
    "torso_link",
    "left_shoulder_roll_link", "left_elbow_link", "left_wrist_yaw_link",
    "right_shoulder_roll_link", "right_elbow_link", "right_wrist_yaw_link",
]
ANCHOR_BODY = "torso_link"
# Termination looks at these four end effectors only.
EE_BODIES = ["left_ankle_roll_link", "right_ankle_roll_link",
             "left_wrist_yaw_link", "right_wrist_yaw_link"]


def default_config() -> config_dict.ConfigDict:
    return config_dict.create(
        ctrl_dt=0.02,
        # BeyondMimic uses 0.005, but that suits its own actuator model
        # (stiffness = armature x (2*pi*10)^2 — a 10 Hz natural frequency with
        # damping ratio 2, deliberately soft). Playground's G1 pairs kp=75 with
        # a very small armature and is far stiffer, where 0.005 diverges: under
        # a perfect controller base_z reached -165911. Anything at or below
        # 0.004 is stable and gives the same result; 0.002 is the value
        # Playground itself validates against.
        sim_dt=0.002,
        impl="jax",            # upstream defaults to warp, which is CUDA-only
        naconmax=1024,
        njmax=128,
        episode_length=500,    # 10s / 0.02s
        action_scale=0.5,
        action_repeat=1,
        restricted_joint_range=False,
        # Must be 1.0 (the hard limit), not Playground's 0.9. The joint_limit
        # penalty carries weight -10, and the tennis reference exceeds the 0.9
        # soft limit on 269 of 298 frames (peak 0.192 rad at shoulder roll).
        # Tracking the reference perfectly would therefore be fined -2.09 per
        # step against a maximum tracking reward of 5.0 — the reward function
        # would be asking for the motion and punishing it at the same time. The
        # reference violates the hard limit on no frames at all, so 1.0 removes
        # the contradiction. Isaac Lab also defaults this factor to 1.0.
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
        # Noise added to the reference state at RSI (matches MotionCommandCfg).
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


# ------------------------------------------------------- quaternion helpers
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
    """Rotation angle between two quaternions, in radians (isaaclab.utils.math)."""
    r = quat_mul(a, quat_conj(b))
    w = jp.clip(jp.abs(r[..., 0]), 0.0, 1.0)
    return 2.0 * jp.arccos(w)


def quat_rotate(q, v):
    """Rotate a vector by a quaternion."""
    qw = q[..., 0:1]
    qv = q[..., 1:4]
    t = 2.0 * jp.cross(qv, v)
    return v + qw * t + jp.cross(qv, t)


def quat_rotate_inv(q, v):
    return quat_rotate(quat_conj(q), v)


def yaw_quat(q):
    """Keep the yaw component only."""
    yaw = jp.arctan2(2.0 * (q[..., 0] * q[..., 3] + q[..., 1] * q[..., 2]),
                     1.0 - 2.0 * (q[..., 2] ** 2 + q[..., 3] ** 2))
    h = yaw * 0.5
    z = jp.zeros_like(h)
    return jp.stack([jp.cos(h), z, z, jp.sin(h)], axis=-1)


def mat_from_quat_2col(q):
    """First two columns of the rotation matrix — the 6-D orientation
    representation BeyondMimic observes."""
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    c0 = jp.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)], -1)
    c1 = jp.stack([2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)], -1)
    return jp.concatenate([c0, c1], axis=-1)


# ------------------------------------------------------------------- environment
class G1Track(g1_base.G1Env):
    """Whole-body motion tracking, BeyondMimic style."""

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

        # ---- reference motion ----
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
        assert names == BODY_NAMES, f"body order does not match: {names}"

        # ---- body indices ----
        self._body_ids = jp.asarray([
            mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n) for n in BODY_NAMES])
        self._anchor_local = BODY_NAMES.index(ANCHOR_BODY)
        self._ee_local = jp.asarray([BODY_NAMES.index(n) for n in EE_BODIES])
        self._body_rootids = jp.asarray(
            [m.body_rootid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, n)]
             for n in BODY_NAMES])
        self._nb = len(BODY_NAMES)

        # ---- default pose and joint limits ----
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

        # ---- per-joint action scale ----
        # BeyondMimic (robots/g1.py): action_scale = 0.25 * effort_limit / stiffness
        # BeyondMimic uses a quarter of the joint deflection at full torque.
        # Playground uses a uniform 0.5, which is small for high-torque joints
        # like the hips and knees and large for the wrists and ankles. Its
        # formula does not carry over: Playground's G1 uses position actuators
        # whose actuator_forcerange is all zeros (no torque ceiling declared),
        # so the expression divides by zero. The two models also disagree on kp
        # (Playground: hips and knees 75, ankles 20, wrists 2;
        #    BeyondMimic: stiffness = armature x (2*pi*10)^2）。
        # so we keep Playground's uniform 0.5, which its own sim2real work
        # validates and which sits mid-range against BeyondMimic's per-joint
        # values (0.30 to 0.90).
        self._action_scale = jp.full((m.nu,), self._config.action_scale)

        # Episode length equals the number of reference frames. RSI starts at
        # a random frame; once the index runs out it holds the final one, which
        # still has to be tracked rather than being free reward.
        object.__setattr__(self._config, "episode_length", int(self._T))

        print(f"[env] reference {self._T} frames ({self._T*0.02:.1f}s), "
              f"tracking {self._nb} bodies, anchor={ANCHOR_BODY}")
        print(f"[env] action_scale = {self._config.action_scale} (uniform)")
        print(f"[env] impl={self._config.impl}  "
              f"episode={self._config.episode_length} steps")

    # ---------------------------------------------- reading the reference
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

    # ------------------------------------------- the robot's current state
    def _robot_bodies(self, data):
        pos = data.xpos[self._body_ids]
        quat = data.xquat[self._body_ids]
        ang = data.cvel[self._body_ids, 0:3]        # world frame, usable as is
        # The linear part of cvel is the velocity **at subtree_com**, not at
        # the body origin. The reference is a finite difference of xpos, so it
        # must be transferred to the same point:
        #        v_origin = v_com + ω × (xpos - subtree_com)
        # Uncorrected this averages 0.26 m/s of error, reaching 1.0 m/s at
        # the wrists.
        com = data.subtree_com[self._body_rootids]
        lin = data.cvel[self._body_ids, 3:6] + jp.cross(ang, pos - com)
        return pos, quat, lin, ang

    # ------------------------------------------- reference, aligned to robot
    def _align_ref(self, ref, r_anchor_pos, r_anchor_quat):
        """Translate and rotate the reference onto the robot's current anchor
        position and yaw.

        Following BeyondMimic (commands.py::_update_command):
          delta_pos = robot_anchor_pos, except z, which comes from the reference
          delta_ori = yaw(robot_anchor_quat * inv(ref_anchor_quat))

        Horizontal drift and overall heading are therefore excluded from the
        tracking error, leaving the shape of the motion — but **height, pitch
        and roll are still scored**, so failing to stay upright still costs.
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

        # RSI: take a full state from a random frame of the reference. The
        # final frame is excluded — starting there would trigger "motion
        # finished" on the very first step.
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

        # Root velocity comes from the reference pelvis velocity, plus noise.
        pel = BODY_NAMES.index("pelvis")
        lin = ref["body_linvel"][pel] + jax.random.uniform(
            k_v, (3,), minval=-c.lin_vel, maxval=c.lin_vel)
        ang = ref["body_angvel"][pel] + jax.random.uniform(
            k_w, (3,), minval=-c.ang_vel, maxval=c.ang_vel)

        jpos = ref["joint_pos"] + jax.random.uniform(
            k_j, (self._nu,), minval=-c.joint_pos, maxval=c.joint_pos)
        jpos = jp.clip(jpos, self._soft_lo, self._soft_hi)

        qpos = jp.concatenate([root_pos, root_quat, jpos])
        # For a MuJoCo free joint, qvel[0:3] is world-frame linear velocity
        # but qvel[3:6] is **body-frame** angular velocity. The reference
        # stores world frame, so it has to be converted. Without this, a motion
        # like tennis at 11 rad/s drives the velocity rewards to exactly 0.
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
        # Advance the reference index; hold the last frame and let the
        # timeout end the episode.
        nidx = jp.minimum(state.info["motion_idx"] + 1, self._T - 1)
        ref_now = self._ref_at(nidx)

        # Targets are relative to the **reference pose**, not default_pose.
        #
        # BeyondMimic sets use_default_offset=True because rsl_rl's Gaussian
        # policy is unbounded and can emit arbitrarily large actions. brax's
        # NormalTanhDistribution clamps actions to [-1,1], and a position
        # actuator settles at q ~= ctrl, so the reachable range is exactly
        # default +/- action_scale.
        #
        # Peak deflections the references actually demand:
        #   salute, right elbow    1.709 rad (98 deg)  - 3.4x over 0.5
        #   tennis, shoulder roll  2.051 rad (118 deg) - 4.1x over 0.5
        # 24% of tennis's upper-body targets are unreachable. The arms cannot
        # physically get there, and no amount of training changes that.
        #
        # Relative to the reference, the policy only has to emit a
        # correction, and reachability holds by construction.
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
        # End the episode when the reference runs out. Upstream teleports to a
        # fresh RSI point and continues within the same episode
        # (_resample_command); we stop instead. RSI starts halfway through on
        # average and the episode length is fixed at T, so continuing would
        # spend roughly half of all samples holding the final pose. The cost is
        # that the last frame is treated as terminal and not bootstrapped,
        # slightly under-estimating state value near the end of the motion —
        # a known and accepted bias.
        done = done | (nidx >= self._T - 1)

        info["last_act"] = action
        obs = self._get_obs(data, info)

        metrics = dict(state.metrics)
        metrics.update(errs)
        metrics.update(terms)

        return mjx_env.State(data, obs, rew, done.astype(jp.float32),
                             metrics, info)

    # ----------------------------------------------------------- rewards
    def _reward(self, ref, ref_pos_rel, ref_quat_rel,
                b_pos, b_quat, b_lin, b_ang, data, action, last_act):
        s = self._config.reward_config.scales
        sd = self._config.reward_config.stds

        # --- anchor global position and orientation ---
        ref_anchor_pos = ref["body_pos"][self._anchor_local]
        ref_anchor_quat = ref["body_quat"][self._anchor_local]
        r_anchor_pos = b_pos[self._anchor_local]
        r_anchor_quat = b_quat[self._anchor_local]

        # Only z and orientation are scored — align() already absorbs xy drift
        # — matching BeyondMimic's bad_anchor_pos_z_only termination.
        e_anchor_pos = jp.square(ref_anchor_pos[2] - r_anchor_pos[2])
        r_ap = jp.exp(-e_anchor_pos / sd.anchor_pos ** 2)

        e_anchor_ori = jp.square(quat_error_magnitude(ref_anchor_quat, r_anchor_quat))
        r_ao = jp.exp(-e_anchor_ori / sd.anchor_ori ** 2)

        # --- body position and orientation, relative ---
        e_bp = jp.sum(jp.square(ref_pos_rel - b_pos), axis=-1)          # (B,)
        r_bp = jp.exp(-jp.mean(e_bp) / sd.body_pos ** 2)

        e_bo = jp.square(quat_error_magnitude(ref_quat_rel, b_quat))    # (B,)
        r_bo = jp.exp(-jp.mean(e_bo) / sd.body_ori ** 2)

        # --- body velocity: global, unaligned, as upstream ---
        e_bl = jp.sum(jp.square(ref["body_linvel"] - b_lin), axis=-1)
        r_bl = jp.exp(-jp.mean(e_bl) / sd.body_lin_vel ** 2)

        e_ba = jp.sum(jp.square(ref["body_angvel"] - b_ang), axis=-1)
        r_ba = jp.exp(-jp.mean(e_ba) / sd.body_ang_vel ** 2)

        # --- penalties ---
        p_rate = jp.sum(jp.square(action - last_act))
        q = data.qpos[7:]
        p_limit = jp.sum(jp.clip(self._soft_lo - q, 0.0, None)
                         + jp.clip(q - self._soft_hi, 0.0, None))

        rew = (s.anchor_pos * r_ap + s.anchor_ori * r_ao
               + s.body_pos * r_bp + s.body_ori * r_bo
               + s.body_lin_vel * r_bl + s.body_ang_vel * r_ba
               + s.action_rate * p_rate + s.joint_limit * p_limit)
        # Reward scale: at most 5.0 per step (the six tracking weights), not
        # multiplied by dt.
        #
        # Isaac Lab's RewardManager multiplies each term by dt, which puts
        # BeyondMimic's per-step ceiling at 0.1, and we copied that at first.
        # Matching the **absolute** scale is pointless — scaling every term by
        # one constant leaves the optimal policy unchanged. Two things do
        # matter: the ratios between reward terms, which a constant does not
        # affect and which are already matched; and the ratio between reward
        # and the entropy bonus, which is optimiser-specific. brax adds entropy
        # straight into the loss without normalising it the way advantages are,
        # and entropy_cost=5e-3 x entropy(29 dims, std~1) is about 0.205 per
        # step. After multiplying by dt the task reward is only 0.044 per step,
        # so entropy outweighs the task 3.4 to 1; the optimiser then favours
        # staying maximally random, and after 61M steps the policy scored worse
        # than taking no action at all. Keeping rewards at O(1) per step —
        # normal practice in brax — puts entropy below 1% of the total.

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

    # ------------------------------------------------------- termination
    def _done(self, ref, ref_pos_rel, b_pos, r_anchor_pos, r_anchor_quat, data):
        """Terminate once tracking error exceeds threshold. This is what makes
        standing still unprofitable."""
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

    # ------------------------------------------------------ observations
    def _get_obs(self, data, info) -> Dict[str, jax.Array]:
        idx = info["motion_idx"]
        ref = self._ref_at(idx)

        b_pos, b_quat, b_lin, b_ang = self._robot_bodies(data)
        r_anchor_pos = b_pos[self._anchor_local]
        r_anchor_quat = b_quat[self._anchor_local]

        # Reference anchor expressed in the robot's anchor frame —
        # BeyondMimic's central observation.
        ref_anchor_pos = ref["body_pos"][self._anchor_local]
        ref_anchor_quat = ref["body_quat"][self._anchor_local]
        anchor_pos_b = quat_rotate_inv(r_anchor_quat, ref_anchor_pos - r_anchor_pos)
        anchor_ori_b = mat_from_quat_2col(
            quat_mul(quat_conj(r_anchor_quat), ref_anchor_quat))

        gyro = self.get_gyro(data, "torso")
        q_rel = data.qpos[7:] - self._default_pose
        dq = data.qvel[6:]

        # command = reference joint angles and velocities (MotionCommand.command)
        command = jp.concatenate([ref["joint_pos"], ref["joint_vel"]])

        # The policy observation carries no torso linear velocity: the SDK and
        # the real robot do not provide it, so training on it would make the
        # policy undeployable. The critic still sees it (asymmetric
        # actor-critic). The policy may only use what Unitree's SDK reports:
        #      LowState = motor_state.q/.dq + imu_state.quaternion/.gyroscope
        # anchor_pos_b therefore cannot appear here: it needs the torso's
        # world position, and the robot has no global localisation — neither
        # hardware nor unitree_mujoco can produce it. base_lin_vel was dropped
        # for the same reason (the IMU gives angular rate and orientation
        # only). BeyondMimic's own Wo-State-Estimation configuration removes
        # exactly these two. The critic still sees both, below, so the training
        # signal is unaffected.
        state = jp.concatenate([
            command,            # 58   reference joint angles and velocities
            anchor_ori_b,       # 6    orientation error, from the IMU quaternion
            gyro,               # 3    IMU gyroscope
            q_rel,              # 29   joint angles
            dq,                 # 29   joint velocities
            info["last_act"],   # 29
        ])                      # = 154

        # The critic additionally sees global linear velocity and body poses
        # in the base frame.
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
