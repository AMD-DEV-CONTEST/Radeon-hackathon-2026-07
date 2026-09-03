# Simulation backend boundary

The 4090 reference workspace was audited on `lkshpc` on 2026-07-22. RoboTwin imports SAPIEN throughout its task, camera, actor, robot, and collection layers. The installed reference stack is SAPIEN `3.0.0b1`, mplib `0.2.1`, cuRobo, and PyTorch `2.4.1`. It is neither MuJoCo nor Isaac Sim.

The competition target therefore preserves the reference task semantics, 16D ACT data interface, camera roles, and evaluation predicate, but does not treat the SAPIEN runtime as the AMD execution backend. Mantis uses a separate Genesis runtime with explicit backends:

- `gs.cpu` for hardware-independent URDF/load debugging;
- `gs.cuda` only for the NVIDIA commissioning reference;
- `gs.amdgpu` for competition training, inference, and performance evidence.

The backend must be selected explicitly. The smoke tool refuses missing backends instead of silently falling back to CPU or CUDA.

## Runtime smoke

```bash
PYTHONPATH=src python tools/run_genesis_mantis_smoke.py \
  /path/to/mantis_fixed_base.urdf \
  --ops-root runs/genesis-smoke \
  --run-id cpu-load-v1 \
  --backend cpu
```

Add `--render` to create closed/open PNGs. A successful runtime receipt only proves URDF loading, joint-name/DOF mapping, stepping, and exact state assignment. Even when PNGs are generated, `visual_gripper_verified` remains false until a reviewer confirms open/close direction, symmetric travel, and the closed contact gap.

The same command on the AMD worker must use `--backend amdgpu`; that AMD receipt is separate from this NVIDIA commissioning evidence.

## 4090 commissioning result

The isolated reference environment uses Genesis `1.2.3` with PyTorch `2.8.0+cu126`; the existing Tron environment remains on PyTorch `2.4.1`. Run `mantis-cpu-corrected-render-20260722-v3` passed on `gs.cpu` with the fixed-base URDF SHA-256 `4db80a7659425b3419555cd28941c04ee5a6f8a44b4a4b3b28e46e3f4e2c5f57`.

The first scale-only gripper candidate was retained as a negative result: it implemented the virtual convention backwards. The corrected affine mapping passed with 37.6 mm travel per finger, zero left/right travel asymmetry, 0 mm closed link-origin separation, and 75.2 mm open link-origin separation. Human review of the close-up closed/open renders confirmed direction and symmetric motion. Hardware ROS2 sign and range remain unverified.

Run `mantis-cpu-limits-20260722-v4` compared all 18 limits parsed by Genesis with `configs/fixed-base-plan.json`; the maximum absolute float32 discrepancy was `1.0490417468034252e-07`, passing the `1e-6` gate. This validates positional limit ingestion only, not velocity, force, workspace, collision, or emergency-stop behavior.

Genesis also warned that it filtered neutral-configuration collision geometry pairs `(1,3)`, `(5,7)`, `(10,12)`, and `(14,16)`. A follow-up geometry inventory mapped them to left/right shoulder pitch↔yaw and wrist roll↔yaw shells. The package uses the high-detail visual STL files as collision geometry, so an explicit filter policy or simplified dedicated collision meshes remain required.

## CUDA compatibility matrix

The reference host has NVIDIA driver `535.247.01`. Genesis `1.2.3` with Quadrants `1.1.1` and Genesis `0.4.6` with Quadrants `0.6.2` both failed before scene construction because the installed CUDA driver library does not export `cuGraphConditionalHandleCreate`. These failures are retained as runs `mantis-cuda-kinematics-20260722-v2` and `mantis-cuda-kinematics-20260722-v3`. No system driver was changed.

The versioned compatibility overlay uses Genesis `0.3.14`, GsTaichi `4.6.0`, and PyTorch `2.8.0+cu126`. Run `mantis-cuda-kinematics-20260722-v4` passed on physical RTX 4090 GPU 3 using `gs.cuda`: all 18 DOFs were resolved, closed/open assignment errors were at most `5.424022689326513e-10`, both grippers had symmetric 37.6 mm finger travel and 75.2 mm open separation, all positional limits passed with maximum error `1.0490417468034252e-07`, and two physics steps completed.

This is a CUDA commissioning reference, not a same-version CUDA-versus-ROCm performance comparison. Genesis `0.4.0` introduced the Quadrants runtime and the experimental AMD backend, so the AMD worker must use the current Genesis/Quadrants stack and produce an independent `gs.amdgpu` receipt. Collision-pair indices in the older GsTaichi run are version-specific and must not be interpreted using the 1.2.3 geometry index map.
