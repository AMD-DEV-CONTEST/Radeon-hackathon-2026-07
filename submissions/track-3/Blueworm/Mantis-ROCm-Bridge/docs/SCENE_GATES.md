# Scene prerequisite gates

> Status update (2026-07-24): these prerequisite and negative runs predate the
> complete scripted v90/v91 seed-1 result. Local CPU G1 now passes; AMD replay,
> multi-seed demonstrations, and learned-policy gates remain. See
> `docs/EXECUTION_PLAN.md` for the continuation source of truth.

## Bowl license and Genesis materialization

RoboTwin's GitHub repository does not contain the large object meshes. Its official downloader fetches `objects.zip` from `TianxingChen/RoboTwin2.0`. The Hugging Face dataset card declares MIT, and the pinned archive revision is `b5230d8b4c348769f0c2402b73c88852f093b011`; the archive LFS SHA-256 is `6aa56b3cf1e1064f7c809308144da36b00815f8b137fef2d7e4de856f8becf27`.

`configs/bowl-asset-plan.json` binds the model-3 visual GLB, multiple-convex collision GLB, metadata, and MIT attribution by SHA-256. `tools/materialize_bowl_asset.py` refuses missing or changed files and never overwrites an output directory. It creates a URDF with separate visual and collision meshes, includes the license, and freezes SAPIEN's automatically computed mass, center of mass, and principal inertia.

Remote materialization:

```bash
PYTHONPATH=src python3 tools/materialize_bowl_asset.py \
  /path/to/robotwin \
  --output /new/versioned/robotwin_002_bowl_model3_v1
```

The first CPU runtime gate exposed a Genesis 1.2.3 legacy-parser fallback for the source multi-convex collision GLB. `tools/materialize_bowl_collision_stl.py` now creates a second, non-overwriting asset version: it verifies the licensed parent manifest, preserves the source GLB and attribution, expands its 24 transformed convex components into individually hashed STL files, and rewrites only the URDF collision entries.

```bash
PYTHONPATH=src python3 tools/materialize_bowl_collision_stl.py \
  /path/to/robotwin_002_bowl_model3_v1 \
  --output /new/versioned/robotwin_002_bowl_model3_v2_stl
```

The CPU runtime gate `mantis-stack-bowls-scene-stl-cpu-20260723-v3` (receipt SHA-256 `bf6f15473cfbf6d5b025ee5a8459f9670ccaa6e34a0fe66833716f847549c62b`) loaded Mantis and three STL-materialized bowls without the GLB collision fallback. All bowls remained in finite table contact after ten 4 ms steps; mass error was zero and maximum principal-inertia error was approximately `1.08e-19`. The v2 asset manifest SHA-256 is `ad895e3148b18909ebdcd0e7dcbb6c1f03c3d7def64ded5b6f991e38dc94ac5c`, and its URDF SHA-256 is `d84ccce7fbd7484fd3195eebc386185855b38a2cafec5cbfec6eec122983fc01`. This verifies CPU parsing and short-horizon stability only; the same gate still must run on the AMD worker.

## Mantis rim-support geometry gate

The selected v4 shelf is a local-only prototype over the unresolved Mantis asset, not a redistributable competition artifact. Its frozen CPU load receipt is `7d59f145576c8eeadf6b552e469d70ca1d77d5bbe7f19bb73aae42ec4c93f1a4`. The full signed scene scan `mantis-bimanual-rim-support-v4-frozen-scene-gate-stl-cpu-20260723-v11` evaluates 1120 candidates and passes 668; receipt SHA-256 is `4956eb511c0f1a546208a021cd8f8b9d31ce8539b406b4da2fe3d33361752546`. The v21 dynamic receipt `501ff5167335c60f45a5858ec0b424466ee01f67652f8817e90d865c8483ac4c` stopped at `9.761 mm`. The v22 candidate keeps the fixed `10 mm` threshold and commands 30 mm instead of 20 mm; run `mantis-bimanual-rim-support-v4-lift30mm-candidate-stl-cpu-20260723-v35` reaches `12.800 mm` with receipt `3c03f64152f4a2cb9551aa37293497c0c0dbcf6b29df94c00146e979fb737fc9`. This clears the single-bowl lift component, but G1 remains open until transport, placement, release, and strict stabilization pass.

## Simulation wrist-camera mounts

No physical wrist-camera transform was found in the audited Mantis description, SDK, or public motion workspace. For the competition simulation, `configs/camera-extrinsics-v1.json` preserves the source task's relative wrist-camera transform and attaches it to Mantis's semantic terminal wrist links:

- left: `left_wrist_yaw_link`;
- right: `right_wrist_yaw_link`;
- translation: `[0.0664, -0.0012, -0.0979]` metres;
- fixed-axis RPY: `[1.78179, 1.451946, -2.929144]` radians.

This is a source-equivalent simulation mount, not a real Mantis calibration. Both Genesis camera attachments passed the same CPU scene gate. A later real-robot deployment must add a separately measured hand-eye or CAD transform and must not relabel the simulation transform as hardware evidence.

## 250 Hz TOPP to 30 Hz Mantis resampling

`configs/control-resampling-v1.json` and `src/mantis_rocm_bridge/control_resampling.py` define the conversion:

1. require the combined dual-arm dense trace with explicit timestamps;
2. semantically reorder all 16 joints into Mantis order;
3. compute one uniform time-stretch factor from the worst source segment velocity versus the target per-joint limit;
4. linearly sample the retimed path on exact `k / 30` command ticks;
5. clamp the final query and hold the exact endpoint on the first tick at or after the retimed duration;
6. recompute 30 Hz command velocities and reject any limit violation.

Uniform retiming preserves the path and left/right synchronization. It may lengthen wall-clock duration and adds less than one 30 Hz interval of endpoint hold. Endpoint-only records without dense timestamps are rejected because their variable TOPP duration cannot be reconstructed from policy-step indices.

The conversion CLI writes a new, non-overwriting receipt:

```bash
PYTHONPATH=src python3 tools/resample_topp_trace.py \
  source-dense-trace.json target-30hz-trace.json
```
