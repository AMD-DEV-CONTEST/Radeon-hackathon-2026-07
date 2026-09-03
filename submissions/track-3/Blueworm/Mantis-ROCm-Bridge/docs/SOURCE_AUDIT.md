# Source Contract Audit

## Confirmed from the Mantis LeRobot adapter

- Repository revision: `53953bc9b3c63dfa1689904cc986ae9e09c1d35b`.
- Policy interface: 16 state values and 16 action values.
- Joint order: left arm and virtual gripper first, then right arm and virtual gripper.
- Wrist order: roll, pitch, yaw.
- Cameras: `env_cam` at 320×240 and both wrist cameras at 424×240, all at 30 FPS.
- Nominal control frequency: 30 Hz.
- Action semantics: absolute joint targets, optionally protected by a maximum-relative-target guard.

## Confirmed from the Tron task configuration

- Source policy vector is also 16-dimensional.
- Source wrist order is yaw, pitch, roll; a positional copy into Mantis would silently corrupt actions.
- Source dataset camera order is high, right wrist, left wrist; target LeRobot order is environment, left wrist, right wrist.
- The existing source planner is cuRobo and therefore is not the portable AMD target planner.
- The source reset sampler, three-bowl assignment, expert target geometry, D435 camera parameters, and source-file hashes are frozen in `configs/source-task-stack-bowls-three.json`.
- The legacy evaluator has a one-sided height check and no stability window. It is retained for compatibility only; `competition_strict_v1` is the reporting protocol.

## Confirmed on the 8×4090 source-reference worker

- The deployed task is `stack_bowls_three`, not a completed Mantis replacement.
- The 200-episode source dataset is 9.6 GB; an inspected raw/processed pair had 889/888 frames and finite 16-dimensional state/actions.
- Both gripper channels use the observed normalized range `[0, 1]`.
- Capture geometry is 320×240; the ACT deployment path resizes all three views to 640×480.
- Source control is variable-duration TOPP execution at a 250 Hz physics step, not a fixed-frequency policy loop.
- T4 checkpoints are packaged but have no closed-loop result. T2/T3 ten-episode evidence is 0.4–0.5 success rate.
- Generic LeRobot and Mantis-description worktrees are clean, but no Mantis adapter is deployed in the Tron or generic LeRobot source trees.

## Confirmed from the public Mantis description

- Repository revision: `b1e154e274fa7cfa8ecdeb10e85145d0c998382e`.
- The IK-oriented URDF has 14 arm joints and no gripper joints.
- The full URDF contains two mirrored prismatic clamp joints per gripper.
- The LeRobot adapter exposes only one virtual gripper action per side.
- `package.xml` contains `TODO: License declaration`, and no root license was observed.
- The full URDF references `package://lanchong_description/meshes/...`, while its base, gripper, and neck meshes are stored under `meshes_full/`. A direct package-root audit therefore reports missing meshes.
- The full URDF also exposes actuated mobile-base and neck joints outside the 14 arm plus four physical clamp joints; they must be removed, fixed, or explicitly controlled for the stationary manipulation task.

## Open measurements

- The target resampling rule from variable-duration source TOPP targets to a fixed 30 Hz Genesis loop.
- Mantis joint, velocity, effort, workspace, and maximum-relative-target safety limits.
- Genesis compatibility of collision meshes, mirrored clamp behavior, and fixed-link structure.
- Dataset observation/action statistics after semantic reordering.
- Mantis wrist-camera mount extrinsics.
- Bowl asset licensing and Genesis-compatible materialization.

The virtual-gripper affine equation has passed Genesis numeric, kinematic, and visual checks, but its hardware ROS2 range and sign are still open. Positional joint limits have passed the Genesis ingestion gate; velocity, effort, workspace, and emergency-stop behavior remain unverified.

These items are gates, not implementation details to infer silently.
