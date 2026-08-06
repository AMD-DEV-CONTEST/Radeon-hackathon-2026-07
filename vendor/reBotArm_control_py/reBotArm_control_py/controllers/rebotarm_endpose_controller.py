"""RebotArmEndPose — 末端位姿控制器（IK + 轨迹规划）。

同时支持两种运动模式：

  - ``move_to_ik(...)``   即时 IK 求解，关节角度一步到位。
  - ``move_to_traj(...)`` SE(3) 测地线规划 + CLIK 跟踪，平滑轨迹运动。

arm 部分支持两种控制模式（由 ``arm_control_mode`` 选择）：

  - ``"posvel"``（默认）：位置+速度模式，电机内部 PID 闭环。
  - ``"mit"``           ：MIT 阻抗控制模式，主机下发 pos/vel/kp/kd/tau 五元组。

控制循环中按组发送：rebotarm.arm.send_pos_vel() → rebotarm.gripper.send_mit()
（posvel 模式），或 rebotarm.arm.send_mit() → rebotarm.gripper.send_mit()（mit 模式）。

使用示例::
----
    from reBotArm_control_py.controllers import RebotArmEndPose

    rebotarm = RebotArm()

    # POS_VEL 模式（默认）
    ctrl = RebotArmEndPose(rebotarm, arm_control_mode="posvel")
    ctrl.start()
    ctrl.move_to_ik(x=0.3, y=0.0, z=0.3)
    ctrl.move_to_traj(x=0.3, y=0.0, z=0.3, duration=2.0)
    ctrl.end()
----
    from reBotArm_control_py.controllers import RebotArmEndPose

    rebotarm = RebotArm()

    # MIT 模式
    ctrl_mit = RebotArmEndPose(rebotarm, arm_control_mode="mit")
    ctrl_mit.start()
    ctrl_mit.move_to_ik(x=0.3, y=0.0, z=0.3)
    ctrl_mit.move_to_traj(x=0.3, y=0.0, z=0.3, duration=2.0)
    ctrl_mit.end()

上下文管理器::

    with RebotArmEndPose(rebotarm, arm_control_mode="mit") as ctrl:
        ctrl.move_to_ik(x=0.3, y=0.0, z=0.3)
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from ..dynamics import compute_generalized_gravity
from ..kinematics import (
    compute_fk,
    pos_rot_to_se3,
    get_end_effector_frame_id,
    load_robot_model,
    pad_q_for_model,
)
from ..kinematics.inverse_kinematics import (
    solve_ik,
    IKParams as TrajIKParams,
)
from ..trajectory import (
    TrajProfile,
    TrajPlanParams,
    IKParams as ClikIKParams,
    plan_cartesian_geodesic_trajectory,
    track_trajectory,
)
from ..actuator import RebotArm


class RebotArmEndPose:

    def __init__(
        self,
        rebotarm: RebotArm,
        dt: float = 0.01,
        profile: TrajProfile = TrajProfile.MIN_JERK,
        arm_control_mode: str = "posvel",
        use_gravity_ff: bool = True,
    ) -> None:
        if arm_control_mode not in ("mit", "posvel"):
            raise ValueError("arm_control_mode must be 'mit' or 'posvel'")
        self._arm_control_mode = arm_control_mode
        self._use_gravity_ff = use_gravity_ff
        self.rebotarm = rebotarm
        self._arm_group = rebotarm.groups.get("arm", None)
        self._gripper_group = rebotarm.groups.get("gripper", None)
        self._has_gripper = rebotarm.has_gripper

        if self._arm_group is None:
            raise ValueError("配置中缺少 arm 组，请检查 groups 配置")

        self._n = self._arm_group.num_joints
        self._dt = dt
        self._model = load_robot_model()
        self._end_frame_id = get_end_effector_frame_id(self._model)
        self._data = self._model.createData()

        self._traj_params = TrajPlanParams(dt=dt, profile=profile)
        self._ik_solver_params = TrajIKParams(
            max_iter=200, tolerance=1e-4, step_size=0.5, damping=1e-6,
        )
        self._clik_params = ClikIKParams(
            max_iter=200, tolerance=1e-4, damping=1e-6, step_size=0.8,
        )

        self._q_target: np.ndarray = np.zeros(self._n)
        self._qd_target: np.ndarray = np.zeros(self._n)
        self._gripper_target: float = 0.0
        self._running = False

        self._traj: list[np.ndarray] = []
        self._moving = False
        self._send_thread: Optional[threading.Thread] = None
        self._stop_send = threading.Event()

        self._home_vel: float = 0.5
        self._vlim_override: Optional[np.ndarray] = None

    # ── 生命周期 ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self.rebotarm.connect()
        if self._arm_group:
            if self._arm_control_mode == "mit":
                self._arm_group.mode_mit(
                    kp=self._arm_group._mit_kp,
                    kd=self._arm_group._mit_kd,
                )
            else:
                self._arm_group.mode_pos_vel()
            self._arm_group.enable()
        if self._has_gripper:
            self._gripper_group.mode_mit()
            self._gripper_group.enable()
        self.rebotarm.start_control_loop(self._loop_cb)
        self._running = True

    def end(self) -> None:
        if not self._running:
            return
        self.safe_home()
        self.rebotarm.disconnect()
        self._running = False

    def __enter__(self) -> "RebotArmEndPose":
        return self

    def __exit__(self, *args) -> None:
        self.end()

    # ── 公共 API ───────────────────────────────────────────────────────────

    def set_gripper_target(self, pos: float) -> None:
        self._gripper_target = float(pos)

    def open_gripper(self) -> None:
        if self._has_gripper:
            self._gripper_group._mit_kp.fill(0)
            self._gripper_group._mit_kd.fill(0)
            pv = self._gripper_group._pv_vlim
            self._gripper_target = float(pv[0]) if pv.size > 0 else 0.0

    def close_gripper(self) -> None:
        if self._has_gripper:
            self._gripper_target = 0.0

    def safe_home(
        self,
        max_vel: float = 0.5,
        send_freq: float = 50.0,
        settle_thresh: float = 0.01,
        timeout: float = 15.0,
    ) -> None:
        if not self._running:
            return

        q_curr, _, _ = self.rebotarm.get_state()
        q_curr = q_curr[: self._n]
        q_start = q_curr.copy()

        home_pos = np.zeros(self._n)
        q_err = np.abs(home_pos - q_start)
        max_err = float(np.max(q_err))
        if max_err < 0.01:
            return

        t_ramp = max_err / max_vel
        t_total = t_ramp * 2.0
        dt_send = 1.0 / send_freq
        num_steps = max(2, int(t_total / dt_send))

        t = np.linspace(0, t_total, num_steps)
        traj = np.zeros((num_steps, self._n))
        for i in range(self._n):
            err_i = home_pos[i] - q_start[i]
            s = t / t_total
            # 最小jerk (minimum jerk) 轨迹:
            #   q(s) = q0 + Δq * (10s³ - 15s⁴ + 6s⁵)
            # 速度: v(s) = Δq/t_total * (30s² - 60s³ + 30s⁴) → 在 s=0 和 s=1 处均为零
            traj[:, i] = q_start[i] + err_i * (10.0 * s ** 3 - 15.0 * s ** 4 + 6.0 * s ** 5)

        interval = t_total / num_steps if num_steps > 0 else dt_send
        deadline = time.monotonic() + timeout
        self._vlim_override = np.full(self._n, max_vel, dtype=np.float64)
        for i in range(num_steps):
            if time.monotonic() > deadline:
                print("[safe_home] 轨迹发送超时")
                break
            self._q_target[:] = traj[i]
            time.sleep(interval)

        self._q_target[:] = 0.0
        settle_deadline = time.monotonic() + 3.0
        while time.monotonic() < settle_deadline:
            q_now, _, _ = self.rebotarm.get_state()
            if np.max(np.abs(q_now[: self._n])) < settle_thresh:
                break
            time.sleep(self._dt)
        self._vlim_override = None

    def move_to_ik(
        self,
        x: float,
        y: float,
        z: float,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
    ) -> bool:
        if not self._running:
            return False

        q_curr, _, _ = self.rebotarm.get_state()
        q_curr = pad_q_for_model(self._model, q_curr, self._n)
        T_target = pos_rot_to_se3(
            np.array([x, y, z]), roll=roll, pitch=pitch, yaw=yaw,
        )

        result = solve_ik(
            self._model, self._data, self._end_frame_id,
            T_target, q_curr, self._ik_solver_params,
            controlled_joints=self._n,
        )
        if not result.success:
            print(f"[RebotArmEndPose/IK] IK 未收敛  err={result.error:.3e}")
            return False

        self._q_target = result.q[:self._n].copy()
        return True

    def move_to_traj(
        self,
        x: float,
        y: float,
        z: float,
        roll: float = 0.0,
        pitch: float = 0.0,
        yaw: float = 0.0,
        duration: float = 2.0,
    ) -> bool:
        if not self._running:
            return False

        q_start, _, _ = self.rebotarm.get_state()
        q_start = pad_q_for_model(self._model, q_start, self._n)

        T_target = pos_rot_to_se3(
            np.array([x, y, z]), roll=roll, pitch=pitch, yaw=yaw,
        )

        ik_result = solve_ik(
            self._model, self._data, self._end_frame_id,
            T_target, q_start, self._ik_solver_params,
            controlled_joints=self._n,
        )
        if not ik_result.success:
            print(f"[RebotArmEndPose/Traj] IK 失败  err={ik_result.error:.4f}")
            return False

        q_end = ik_result.q
        q_end_padded = pad_q_for_model(self._model, q_end, self._n)

        T_start = compute_fk(self._model, q_start)[2]
        T_end = compute_fk(self._model, q_end_padded)[2]

        if duration <= 0:
            dist = float(np.linalg.norm(T_target.translation() - T_start.translation()))
            duration = max(1.0, dist / 0.1)

        cart_traj = plan_cartesian_geodesic_trajectory(
            T_start, T_end, duration, self._traj_params,
        )

        joint_traj = track_trajectory(
            self._model, self._end_frame_id,
            cart_traj.trajectory, q_start, self._clik_params,
            null_gain=0.1,
        )
        if not joint_traj:
            print("[RebotArmEndPose/Traj] 轨迹为空")
            return False

        pts = [pt.q[: self._n].copy() for pt in joint_traj]

        self._stop_send.set()
        if self._send_thread is not None:
            self._send_thread.join(timeout=5.0)

        self._traj = pts
        self._moving = True
        self._stop_send.clear()
        self._send_thread = threading.Thread(
            target=self._send_loop, args=(duration,), daemon=True,
        )
        self._send_thread.start()
        return True

    # ── 控制循环 ───────────────────────────────────────────────────────────

    def _loop_cb(self, _: RebotArm, dt: float) -> None:
        if self._arm_group:
            if self._arm_control_mode == "mit":
                tau_ff = np.zeros(self._n)
                if self._use_gravity_ff:
                    q_now = self._arm_group.get_positions(request_feedback=False)
                    q_now = pad_q_for_model(self._model, q_now, self._n)
                    tau_ff = compute_generalized_gravity(self._model, q_now, self._data)[: self._n]
                    tau_ff[1] *= 1.55  # joint2 额外补偿
                    tau_ff[2] *= 1.55  # joint3 额外补偿
                    
                self._arm_group.send_mit(
                    self._q_target,
                    vel=self._qd_target,
                    kp=self._arm_group._mit_kp,
                    kd=self._arm_group._mit_kd,
                    tau=tau_ff,
                )
            else:
                vlim = (
                    self._vlim_override
                    if self._vlim_override is not None
                    else self._arm_group._pv_vlim
                )
                self._arm_group.send_pos_vel(self._q_target, vlim=vlim)
        if self._has_gripper:
            self._gripper_group.send_mit(
                np.array([self._gripper_target]),
                kp=self._gripper_group._mit_kp,
                kd=self._gripper_group._mit_kd,
            )

    # ── 轨迹发送线程 ──────────────────────────────────────────────────────

    def _send_loop(self, duration: float) -> None:
        n = len(self._traj)
        interval = duration / n if n > 0 else self._dt
        for i in range(n):
            if self._stop_send.is_set():
                return
            self._q_target[:] = self._traj[i]
            time.sleep(interval)
        self._moving = False
