"""Layer 3: drive unitree_mujoco (or a real G1) over DDS with the trained policy.

Everything the policy sees is derived from `LowState` alone:

    motor_state[i].q        29 joint angles
    motor_state[i].dq       29 joint velocities
    imu_state.quaternion    pelvis orientation
    imu_state.gyroscope     pelvis angular rate (body frame)

plus the reference motion file, which ships with the policy.

⚠️ One subtlety the policy forces on us: it was trained on the **torso_link**
frame (Playground's `gyro_torso` / `orientation_torso` sensors), but the G1's
IMU sits on the **pelvis**. Between them are three waist joints, so pelvis
orientation is NOT torso orientation whenever the waist moves.

We recover the torso frame by forward kinematics from data we already have:
put the pelvis orientation and the measured joint angles into a kinematics-only
MuJoCo model, run mj_forward, and read the torso frame back out. Same for the
angular rate via mj_objectVelocity. No extra sensor is needed, so this stays a
legitimate SDK-only deployment.
"""

import argparse
import sys
import time
from pathlib import Path

import mujoco
import numpy as np

from unitree_sdk2py.core.channel import (ChannelFactoryInitialize,
                                         ChannelPublisher, ChannelSubscriber)
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
from unitree_sdk2py.utils.crc import CRC

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

BASE = C.SRC
N_MOTOR = 29
ANCHOR = "torso_link"
BODY_NAMES = [
    "pelvis",
    "left_hip_roll_link", "left_knee_link", "left_ankle_roll_link",
    "right_hip_roll_link", "right_knee_link", "right_ankle_roll_link",
    "torso_link",
    "left_shoulder_roll_link", "left_elbow_link", "left_wrist_yaw_link",
    "right_shoulder_roll_link", "right_elbow_link", "right_wrist_yaw_link",
]


# ───────────────────────── quaternion helpers
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


def mat2col(q):
    w, x, y, z = q
    c0 = np.array([1 - 2*(y*y + z*z), 2*(x*y + w*z), 2*(x*z - w*y)])
    c1 = np.array([2*(x*y - w*z), 1 - 2*(x*x + z*z), 2*(y*z + w*x)])
    return np.concatenate([c0, c1])


class NumpyPolicy:
    def __init__(self, npz):
        d = np.load(npz)
        self.mean, self.std = d["norm_mean"], d["norm_std"]
        n = int(d["n_layers"])
        self.W = [d[f"w{i}"] for i in range(n)]
        self.b = [d[f"b{i}"] for i in range(n)]
        print(f"[policy] {n} layers, input dim {self.mean.shape[0]}")

    def __call__(self, obs):
        x = (obs - self.mean) / self.std
        for i in range(len(self.W) - 1):
            z = x @ self.W[i] + self.b[i]
            x = z / (1.0 + np.exp(-z))                 # swish
        out = x @ self.W[-1] + self.b[-1]
        return np.tanh(out[: out.shape[-1] // 2])


class TorsoFK:
    """pelvis IMU + joint angles  ->  torso orientation and angular rate.

    The policy was trained on the torso frame; the robot only measures the
    pelvis. Three waist joints sit in between, so we have to propagate.
    """

    def __init__(self):
        from mujoco_playground._src.locomotion.g1 import base, g1_constants as c
        self.m = mujoco.MjModel.from_xml_string(
            Path(c.FEET_ONLY_FLAT_TERRAIN_XML).read_text(), base.get_assets())
        self.d = mujoco.MjData(self.m)
        self.tid = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, ANCHOR)

    def __call__(self, pelvis_quat, q, pelvis_gyro, dq):
        d = self.d
        d.qpos[0:3] = 0.0
        d.qpos[3:7] = pelvis_quat
        d.qpos[7:] = q
        d.qvel[0:3] = 0.0
        d.qvel[3:6] = pelvis_gyro          # free joint: body-frame angular rate
        d.qvel[6:] = dq
        mujoco.mj_forward(self.m, d)
        res = np.zeros(6)
        mujoco.mj_objectVelocity(self.m, d, mujoco.mjtObj.mjOBJ_BODY,
                                 self.tid, res, 1)     # flg_local=1
        return d.xquat[self.tid].copy(), res[0:3].copy()


class Controller:
    def __init__(self, policy_npz, motion_npz, ctrl_dt=0.02,
                 action_scale=0.5, kp=None, kd=2.0):
        self.pol = NumpyPolicy(policy_npz)
        self.fk = TorsoFK()
        ref = np.load(motion_npz)
        self.ref_q = ref["joint_pos"]
        self.ref_dq = ref["joint_vel"]
        self.ref_bq = ref["body_quat_w"]
        self.a_i = BODY_NAMES.index(ANCHOR)
        self.T = self.ref_q.shape[0]

        self.ctrl_dt = ctrl_dt
        self.a_scale = action_scale
        # Playground's position actuators: kp lives in the model, kv = 0 and
        # damping comes from the joints. The unitree bridge is a software PD,
        # so it needs an explicit kd.
        self.kp = np.asarray(kp if kp is not None
                             else self.fk.m.actuator_gainprm[:, 0])
        self.kd = np.full(N_MOTOR, kd)
        self.default_pose = self.fk.m.keyframe("home").qpos[7:].copy()

        self.last_act = np.zeros(N_MOTOR)
        self.low_state = None
        self.crc = CRC()
        self.cmd = unitree_hg_msg_dds__LowCmd_()
        self.pub = ChannelPublisher("rt/lowcmd", LowCmd_)
        self.pub.Init()
        self.sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.sub.Init(self._on_state, 10)

    def _on_state(self, msg):
        self.low_state = msg

    def wait(self, timeout=15.0):
        t0 = time.time()
        while self.low_state is None:
            if time.time() - t0 > timeout:
                raise TimeoutError("no LowState — check DOMAIN_ID / interface")
            time.sleep(0.01)
        print(f"[dds] LowState received, mode_machine={self.low_state.mode_machine}")
        self.cmd.mode_machine = self.low_state.mode_machine

    def send(self, target_q):
        for i in range(N_MOTOR):
            mc = self.cmd.motor_cmd[i]
            mc.mode, mc.q, mc.dq, mc.tau = 1, float(target_q[i]), 0.0, 0.0
            mc.kp, mc.kd = float(self.kp[i]), float(self.kd[i])
        self.cmd.crc = self.crc.Crc(self.cmd)
        self.pub.Write(self.cmd)

    def obs(self, idx):
        st = self.low_state
        q = np.array([st.motor_state[i].q for i in range(N_MOTOR)])
        dq = np.array([st.motor_state[i].dq for i in range(N_MOTOR)])
        pq = np.array(st.imu_state.quaternion)          # w,x,y,z
        pg = np.array(st.imu_state.gyroscope)

        torso_q, torso_gyro = self.fk(pq, q, pg, dq)
        ref_aq = self.ref_bq[idx, self.a_i]

        return np.concatenate([
            self.ref_q[idx], self.ref_dq[idx],          # 58
            mat2col(qmul(qconj(torso_q), ref_aq)),      # 6  anchor_ori_b
            torso_gyro,                                 # 3
            q - self.default_pose,                      # 29
            dq,                                         # 29
            self.last_act,                              # 29
        ]).astype(np.float32)                           # = 154

    def run(self, n_steps):
        self.wait()
        g = qrot_inv(np.array(self.low_state.imu_state.quaternion),
                     np.array([0., 0., -1.]))
        print(f"[start] pelvis gravity_z={g[2]:+.3f}")
        print(f"[run] executing {n_steps} steps ({n_steps*self.ctrl_dt:.1f}s)")

        alive, fell = 0, False
        for t in range(n_steps):
            idx = min(t + 1, self.T - 1)
            act = self.pol(self.obs(idx))
            self.send(self.ref_q[idx] + act * self.a_scale)
            self.last_act = act
            alive = t + 1

            g = qrot_inv(np.array(self.low_state.imu_state.quaternion),
                         np.array([0., 0., -1.]))
            if g[2] > -0.5:
                print(f"  FELL at step {t} (gravity_z={g[2]:+.3f})")
                fell = True
                break
            if t % 25 == 0:
                q = np.array([self.low_state.motor_state[i].q
                              for i in range(N_MOTOR)])
                err = np.degrees(np.abs(q - self.ref_q[idx]).mean())
                print(f"  t={t:>4}  joint err={err:5.2f} deg  "
                      f"gravity_z={g[2]:+.3f}")
            time.sleep(self.ctrl_dt)

        print()
        print(f"{'FELL' if fell else 'OK  survived'}  {alive}/{n_steps} steps "
              f"({alive*self.ctrl_dt:.1f}s)")
        return not fell


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--motion", required=True)
    ap.add_argument("--steps", type=int, default=156)
    ap.add_argument("--domain_id", type=int, default=1)
    ap.add_argument("--interface", default="lo")
    ap.add_argument("--kd", type=float, default=2.0)
    a = ap.parse_args()

    print(f"[dds] init domain={a.domain_id} interface={a.interface}")
    ChannelFactoryInitialize(a.domain_id, a.interface)
    Controller(a.policy, a.motion, kd=a.kd).run(a.steps)


if __name__ == "__main__":
    main()
