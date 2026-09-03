# Fixed-base Mantis Asset Contract

The competition profile uses the Mantis torso as a stationary dual-arm robot. It does not silently command or leave free the mobile base, pelvis actuator, or neck.

## Selected topology

- Root: `pelvis_link`.
- Links: 19 total — pelvis plus one child link for each selected joint.
- Physical joints: 18 total — 14 arm revolute joints and four clamp prismatic joints.
- Policy channels: 16 total — 14 arm channels and two virtual gripper channels.
- Excluded topology: all mobile-base ancestors of `pelvis_link` and the neck subtree.

The builder reads an external `mantis_description` checkout, selects only this topological tree, resolves the incorrect `meshes/` references against `meshes_full/`, copies only the selected meshes into a new versioned output, rewrites the URDF to relative paths, emits joint limits and SHA-256 hashes, and runs the structural URDF audit.

The read-only plan was executed against revision `b1e154e274fa7cfa8ecdeb10e85145d0c998382e`. It resolved all 19 unique selected meshes from `meshes_full/`, observed 38 visual/collision mesh uses, excluded nine joints, and produced source URDF SHA-256 `cf84f5eb2e6297e50cedcdd783888cb2ab628b4fb1dde57a7e1498f79003868c`. The frozen plan and joint limits are in `configs/fixed-base-plan.json`.

A temporary local-only materialization passed the structural import audit with 19 links, 18 actuated joints, no missing meshes, and no uncontrolled joints. Its deterministic generated URDF SHA-256 is `4db80a7659425b3419555cd28941c04ee5a6f8a44b4a4b3b28e46e3f4e2c5f57`; the joint-limit receipt SHA-256 is `e5d08fdd10b9f8b217c2e536a3764cae9d30e64087426ec18331927e8cf353f8`. This is not a Genesis runtime-load or visual-rendering result.

It never overwrites an output directory. Planning is read-only. Materialization requires an explicit local-use acknowledgement because the upstream package currently has no usable license declaration. A generated manifest always says `distribution_allowed: false`; the output must not be committed or submitted until the asset owner supplies a license.

The license boundary was re-audited on 2026-07-26. The public
`BlueWorm-EAI-Tech/mantis_description` tree remains pinned at
`b1e154e274fa7cfa1689904cc986ae9e09c1d35b`, contains `urdf_full/` and
`meshes_full/` but no root `LICENSE`, and its `package.xml` still says
`TODO: License declaration`. GitHub's repository metadata reports no detected
license. The separately supplied
`BlueWorm-EAI-Tech/lerobot_mantis_server` public page and repository API both
returned 404. These observations do not grant redistribution rights. Any
competition-only finger or tool overlay must therefore be authored from
independent URDF primitives under an explicit project license, while the
underlying Mantis asset remains an external, local-only dependency until its
owner publishes a license or grants written submission permission.

## Local-only rim-support overlay

`tools/materialize_mantis_rim_support_overlay.py` verifies the parent manifest and URDF hashes, copies into a new staging directory, appends independently specified box primitives, reruns the structural audit, and atomically publishes a non-overwriting output. It requires an explicit unresolved-license acknowledgement and always records `distribution_allowed: false` for the combined asset.

The selected `configs/mantis-rim-support-overlay-v4.json` plan places a `0.022 × 0.014 × 0.004 m` box at local `[0.061, 0.007, -0.006]` on each `clamp_left_link`. Both boxes use a `+35°` local-X rotation so their top faces are approximately horizontal in the contracted below-rim wrist pose. The remote local-only manifest SHA-256 is `41c4c3cf315f548344ce8004a0f29587d9f0c40a75df26443c325aeeaa6cb387`, and the generated URDF SHA-256 is `9e93491b2244e0d68e7cf110d631e0f970c30decba8d5d9e9e4955e75a0600ec`. Neither output may be committed or submitted until the upstream Mantis license is resolved.

## Candidate virtual-gripper mapping

Let `g` be a normalized open fraction, with `g=0` closed and `g=1` open:

```text
left_clamp_right_joint = +0.0376 - 0.0376 * g_left
left_clamp_left_joint  = -0.0376 + 0.0376 * g_left
right_clamp_right_joint = -0.0376 + 0.0376 * g_right
right_clamp_left_joint  = +0.0376 - 0.0376 * g_right
```

The original scale-only candidate was rejected by the first Genesis kinematic run: zero joint positions were open and the limit endpoints were closed. The corrected mapping is affine so `g=0` selects the closed limit endpoints and `g=1` selects zero-position open endpoints. It must pass a fresh Genesis kinematic and visual run before simulator promotion, followed by a check against the real ROS2 gripper range and sign.

The runtime adapter therefore rejects this mapping by default. `allow_unverified=True` is reserved for offline numeric and simulator commissioning tests; it must not be enabled in hardware deployment code.

## Commands

Read-only plan:

```bash
PYTHONPATH=src python tools/build_mantis_fixed_base.py \
  /external/mantis_description/urdf_full/lanchong_description_full.urdf \
  --package-root /external/mantis_description
```

Local-only materialization after explicit acknowledgement:

```bash
PYTHONPATH=src python tools/build_mantis_fixed_base.py \
  /external/mantis_description/urdf_full/lanchong_description_full.urdf \
  --package-root /external/mantis_description \
  --output /new/versioned/local-output \
  --materialize \
  --acknowledge-unresolved-license-for-local-use
```

Numeric gripper check:

```bash
PYTHONPATH=src python tools/check_gripper_mapping.py
```
