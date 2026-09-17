# Sim-to-Real Risk Analysis

This project is evaluated in Genesis, so the reported success rate is a
simulation result rather than a claim of real-robot performance. The following
risks are the main transfer gaps that would need to be measured and calibrated
before deploying the policy on a physical Franka arm.

## Visual Gap

- Camera intrinsics, exposure, white balance, lens distortion, and mounting
  height will differ from the rasterized Genesis cameras.
- Kitchen textures and object colors may be more varied in the real workspace.
- The wrist camera can be partially occluded by the gripper, cable, or the
  object itself.
- Image timing and transport latency can change the apparent object position.

The current mitigation is reproducible brightness scaling and pixel noise
during data generation and evaluation. This is intentionally a small,
controlled augmentation rather than a claim that the full visual gap has been
solved.

The repository now also exposes two controlled sensor-loss tests:

- `--camera-dropout-prob` masks one of the two views with neutral pixels;
- `--occlusion-prob` and `--occlusion-fraction` apply a localized rectangular
  occlusion to the rendered observation.

These tests keep the policy architecture and episode placements fixed. They
measure the cost of missing visual evidence instead of changing the task.
For video evidence, the recorder stores the perturbed policy observations
directly; this keeps the visible stress condition aligned with the input used
for closed-loop inference.

## Contact and Dynamics Gap

- Real friction, restitution, contact compliance, and gripper pad deformation
  are not identical to Genesis parameters.
- The cube may slide, rotate, or rebound differently during approach and
  closure.
- Robot joint backlash, gravity calibration, torque limits, and controller
  bandwidth affect the executed action.

The evaluation already exposes cube friction as an independent parameter. A
calibrated sweep should report success over a friction interval instead of
using one nominal value. The robustness matrix includes low and high friction
conditions as explicit controls.

## Control and Timing Gap

- The policy predicts action chunks, while the real robot executes through a
  lower-level controller with its own interpolation and delay.
- Observation-to-action latency can compound across closed-loop replanning.
- Safety limits may clip actions that are valid in simulation.

Before a hardware trial, the action rate, chunk horizon, smoothing limit,
joint limits, and emergency stop behavior should be matched to the real
controller. `--action-delay-steps` provides a discrete timing stress test for
this gap. The first transfer test should use a low-height, low-speed workspace
and a soft object or guarded fixture.

## Robustness envelope protocol

The matrix runner executes every condition against one fixed placement
manifest. The nominal score is the paired control. For each stressed condition
we report:

```text
robustness_retention = stressed closed-loop success / nominal closed-loop success
```

The resulting curve is evidence about simulation sensitivity, not a real-world
success guarantee. Confidence intervals are Wilson intervals because success
is a binomial episode-level outcome.

Completed paired matrix (20 episodes per condition):

| Condition | Success | Retention |
|---|---:|---:|
| Nominal | 10/20 = 50% | 100% |
| Brightness `[0.85, 1.15]` | 11/20 = 55% | 110% |
| RGB noise, std 4 | 9/20 = 45% | 90% |
| Camera dropout, 50% observations | 4/20 = 20% | 40% |
| Local occlusion, 25% area | 4/20 = 20% | 40% |
| Action delay, 2 steps | 8/20 = 40% | 80% |
| Low friction, 1.2 | 8/20 = 40% | 80% |
| High friction, 1.8 | 11/20 = 55% | 110% |

The 110% rows are sampling noise, not evidence that perturbations improve the
policy. The stronger engineering conclusion is that missing visual evidence
caused the largest measured degradation, followed by timing and low-friction
stress.

## Multi-strength evidence

The single-point matrix is complemented by a 19-point intensity sweep: one
nominal control plus three levels for each stress family, all with 20 episodes
and the same placement manifest.

| Stress family | Levels | Success rates |
|---|---|---|
| Brightness | +/-5%, +/-15%, +/-25% | 40%, 60%, 45% |
| RGB noise | std 2, 4, 8 | 10%, 45%, 15% |
| Local occlusion | 10%, 25%, 40% image side length | 20%, 5%, 0% |
| Action delay | 1, 2, 4 steps | 55%, 55%, 45% |
| Friction low | 1.4, 1.2, 1.0 | 45%, 50%, 65% |
| Friction high | 1.6, 1.8, 2.0 | 60%, 50%, 30% |

The occlusion curve gives the clearest transfer envelope: 20% success at the
lowest tested mask, 5% at the middle level, and 0% at the largest level. The
other curves are intentionally not smoothed; their local increases are
sampling variance from 20 binomial episodes per point.

## Lightweight uncertainty probe

With `--uncertainty-samples 3`, the evaluator runs the same observation through
small visual perturbations and measures the standard deviation of the first
predicted joint action. Above `--uncertainty-threshold`, it can shorten the
action horizon and reduce the action delta. This is a diagnostic and recovery
heuristic, not a calibrated probability of failure; the baseline result is
always reported separately.

In the recorded 10-episode probe, the policy succeeded in 3/10 episodes. The
threshold `0.03` triggered zero uncertain observations and zero replans; mean
action disagreement was `0.00313`. This is a completed diagnostic with a null
trigger result, so it is not presented as a measured robustness improvement.

## Calibration Plan

1. Measure the real camera intrinsics and extrinsics, then reproduce the
   camera pose in Genesis.
2. Calibrate the robot home pose and the table height in the same robot-local
   coordinate frame used by the dataset.
3. Identify cube mass, friction, and gripper contact behavior from short
   scripted trajectories.
4. Replay the same fixed placement manifest in simulation and on hardware.
5. Compare approach error, grasp closure, lift height, and release behavior.
6. Increase placement range and speed only after the guarded test is stable.

## What This Submission Claims

The defensible claim is: the pipeline demonstrates a reproducible,
closed-loop Genesis benchmark running on AMD ROCm, with explicit failure
analysis and documented transfer risks. It does not claim that a real Franka
will achieve the same success rate without calibration.
