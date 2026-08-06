# `stack_bowls_three` Mantis port contract

> Status update (2026-07-24): the later scripted seed-1 runs v90/v91 complete
> transport, placement, release, and strict stabilization, so local CPU G1 is
> now closed. Earlier “G1 open” passages below are retained as historical
> component and negative evidence. Use `docs/EXECUTION_PLAN.md` and
> `configs/mantis-port-config.json` for current status.

## Port identity

This is a `new_robot_same_task` port:

- source embodiment: `tron2_v5_DACH_validing` in RoboTwin/SAPIEN;
- target embodiment: Mantis in Genesis on `gs.amdgpu`;
- shared task identity: `stack_bowls_three`;
- instruction: “stack the three bowls on top of each other”.

The machine-readable source audit is `configs/source-task-stack-bowls-three.json`. It binds the inspected task, base-task, camera, random-pose, configuration, embodiment, instruction, URDF, seed-list, and scene-info files by SHA-256. Those hashes identify read-only evidence; they do not grant permission to redistribute the bowl meshes.

## Baseline reset contract

The baseline reproduces the source distribution before any robustness randomization:

- seed NumPy and PyTorch with the episode seed;
- sample three bowl poses with `x ~ U(-0.3, 0.3)`, `y ~ U(-0.15, 0.15)`, `z = 0.741`, and quaternion `[0.5, 0.5, 0.5, 0.5]`;
- when `abs(x) < 0.15` and `y > 0`, resample `y` from `U(-0.15, 0)`;
- reject a pose when `abs(x) < 0.09`, when its XY distance from `[0, -0.1]` is below 0.13 m, or when its XY distance from an earlier bowl is below 0.13 m;
- sort the accepted poses by ascending `y` and assign `bowl1`, `bowl2`, and `bowl3` in that order;
- keep all source domain-randomization switches off.

The Genesis implementation must first pass this exact-distribution baseline. Camera, mass, and friction perturbations belong to a separately labelled robustness protocol and cannot be mixed into baseline success rates.

`src/mantis_rocm_bridge/stack_bowls_env.py` now implements that reset using `numpy.random.RandomState`. It preserves the source RNG call order, including the otherwise easy-to-miss `uniform(0.741, 0.741)` call for every candidate. Reference seeds `0`, `1`, `42`, and `20260722` are frozen in `configs/stack-bowls-genesis-v1.json`; seed `0` is checked component-for-component against the source sequence.

## Genesis workcell frame and pre-G1 boundary

The fixed-base asset roots Mantis at `pelvis_link`, so loading it at the world origin is not a valid task placement: its neutral wrists are around `z=-0.302 m` while the table is at `z=0.74 m`. The audited source workcell pose from `tron2_v5_DACH_validing/config.yml`, `[0.0, -0.45, 1.18]` with a +90-degree world-Z rotation, was used as the first candidate. Its reset and stack checks passed, but the frontmost seed-0 right-arm grasp missed by 52.1 mm. A separate diagnostic then tested all 30 frozen IK targets at `base_y=-0.35`; all passed, with maximum position and rotation residuals of 0.413 mm and 0.000205 rad. The target scene therefore retains the source X, Z, and yaw while translating Mantis +0.10 m along world Y. This is a simulation embodiment adaptation, not a physical Mantis calibration or task-success result.

`tools/run_genesis_stack_bowls_preflight.py` checks deterministic reset readback, table contact, base-pose readback, and independent full-pose IK targets for both arms. A passing receipt is only pre-G1 evidence. Under the promotion ladder, G1 still requires one complete safe episode with collision-aware motion, actual bowl contact, grasp, transport, placement, and terminal evaluation; teleporting bowls is explicitly invalid.

The current CPU pre-G1 receipt is `mantis-stack-bowls-pre-g1-cpu-20260723-v4` (SHA-256 `4a19a638028a62c04cac8659bfcb7a0b58cc392ebce1bc8760c2bcad6acf3491`). It passes all 30 IK probes across seeds `0`, `1`, `42`, and `20260722`, plus reset, base-pose, table, and wrist-camera gates. It makes no contact-execution or task-success claim.

Single-arm grasp experiments are retained as negative evidence through `mantis-bowl1-contact-cpu-20260723-v15`. Safe staged navigation and symmetric finger contact were achieved, but the original bowl diameter is approximately `0.1355 m`, larger than the Mantis maximum jaw opening of `0.0752 m`; horizontal chord and top-down rim pinches did not transport the bowl. Object scaling is not used in the source-comparable gate.

The opposed whole-bowl bimanual branch is retained as negative transport evidence through `mantis-bimanual-bowl-contact-cpu-20260723-v9` (receipt SHA-256 `83e4735aec242cb3ff750c4a769dcfa1c28f84be9e5ea8ee840571710cfcaec3`). Its staged route first moves and rotates the left arm at clearance, then brings the right arm into the opposed pose. That route is contact-free before approach and has no robot-table, other-bowl, robot self, or non-clamp bowl collision. Both arms maintain clamp-only bowl contact through hold and lift, including with a `0.120 m` TCP half-span, higher arm stiffness, finger friction `5.0`, and a 10-degree inward-downward pad angle. The measured bowl lift is only `2.38e-7 m`, so this branch remains a transport failure and makes no G1 claim.

The local-rim branch first rejected top-down dual pinches: each Mantis wrist collision mesh is `0.150 m` wide along the jaw axis, larger than the bowl's approximately `0.1356 m` diameter. The first tilted route sustained bilateral contact, and GLB/STL A/B probes behaved equivalently, but a force-instrumented rerun showed a mean `-0.115 N` vertical force during hold: the fingers were pressing down on the upper rim.

A signed full-scene search was then expanded to 1120 candidates; 653 passed IK plus table, other-bowl, and self-collision endpoint gates (`mantis-bimanual-converged-rim-hook-scene-gate-stl-cpu-20260723-v5`, receipt `d83536ce762d2696cff1897fa03ceef86d7f925c5878f4f28ba4e0ca916a4156`). Mirrored negative-35-degree wrists at `z=0.81 m` moved the measured contacts below the upper rim and changed the vertical force upward. The best unconverged lift peaked at `0.746 N`; stronger jaw preload reduced support. Scene-gated wrist convergence to `0.110 m` and then `0.105 m` half-span only raised the peak to `0.757 N` and `0.787 N`, respectively, against a nominal `1.843 N` bowl weight. The boundary run `mantis-bimanual-max-converged-under-rim-hook-stl-cpu-20260723-v15` (receipt `0a67757cb25b9ab7a84ab274ba103e705e103f6c60471498aae3c8afb896a102`) retained bilateral contact and all safety gates but moved the bowl by `-1.67e-6 m`. Local friction, closure, height, and convergence tuning is therefore frozen as negative evidence; the next gate requires a licensed finger/tool collision geometry with a true upward-facing support surface. No G1 claim is made.

The follow-on tool branch adds an independently authored box primitive to each selected hook finger without modifying or redistributing the unresolved upstream Mantis meshes. Geometry-force attribution showed that the first shelf was active but contacted below the rim. The v4 plan raises the shelf and applies a `+35°` local-X counter-rotation on both clamp frames, placing its contact band around the measured `0.0678 m` rim radius with an approximately horizontal top face. The local-only v4 asset manifest is `41c4c3cf315f548344ce8004a0f29587d9f0c40a75df26443c325aeeaa6cb387`; its generated URDF is `9e93491b2244e0d68e7cf110d631e0f970c30decba8d5d9e9e4955e75a0600ec`.

The v4 CPU chain uses run `mantis-rim-support-v4-frozen-load-cpu-20260723-v5` (receipt `7d59f145576c8eeadf6b552e469d70ca1d77d5bbe7f19bb73aae42ec4c93f1a4`) for the 18-DOF load gate and `mantis-bimanual-rim-support-v4-frozen-scene-gate-stl-cpu-20260723-v11` (receipt `4956eb511c0f1a546208a021cd8f8b9d31ce8539b406b4da2fe3d33361752546`) for the 1120-candidate scene scan, where 668 candidates pass. The v21 dynamic run reached `9.761 mm` against the fixed `10 mm` threshold. Without changing geometry, contact span, duration, or threshold, the v22 candidate increases the commanded vertical distance from 20 to 30 mm. Run `mantis-bimanual-rim-support-v4-lift30mm-candidate-stl-cpu-20260723-v35` (receipt `3c03f64152f4a2cb9551aa37293497c0c0dbcf6b29df94c00146e979fb737fc9`) lifts the bowl `12.800 mm` and preserves bilateral contact, tracking, navigation, table, other-bowl, self-collision, and non-clamp safety gates. This passes the lift component only; horizontal transport, placement, release, and strict stabilization are still required before G1 or task-success claims.

The subsequent transport boundary is retained as negative evidence. Eight
synchronized Cartesian IK waypoints remove the earlier wrist collision, but
the right support is lost at the first horizontal waypoint (v23 receipt
`b121e1cd989f5b8571df02f05dd086b64b9d01a16663499cde048eca9f5411fc`).
Increasing total transport time from 2 s to 8 s still fails (v24 receipt
`d266fe59d89577630c31a5f973ca3c7823492ec991c32c789d8364c4ba6f72d1`).
Tightening the lift/transport opening from `0.65` to `0.50` raises lift travel
to `14.705 mm` but lowers mean vertical support to `94.1%` of bowl weight and
also drops during transport (v25 receipt
`4b0c80bc529efd873e52a532f222984fbd8e11c6803f6b1aaaa47cfb58381b64`).
Further timing/preload sweeps are deferred; the remaining gate requires
transport-retentive licensed geometry or another grasp mode.

## Observation and control boundary

The source records 320×240 RGB from head, right-wrist, and left-wrist cameras. Its ACT path resizes these views directly to 640×480. Mantis retains its native LeRobot camera sizes and maps policy roles to environment, left-wrist, and right-wrist views before the same policy-tensor resize.

The environment-camera source-equivalent pose is frozen. For competition simulation, the source relative wrist-camera mount is attached to Mantis's semantic terminal wrist links and has passed a Genesis attachment gate. It is explicitly not a physical Mantis calibration; see `docs/SCENE_GATES.md`.

Source expert actions are variable-duration TOPP joint targets at a 250 Hz physics step. The Mantis policy interface is fixed at 30 Hz. The frozen resampler requires a timestamped dense trace, preserves semantic path and coordination through uniform velocity-limited retiming, samples exact 30 Hz ticks, and holds the endpoint. Endpoint-only source records remain invalid conversion inputs.

## Two evaluation protocols

`legacy_source_v1` reproduces the source evaluator exactly for compatibility checks. It sorts the three bowls by height, requires adjacent XY component differences to be strictly below 0.04 m, checks both grippers are open, and applies the one-sided height test `actual_z - target_z < 0.02` against `[0.74, 0.77, 0.81]`. It has no lower height bound and no consecutive-frame stability requirement. An implausibly low aligned stack can therefore pass.

`competition_strict_v1` is the target reporting protocol. It keeps the same XY and target-height geometry, but uses absolute height error, requires bounded linear and angular speeds, requires both virtual grippers at least 90% open, rejects safety or physics failures, and requires the predicate to remain true for 12 consecutive 30 Hz policy frames.

The protocols are intentionally not directly comparable. Reports must name the protocol alongside every success rate. The pure reference implementations and regression tests are in `src/mantis_rocm_bridge/stack_bowls.py` and `tests/test_stack_bowls.py`.

## Current gates before scene execution

- pass the remote CPU pre-G1 reset/IK receipt with the corrected Mantis workcell pose;
- execute one complete scripted contact episode before making a G1 claim;
- retain the passed unchanged 10 mm lift component while adding transport,
  placement, release, and strict stabilization;
- freeze workspace and maximum-relative-target limits;
- resolve the visual-mesh collision filter policy;
- collect the target Mantis dataset and recompute normalization statistics;
- verify the virtual-gripper mapping against hardware.

Until these gates close, this repository makes no Mantis task-success or AMD performance claim.
