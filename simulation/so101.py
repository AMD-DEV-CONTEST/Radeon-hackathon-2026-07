"""SO-101 robot constants: joints, gains, home pose, gripper, cameras.

The SO-101 follower arm is a 6-DOF manipulator: 5 arm joints + 1 gripper jaw
(vs the Franka Panda's 7+2). Joint names follow the SO-ARM100 URDF/MJCF
convention. The action / observation vectors used throughout this project are
6-D (5 arm joint targets + 1 gripper joint target), in this order:

    [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper]

IMPORTANT (needs on-machine calibration): the PD gains, torque limits, home
pose, gripper open/close values and grasp heights below are conservative
defaults inferred from the SO-101 spec (6x STS3215 servos, 1/345 gearing). They
are the right *shape* but the exact magnitudes should be tuned on the Radeon
machine against the actual loaded model. Each such constant is marked TODO.
"""

from __future__ import annotations

import numpy as np

# == Robot model file (populated by scripts/setup_so101_assets.py) ==
# The MJCF is preferred (Genesis handles MuJoCo contacts/actuators cleanly); the
# URDF is the fallback. simulation/genesis_env.py resolves whichever exists.
MJCF_CANDIDATES = ("so101_new_calib.xml", "scene.xml", "so101.xml")
URDF_CANDIDATES = ("so101_new_calib.urdf", "so101_old_calib.urdf")

# == Joint layout ==
ARM_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
]
GRIPPER_JOINT_NAME = "gripper"
JOINT_NAMES = ARM_JOINT_NAMES + [GRIPPER_JOINT_NAME]

N_ARM_DOF = len(ARM_JOINT_NAMES)  # 5
N_DOF = len(JOINT_NAMES)  # 6

ARM_DOF = np.arange(N_ARM_DOF)  # [0..4]
GRIPPER_DOF = np.arange(N_ARM_DOF, N_DOF)  # [5]

# == Base placement on the tabletop ==
# SO-101 is a small desktop arm (~0.05–0.55 m forward reach, ~0.35 m above base).
# Mount at the rear (-x) edge of the table facing +x. z MUST match
# ``genesis_env.TABLE_TOP_Z`` (0.75); a floor mount (z=0) cannot reach the cubes.
# TODO: verify against the loaded model's origin (some URDFs put the base frame
# at the mounting plate rather than the table contact).
SO101_POS = (-0.05, 0.0, 0.75)
SO101_EULER = (0.0, 0.0, 0.0)

# == Home pose (radians), a safe "ready" configuration above the table ==
# Wrists at π/2 match pick-101 top-down lock; gripper starts open (high MJCF angle).
HOME_QPOS = (0.0, -0.9, 1.1, float(np.pi / 2), float(np.pi / 2), 1.7)

# == PD gains + torque limits (per joint) ==
# Match so101_new_calib.xml STS3215 actuator forcerange (±3.35) and a moderate
# position gain — oversized kp/force fought the MJCF actuators and stalled motion.
KP = (80.0, 80.0, 80.0, 60.0, 40.0, 30.0)
KV = (8.0, 8.0, 8.0, 6.0, 4.0, 3.0)
# Arm actuators ±3.35; gripper ±10 matches pick-101 so101_new_calib.xml.
FORCE_MIN = (-3.35, -3.35, -3.35, -3.35, -3.35, -10.0)
FORCE_MAX = (3.35, 3.35, 3.35, 3.35, 3.35, 10.0)

# == Gripper ==
# so101_new_calib.xml range ≈ [-0.175, 1.745]. Verified against ggand0/pick-101
# (test_topdown_pick.py maps action -1→ctrl low / +1→ctrl high, and uses
# gripper_closed=-0.8 ≈ 0 rad, gripper_open=0.3 ≈ 1.1 rad):
#   low MJCF angle  ≈ closed
#   high MJCF angle ≈ open
# Official SO-ARM100 README also documents LeRobot percent as 0=closed, 100=open.
GRIPPER_OPEN = 1.7
GRIPPER_CLOSE = 0.0

# == End-effector link used for IK (the gripper/jaw mount) ==
# Prefer the MJCF ``gripper`` body. Its tip site ``gripperframe`` sits at about
# (0, 0, -0.098) in the body frame — i.e. along body -Z.
EE_LINK_CANDIDATES = ("gripper", "wrist_roll", "gripper_link", "moving_jaw_so101_v1")
# Distance from gripper-link origin to the jaw tip (meters). When the link Z
# aligns with world Z, tip = link_pos - (0, 0, EE_TIP_OFFSET).
EE_TIP_OFFSET = 0.098

# == Cameras (matched to an Intel RealSense D435i RGB module, as in the sibling demo) ==
# World camera: fixed third-person top-down-ish view of the tabletop workspace.
WORLD_CAM_RES = (640, 480)
WORLD_CAM_FOV = 42  # vertical FOV (deg)
# Wrist camera: eye-in-hand, attached to the EE link.
WRIST_CAM_RES = (640, 480)
WRIST_CAM_FOV = 42
WRIST_CAM_NEAR = 0.01
WRIST_CAM_FAR = 20.0
# Camera pose relative to the EE link frame. TODO: calibrate offset to the model.
WRIST_CAM_OFFSET_POS = (0.02, 0.0, 0.02)
WRIST_CAM_OFFSET_EULER = (180.0, 0.0, 0.0)


def home_qpos(n_envs: int = 1) -> np.ndarray:
    """Return the home qpos, tiled for a batched (n_envs>1) build."""
    q = np.asarray(HOME_QPOS, dtype=np.float64)
    return np.tile(q, (n_envs, 1)) if n_envs > 1 else q
