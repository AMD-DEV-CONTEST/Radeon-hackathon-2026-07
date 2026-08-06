# SO-101 Grasp Reliability Design

## Problem

Scripted dataset collection currently misses every cube even though the gripper
reaches its commanded closed position. The logged cube height does not increase
by the 20 mm lift threshold, while the approximate tool-center-point (TCP)
position is commonly 20–30 mm away from a 30 mm cube. The current 40 mm motion
warning threshold therefore permits errors that are already fatal to grasping.

The existing diagnostic is also ambiguous: it compares the TCP with the raw
cube center even though IK intentionally applies a -15 mm Y offset, and it
subtracts the fingertip offset along world Z instead of rotating that offset by
the end-effector orientation.

## Goals

- Require the measured TCP to converge before closing the gripper.
- Close gradually and require contact from both the fixed and moving fingers.
- Emit enough structured diagnostics to separate IK, actuator tracking, TCP
  calibration, and collision/contact failures.
- Abort failed grasps before producing meaningless lift/place trajectories.
- Preserve the existing six-dimensional action/state and dataset schema.

## Non-goals

- Replacing Genesis IK with a custom Jacobian or DLS controller.
- Adding a general-purpose motion planner.
- Changing the learned-policy interface or recorded dataset format.
- Tuning scene randomization, camera placement, or basket geometry.

## Selected Approach

Keep the existing one-shot Genesis IK and joint interpolation, then add a
bounded convergence phase driven by measured state. During convergence, the
controller continues commanding the solved joint target until the measured TCP
stays within tolerance for several consecutive steps or a maximum step count is
reached. A failed convergence check aborts the attempt with the gripper open.

After convergence, ramp the gripper command from its measured opening toward
the closed limit while continuing to command the grasp arm target. Query
Genesis contacts between the robot and target cube every step. Classify contacts
by the fixed-finger link and moving-jaw link. Only bilateral contact permits a
small, gradual tightening phase followed by lift. Exhausting the closing range
without bilateral contact is a grasp failure.

This is preferred over merely increasing settle time because it establishes
explicit phase invariants, and over a new Cartesian servo because it keeps the
change focused and compatible with the existing controller.

## Components

### Geometry and convergence utilities

Add a Genesis-independent module containing:

- quaternion-based transformation of a link-local point into world space;
- TCP position and position-error calculation;
- stable-convergence tracking for consecutive in-tolerance samples;
- contact classification from Genesis contact arrays and known link indices.

These functions are independently testable without installing Genesis.

### Motion execution

`ScriptedPickPlace._move_to` will:

1. solve IK and retain the requested TCP and joint target;
2. perform the existing velocity-limited joint interpolation;
3. continue commanding the final joint target for a bounded number of steps;
4. calculate the measured TCP using the link position and quaternion;
5. require several consecutive samples within a grasp-scale tolerance;
6. return a structured result containing convergence, residuals, target joint
   values, measured joint values, and step count.

Pre-grasp and grasp motion failures stop the state machine. Lift, place, and
retreat retain bounded execution and diagnostic reporting, but only the grasp
phases gate closing.

### Contact-aware closing

A dedicated close operation will:

1. ramp the command over a bounded number of control steps;
2. hold the converged arm goal throughout the ramp;
3. inspect robot-to-cube contacts after each physics step;
4. detect fixed-finger and moving-finger contact independently;
5. record first bilateral contact and gradually tighten by a bounded amount;
6. fail if bilateral contact never occurs or is lost before tightening ends.

Contact detection uses the public Genesis `RigidEntity.get_contacts` API and
link indices rather than MuJoCo geometry IDs.

## Logging

Motion summary logs will include:

- phase name;
- requested and measured TCP;
- TCP vector and norm error;
- IK solver-reported position residual when available;
- maximum commanded-versus-measured arm joint error;
- interpolation and convergence step counts;
- convergence status.

Closing logs, sampled periodically and at transitions, will include:

- close step, gripper command, and measured gripper position;
- fixed-finger and moving-finger contact flags;
- contact count and maximum contact-force magnitude;
- current TCP residual;
- first-contact and final-tightening summaries.

Failure logs will use explicit reasons such as `pregrasp_not_converged`,
`grasp_not_converged`, `no_bilateral_contact`, and `contact_lost`.

## Error Handling

- Missing moving-jaw link resolution is a construction-time error because
  bilateral contact cannot otherwise be evaluated safely.
- Missing optional IK residual support falls back to measured TCP diagnostics;
  the selected IK API path is logged once.
- Unexpected or empty contact arrays are treated as no finger contact, not as
  success.
- Every failed grasp leaves the gripper open and returns `False`, allowing the
  recorder to discard the attempt through its existing path.

## Testing

Tests will be written before production changes and will cover:

- rotating the local fingertip offset into world coordinates;
- convergence requiring consecutive in-tolerance samples and resetting after
  an out-of-tolerance sample;
- classification of bilateral, unilateral, unrelated, and empty contacts;
- close-phase success only after bilateral contact and failure at exhaustion;
- motion failure preventing the close/lift phases;
- log formatting containing target, measured, residual, joint, and contact
  fields.

The local verification suite will use the standard library where practical so
it can run without Genesis. It will include unit tests, Python syntax
compilation, and `git diff --check`. A five-attempt Genesis simulation remains
the required hardware-environment acceptance test because Genesis is not
installed in the local workspace.

## Acceptance Criteria

- No close command begins after a grasp TCP convergence failure.
- No lift begins without confirmed bilateral finger contact.
- A fully closed gripper with no bilateral contact reports an explicit failure.
- Logs distinguish IK residual, executed TCP residual, joint tracking error,
  and per-finger contact state.
- Unit tests and syntax checks pass locally.
- On the Radeon/Genesis environment, five deterministic attempts produce no
  silent misses; every miss has a phase-specific diagnostic. Successful lifts
  raise the cube center by at least 20 mm before placement.
