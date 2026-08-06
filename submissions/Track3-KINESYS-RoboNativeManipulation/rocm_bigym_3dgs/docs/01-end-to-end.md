# End-to-end implementation and coordinate systems

## Why 3DGS is split into a visual shell

MuJoCo is strong at stable, verifiable robot and object physics; 3DGS is strong at realistic environmental appearance. After separation, visual background does not enter MJCF, so it does not affect collision, contact, reward, or control trajectories.

Per-camera frame processing order is:

1. Read camera extrinsics, intrinsics, RGB, and segmentation from MuJoCo.
2. Transform MuJoCo camera poses to Gaussian coordinates using the inverse of `T_gaussian_to_mujoco`.
3. Render background with gsplat on AMD GPU.
4. Composite robot, workbench, and task objects back onto the background by segmentation.
5. Strict mode records render counts and last error; any 3DGS error immediately terminates official collection.

## Sim(3) alignment

The 4x4 transform in configuration maps Gaussian world coordinates into MuJoCo world coordinates:

```text
p_mujoco = s R p_gaussian + t
```

The result must pass independent checks, not visual alignment only:

- Keep ground normal vertical.
- Keep room height and relative scale in valid range.
- Keep head / left wrist / right wrist cameras near the training camera trajectory.
- Keep rotation deviation bounded.
- Do not change floor height via appearance search.

This appearance search only tuned horizontal translation and yaw, then selected one fixed external camera with full H1 visibility. The measured profile is stored in `configs/`, and visual-quality boundaries are retained there.

## Physics isolation acceptance

Receipts must record:

```json
{
  "background_physics": {
    "body_count": 0,
    "geom_count": 0,
    "collision_count": 0
  }
}
```

These three values only prove 3DGS did not enter the physics world and cannot replace visual acceptance.
