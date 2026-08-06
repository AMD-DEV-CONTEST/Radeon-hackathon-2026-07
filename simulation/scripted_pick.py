"""Scripted top-down pick-and-place for the SO-101, used to generate demos.

Approach follows the working MuJoCo reference in ggand0/pick-101
(``tests/test_topdown_pick.py``, blog: https://ggando.com/blog/so101-rl-lift/):

  * IK targets the jaw tip (``gripperframe`` local offset), not graspframe
  * Lock ``wrist_flex`` / ``wrist_roll`` at π/2 for top-down; solve only the
    first 3 arm DOFs with position-only IK
  * Offset the target in Y to compensate for the asymmetric fixed finger
  * MJCF gripper: low angle ≈ closed, high angle ≈ open (pick-101 maps
    ``gripper_closed=-0.8`` → ~0 rad, ``gripper_open=0.3`` → ~1.1 rad)

Requires Genesis; run on the Radeon machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from simulation import so101
from simulation.genesis_env import BASKET_HOME, BASKET_SIZE, CUBE_SIZE, TABLE_TOP_Z
from simulation.grasp_control import (
    ContactSummary,
    ConvergenceWindow,
    classify_finger_pad_contacts,
    local_point_world,
)

# Heights from pick-101 test_topdown_pick.py (3 cm cube).
PREGRASP_CLEARANCE = 0.03  # 30 mm above grasp height
GRASP_Z_OFFSET = 0.005     # 5 mm above cube center
# With wrist_roll=π/2, fingers spread along world Y; static finger needs this.
FINGER_WIDTH_OFFSET_Y = -0.015
LIFT_Z = TABLE_TOP_Z + 0.12
PLACE_Z = TABLE_TOP_Z + BASKET_SIZE[2] + 0.05
CLOSE_RAMP_STEPS = 250
CLOSE_LOG_INTERVAL = 25
# Tighten only slightly from the measured jaw position at first pad contact.
# The commanded ramp leads the physical jaw by about 0.09 rad on Genesis, so
# tightening from the scheduled command over-closes and ejects the cube.
CONTACT_TIGHTEN = 0.02
TIGHTEN_STEPS = 80
CONTACT_LOST_MAX_STEPS = 5

# Locked wrist pose for top-down (pick-101 / ECE4560).
WRIST_FLEX_TOPDOWN = float(np.pi / 2)
WRIST_ROLL_TOPDOWN = float(np.pi / 2)
# IK only over shoulder_pan, shoulder_lift, elbow_flex.
IK_DOFS = [0, 1, 2]

MOVE_MAX_DQ = 0.02  # rad per control step
MOVE_MIN_STEPS = 30
TCP_POS_TOL = 0.006
MOVE_STABLE_STEPS = 5
MOVE_SETTLE_MAX_STEPS = 120


@dataclass(frozen=True)
class MotionResult:
    converged: bool
    arm_goal: np.ndarray
    target_tip: np.ndarray
    actual_tip: np.ndarray
    error_vector: np.ndarray
    tcp_error: float
    ik_error: float
    joint_error: float
    interp_steps: int
    settle_steps: int


def _to_np(x) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x).reshape(-1)


def _tip_to_link_pos(tip_pos: np.ndarray) -> np.ndarray:
    """Fallback link target when Genesis has no ``local_point`` (Z-up tip)."""
    link = np.asarray(tip_pos, dtype=np.float64).reshape(3).copy()
    link[2] += so101.EE_TIP_OFFSET
    return link


def _with_finger_offset(tip_pos: np.ndarray) -> np.ndarray:
    """Apply pick-101 asymmetric-finger Y offset."""
    p = np.asarray(tip_pos, dtype=np.float64).reshape(3).copy()
    p[1] += FINGER_WIDTH_OFFSET_Y
    return p


def _unexpected_ik_keyword(exc: TypeError) -> str | None:
    match = re.search(
        r"got an unexpected keyword argument ['\"]([^'\"]+)['\"]$", str(exc)
    )
    if match is None:
        return None
    keyword = match.group(1)
    return keyword if keyword in {"return_error", "init_qpos", "local_point"} else None


def _resolve_pad_geom(link, *, link_name: str):
    candidates = [
        geom
        for geom in getattr(link, "geoms", ())
        if getattr(geom, "n_verts", None) == 8
        and bool(getattr(geom, "contype", 0))
        and bool(getattr(geom, "conaffinity", 0))
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Required robot link '{link_name}' must expose exactly one active "
            f"8-vertex box pad geom; found {len(candidates)}."
        )
    return candidates[0]


class ScriptedPickPlace:
    """Runs a scripted pick-place on a built SceneBundle, optionally recording steps."""

    def __init__(self, bundle):
        self.bundle = bundle
        self.robot = bundle.robot
        self.ee_link = bundle._ee_link
        if self.ee_link is None:
            raise RuntimeError("No EE link resolved; cannot run IK. Fix EE_LINK_CANDIDATES.")
        try:
            self.fixed_finger_link = self.robot.get_link("gripper")
        except Exception as exc:  # noqa: BLE001 -- Genesis raises for unknown links
            raise RuntimeError(
                "Required robot link 'gripper' is missing; bilateral contact "
                "detection requires both finger links."
            ) from exc
        if self.fixed_finger_link is None:
            raise RuntimeError(
                "Required robot link 'gripper' is missing; bilateral contact "
                "detection requires both finger links."
            )
        try:
            self.moving_finger_link = self.robot.get_link("moving_jaw_so101_v1")
        except Exception as exc:  # noqa: BLE001 -- Genesis raises for unknown links
            raise RuntimeError(
                "Required robot link 'moving_jaw_so101_v1' is missing; bilateral "
                "contact detection requires both finger links."
            ) from exc
        if self.moving_finger_link is None:
            raise RuntimeError(
                "Required robot link 'moving_jaw_so101_v1' is missing; bilateral "
                "contact detection requires both finger links."
            )
        self.fixed_finger_geom = _resolve_pad_geom(
            self.fixed_finger_link, link_name="gripper"
        )
        self.moving_finger_geom = _resolve_pad_geom(
            self.moving_finger_link, link_name="moving_jaw_so101_v1"
        )
        self.fixed_finger_geom_idx = self.fixed_finger_geom.idx
        self.moving_finger_geom_idx = self.moving_finger_geom.idx
        print(
            "[pick] contact pads "
            f"fixed_geom={self.fixed_finger_geom_idx} "
            f"moving_geom={self.moving_finger_geom_idx}"
        )
        self._ik_api_path = None
        self._close_failure_reason = None
        self._grasp_gripper_cmd = None

    def _lock_wrists(self, arm3: np.ndarray) -> np.ndarray:
        """Build a 5-D arm target with wrists locked to the top-down pose."""
        a = _to_np(arm3)[:3]
        return np.array(
            [a[0], a[1], a[2], WRIST_FLEX_TOPDOWN, WRIST_ROLL_TOPDOWN],
            dtype=np.float64,
        )

    def _record_ik_api_path(self, path: str, *, residual: bool) -> None:
        if self._ik_api_path is None:
            self._ik_api_path = path
            print(f"[pick] IK api path={path} residual={residual}")

    def _ik(self, tip_pos: np.ndarray) -> tuple[np.ndarray, float]:
        """Position-only IK for the jaw tip, solving the first 3 arm DOFs.

        Mirrors pick-101: site ``gripperframe``, wrists locked, no orientation IK.
        """
        tip = _with_finger_offset(tip_pos)
        call_kwargs = dict(
            link=self.ee_link,
            dofs_idx_local=IK_DOFS,
            max_samples=80,
            max_solver_iters=40,
        )
        # Seed IK with wrists already locked (pick-101 sets qpos[3]=qpos[4]=π/2
        # before solving). Otherwise local_point is evaluated under the wrong R.
        init = _to_np(self.robot.get_qpos()).astype(np.float64).copy()
        if init.size >= 5:
            init[3] = WRIST_FLEX_TOPDOWN
            init[4] = WRIST_ROLL_TOPDOWN
        call_kwargs.update(
            local_point=[0.0, 0.0, -so101.EE_TIP_OFFSET],
            init_qpos=init,
            return_error=True,
        )
        pos = tip
        while True:
            try:
                result = self.robot.inverse_kinematics(pos=pos, **call_kwargs)
                break
            except TypeError as exc:
                keyword = _unexpected_ik_keyword(exc)
                if keyword is None or keyword not in call_kwargs:
                    raise
                del call_kwargs[keyword]
                if keyword == "local_point":
                    pos = _tip_to_link_pos(tip)

        residual = "return_error" in call_kwargs
        if residual:
            q, error_pose = result
        else:
            q = result
            error_pose = None
        path = "local_point" if "local_point" in call_kwargs else "link_origin"
        if "init_qpos" in call_kwargs:
            path += "_init"
        self._record_ik_api_path(path, residual=residual)
        ik_error = (
            float(np.linalg.norm(_to_np(error_pose)[:3]))
            if residual
            else float("nan")
        )
        return _to_np(q), ik_error

    def _cmd(self, arm5: np.ndarray, gripper: float, *, recorder) -> None:
        arm_values = _to_np(arm5)
        arm = (
            self._lock_wrists(arm_values)
            if len(arm_values) < 5
            else arm_values[:5].copy()
        )
        arm[3] = WRIST_FLEX_TOPDOWN
        arm[4] = WRIST_ROLL_TOPDOWN
        action = np.concatenate([arm, [gripper]])
        if recorder is not None:
            recorder.on_step(action)
        self.robot.control_dofs_position(
            np.concatenate([arm, [gripper]]), np.arange(so101.N_DOF)
        )
        self.bundle.scene.step()
        self.bundle.update_wrist_cam()

    def _move_to(self, tip_pos, *, phase, gripper, recorder=None) -> MotionResult:
        """Velocity-limited interpolation to the IK goal (wrists stay locked)."""
        q_goal, ik_error = self._ik(tip_pos)
        target_tip = _with_finger_offset(tip_pos)
        arm_goal = self._lock_wrists(q_goal[:3])
        arm_start = _to_np(self.robot.get_dofs_position(so101.ARM_DOF))[:5]
        arm_start[3] = WRIST_FLEX_TOPDOWN
        arm_start[4] = WRIST_ROLL_TOPDOWN
        dist = float(np.max(np.abs(arm_goal[:3] - arm_start[:3])))
        n = max(MOVE_MIN_STEPS, int(np.ceil(dist / MOVE_MAX_DQ))) if dist > 1e-9 else MOVE_MIN_STEPS
        for i in range(1, n + 1):
            arm = arm_start + (arm_goal - arm_start) * (i / n)
            self._cmd(arm, gripper, recorder=recorder)

        window = ConvergenceWindow(TCP_POS_TOL, MOVE_STABLE_STEPS)
        settle_steps = 0
        converged = False
        for settle_steps in range(1, MOVE_SETTLE_MAX_STEPS + 1):
            self._cmd(arm_goal, gripper, recorder=recorder)
            actual_tip = self._tip_pos()
            tcp_error = float(np.linalg.norm(actual_tip - target_tip))
            if window.update(tcp_error):
                converged = True
                break

        measured_arm = _to_np(self.robot.get_dofs_position(so101.ARM_DOF))[:5]
        joint_error = float(np.max(np.abs(measured_arm - arm_goal)))
        error_vector = actual_tip - target_tip
        tcp_error = float(np.linalg.norm(error_vector))
        result = MotionResult(
            converged=converged,
            arm_goal=arm_goal.copy(),
            target_tip=target_tip.copy(),
            actual_tip=actual_tip.copy(),
            error_vector=error_vector.copy(),
            tcp_error=tcp_error,
            ik_error=ik_error,
            joint_error=joint_error,
            interp_steps=n,
            settle_steps=settle_steps,
        )
        print(
            f"[pick] motion phase={phase} "
            f"target_tip={target_tip.round(4).tolist()} "
            f"actual_tip={actual_tip.round(4).tolist()} "
            f"error_vec={error_vector.round(4).tolist()} "
            f"tcp_err={tcp_error:.4f} ik_err={ik_error:.4f} "
            f"joint_err={joint_error:.4f} interp_steps={n} "
            f"settle_steps={settle_steps} converged={converged}"
        )
        return result

    def _hold(self, steps: int, *, gripper, recorder=None) -> None:
        arm = _to_np(self.robot.get_dofs_position(so101.ARM_DOF))[:5]
        arm[3] = WRIST_FLEX_TOPDOWN
        arm[4] = WRIST_ROLL_TOPDOWN
        for _ in range(steps):
            self._cmd(arm, gripper, recorder=recorder)

    def _gripper_q(self) -> float:
        q = _to_np(self.robot.get_dofs_position(so101.GRIPPER_DOF))
        return float(q.reshape(-1)[0])

    def _finger_contacts(self, cube) -> ContactSummary:
        contacts = self.robot.get_contacts(with_entity=cube)
        return classify_finger_pad_contacts(
            contacts,
            fixed_geom_idx=self.fixed_finger_geom_idx,
            moving_geom_idx=self.moving_finger_geom_idx,
        )

    def _log_close_step(
        self,
        *,
        state: str,
        step: int,
        gripper_cmd: float,
        summary: ContactSummary,
        target_tip: np.ndarray,
    ) -> None:
        gripper_q = self._gripper_q()
        tcp_err = float(np.linalg.norm(self._tip_pos() - target_tip))
        print(
            f"[pick] close state={state} step={step} "
            f"gripper_cmd={gripper_cmd:.3f} gripper_q={gripper_q:.3f} "
            f"fixed_contact={summary.fixed} moving_contact={summary.moving} "
            f"contacts={summary.count} max_force={summary.max_force:.3f} "
            f"tcp_err={tcp_err:.4f}"
        )

    def _close_until_contact(
        self, cube, arm_goal, target_tip, recorder=None
    ) -> bool:
        """Ramp the jaw closed, then tighten only after bilateral contact."""
        self._close_failure_reason = None
        self._grasp_gripper_cmd = None
        arm_goal = _to_np(arm_goal)[:5]
        target_tip = _to_np(target_tip)[:3]
        gripper_start = self._gripper_q()
        previous_contacts = None
        total_step = 0

        for ramp_step in range(1, CLOSE_RAMP_STEPS + 1):
            total_step += 1
            fraction = ramp_step / CLOSE_RAMP_STEPS
            gripper_cmd = gripper_start + (
                so101.GRIPPER_CLOSE - gripper_start
            ) * fraction
            self._cmd(arm_goal, gripper_cmd, recorder=recorder)
            summary = self._finger_contacts(cube)
            contact_state = (summary.fixed, summary.moving)
            if (
                total_step % CLOSE_LOG_INTERVAL == 0
                or contact_state != previous_contacts
            ):
                self._log_close_step(
                    state="ramp",
                    step=total_step,
                    gripper_cmd=gripper_cmd,
                    summary=summary,
                    target_tip=target_tip,
                )
            previous_contacts = contact_state
            if not summary.bilateral:
                continue

            self._log_close_step(
                state="contact_acquired",
                step=total_step,
                gripper_cmd=gripper_cmd,
                summary=summary,
                target_tip=target_tip,
            )
            contact_gripper_q = self._gripper_q()
            distance_to_close = so101.GRIPPER_CLOSE - contact_gripper_q
            tighten_delta = min(CONTACT_TIGHTEN, abs(distance_to_close))
            tighten_target = (
                contact_gripper_q + np.sign(distance_to_close) * tighten_delta
            )
            print(
                f"[pick] close plan step={total_step} "
                f"contact_cmd={gripper_cmd:.3f} contact_q={contact_gripper_q:.3f} "
                f"tighten_target={tighten_target:.3f} "
                f"tighten_delta={tighten_delta:.3f}"
            )
            lost_steps = 0
            previous_contacts = None
            for tighten_step in range(1, TIGHTEN_STEPS + 1):
                total_step += 1
                fraction = tighten_step / TIGHTEN_STEPS
                tighten_cmd = gripper_cmd + (tighten_target - gripper_cmd) * fraction
                self._cmd(arm_goal, tighten_cmd, recorder=recorder)
                summary = self._finger_contacts(cube)
                contact_state = (summary.fixed, summary.moving)
                lost_steps = 0 if summary.bilateral else lost_steps + 1
                if (
                    total_step % CLOSE_LOG_INTERVAL == 0
                    or contact_state != previous_contacts
                ):
                    self._log_close_step(
                        state="tighten",
                        step=total_step,
                        gripper_cmd=tighten_cmd,
                        summary=summary,
                        target_tip=target_tip,
                    )
                previous_contacts = contact_state
                if lost_steps > CONTACT_LOST_MAX_STEPS:
                    self._close_failure_reason = "contact_lost"
                    self._grasp_gripper_cmd = None
                    self._log_close_step(
                        state="contact_lost",
                        step=total_step,
                        gripper_cmd=tighten_cmd,
                        summary=summary,
                        target_tip=target_tip,
                    )
                    return False

            if not summary.bilateral:
                self._close_failure_reason = "contact_lost"
                self._grasp_gripper_cmd = None
                self._log_close_step(
                    state="contact_lost",
                    step=total_step,
                    gripper_cmd=tighten_target,
                    summary=summary,
                    target_tip=target_tip,
                )
                return False
            self._log_close_step(
                state="success",
                step=total_step,
                gripper_cmd=tighten_target,
                summary=summary,
                target_tip=target_tip,
            )
            self._grasp_gripper_cmd = float(tighten_target)
            return True

        self._close_failure_reason = "no_bilateral_contact"
        self._grasp_gripper_cmd = None
        self._log_close_step(
            state="no_bilateral_contact",
            step=total_step,
            gripper_cmd=so101.GRIPPER_CLOSE,
            summary=summary,
            target_tip=target_tip,
        )
        return False

    def _ee_pos(self) -> np.ndarray:
        return _to_np(self.ee_link.get_pos())[:3]

    def _tip_pos(self) -> np.ndarray:
        return local_point_world(
            _to_np(self.ee_link.get_pos())[:3],
            _to_np(self.ee_link.get_quat())[:4],
            [0.0, 0.0, -so101.EE_TIP_OFFSET],
        )

    def _abort(self, reason: str, recorder) -> bool:
        print(f"[pick] abort reason={reason}")
        self._hold(30, gripper=so101.GRIPPER_OPEN, recorder=recorder)
        return False

    def run(self, color: str, *, recorder=None) -> bool:
        """Pick the ``color`` cube and place it into the basket. Returns success."""
        cube = self.bundle.cubes[color]
        cube_pos = _to_np(cube.get_pos())

        # Tip targets (world); Y asymmetry applied inside _ik.
        grasp = np.array(
            [cube_pos[0], cube_pos[1], cube_pos[2] + GRASP_Z_OFFSET], dtype=np.float64
        )
        pregrasp = grasp.copy()
        pregrasp[2] += PREGRASP_CLEARANCE

        # 1) Above cube, jaw open.
        pregrasp_result = self._move_to(
            pregrasp,
            phase="pregrasp",
            gripper=so101.GRIPPER_OPEN,
            recorder=recorder,
        )
        if not pregrasp_result.converged:
            return self._abort("pregrasp_not_converged", recorder)
        # 2) Descend.
        grasp_result = self._move_to(
            grasp,
            phase="grasp",
            gripper=so101.GRIPPER_OPEN,
            recorder=recorder,
        )
        if not grasp_result.converged:
            return self._abort("grasp_not_converged", recorder)
        # 3) Close (MJCF low angle) until both fingers contact the cube.
        if not self._close_until_contact(
            cube, grasp_result.arm_goal, grasp_result.target_tip, recorder
        ):
            return self._abort(self._close_failure_reason, recorder)
        grasp_gripper_cmd = self._grasp_gripper_cmd
        if grasp_gripper_cmd is None:
            raise RuntimeError("Successful close did not preserve its gripper command")
        z_before_lift = float(_to_np(cube.get_pos())[2])
        gq = self._gripper_q()
        actual_tip = self._tip_pos()
        target_tip = grasp_result.target_tip
        cube_now = _to_np(cube.get_pos())
        print(
            f"[pick] at_close color={color} gripper_q={gq:.3f} "
            f"cube={cube_now.round(3).tolist()} "
            f"target_tip={target_tip.round(3).tolist()} "
            f"actual_tip={actual_tip.round(3).tolist()} "
            f"target_xy_err={float(np.linalg.norm(actual_tip[:2] - target_tip[:2])):.3f} "
            f"target_z_err={float(actual_tip[2] - target_tip[2]):.3f} "
            f"cube_xy_err={float(np.linalg.norm(actual_tip[:2] - cube_now[:2])):.3f} "
            f"cube_z_err={float(actual_tip[2] - cube_now[2]):.3f}"
        )

        # 4) Lift.
        lift = np.array([grasp[0], grasp[1], LIFT_Z], dtype=np.float64)
        self._move_to(
            lift, phase="lift", gripper=grasp_gripper_cmd, recorder=recorder
        )
        z_after_lift = float(_to_np(cube.get_pos())[2])
        if z_after_lift < z_before_lift + 0.02:
            print(
                f"[pick] grasp miss color={color} gripper_q={gq:.3f} "
                f"(gripper_cmd={grasp_gripper_cmd:.3f}, "
                f"close_limit={so101.GRIPPER_CLOSE}, open={so101.GRIPPER_OPEN}) "
                f"cube_z {z_before_lift:.3f}->{z_after_lift:.3f}"
            )

        # 5) Over basket.
        bx, by = BASKET_HOME
        above = np.array([bx, by, PLACE_Z], dtype=np.float64)
        self._move_to(
            above, phase="place", gripper=grasp_gripper_cmd, recorder=recorder
        )

        # 6) Release.
        self._hold(30, gripper=so101.GRIPPER_OPEN, recorder=recorder)

        # 7) Retreat.
        retreat = np.array([bx, by, PLACE_Z + 0.05], dtype=np.float64)
        self._move_to(
            retreat, phase="retreat", gripper=so101.GRIPPER_OPEN, recorder=recorder
        )
        self._hold(40, gripper=so101.GRIPPER_OPEN, recorder=recorder)

        ok = self._success(color)
        if not ok:
            final = _to_np(cube.get_pos())
            ee = self._ee_pos()
            print(
                f"[pick] fail diag color={color} cube={final.round(3).tolist()} "
                f"basket=[{bx:.3f},{by:.3f}] ee_link={ee.round(3).tolist()} "
                f"horiz={float(np.linalg.norm(final[:2] - np.array([bx, by]))):.3f} "
                f"gripper_q={self._gripper_q():.3f}"
            )
        return ok

    def _success(self, color: str) -> bool:
        cube_pos = _to_np(self.bundle.cubes[color].get_pos())
        bx, by = BASKET_HOME
        horizontal = float(np.linalg.norm(cube_pos[:2] - np.array([bx, by])))
        rim_radius = 0.5 * min(BASKET_SIZE[0], BASKET_SIZE[1])
        within = horizontal < rim_radius
        below_rim = cube_pos[2] < TABLE_TOP_Z + BASKET_SIZE[2]
        return bool(within and below_rim and cube_pos[2] > TABLE_TOP_Z)
