# URDF-to-ROCm ACT compiler MVP

Date: 2026-07-29  
Work package: `WP-URDF-ACT-COMPILER-MVP-004`

## Product boundary

Mantis-ROCm Bridge compiles a robot description and task contract into an
auditable Genesis, LeRobot ACT, and AMD/ROCm port bundle. The MVP supports
fixed-base single-arm and bimanual robots with six or seven actuated joints per
arm.

URDF is sufficient for topology, joint types, limits, and kinematic-chain
analysis. It is not sufficient for camera calibration, controller frequency,
gripper semantics, safety behavior, task reset, success predicates, or asset
rights. The compiler reports questions and blockers instead of inventing these
values.

## Commands

```bash
PYTHONPATH=src python3 tools/compile_robot_urdf.py inspect robot.urdf

PYTHONPATH=src python3 tools/compile_robot_urdf.py compile robot.urdf \
  --semantics robot-semantics.json \
  --task task-pack.json \
  --output new-port-bundle
```

`inspect` writes nothing and prints deterministic JSON. `compile` refuses an
existing output path and either creates the complete nine-file bundle or
publishes nothing.

## Embodiment intermediate representation

The Embodiment IR records:

- source hash and robot identifier without the absolute input path;
- roots, links, joints, joint limits, mimic relations, and topology;
- candidate and selected arm chains;
- arm count and actuated degrees of freedom;
- inferred semantic candidates with confidence and evidence;
- unresolved questions, unsupported features, and blockers; and
- a claim boundary.

For 6/7-DoF portability, policy actions are defined in a canonical per-arm task
space: translation delta, axis-angle rotation delta, and an optional normalized
gripper command. A generated Genesis adapter still requires robot-specific IK
and explicit controller/safety admission before runtime execution.

## ACT quality contract

Compilation is not model capability. Promotion is monotonic:

```text
URDF_ANALYZED
  -> PORT_COMPILED
  -> DATASET_ADMITTED
  -> ACT_TRAINED
  -> ACT_OPENLOOP_PASS
  -> ACT_CLOSEDLOOP_PASS
  -> AMD_DEPLOYABLE
```

Training loss is diagnostic only. `ACT_CLOSEDLOOP_PASS` requires a declared
ten-seed gate with at least 6/10 successes and zero safety failures. The
competitive target is 8/10. A thirty-seed confirmation is permitted only after
G3 passes.

The existing Mantis ACT baseline remains `ACT_OPENLOOP_PASS_ONLY`: its official
AMD G3 result is 0/10 with two safety failures.

## External assets and presentation

Mantis may be used as an external read-only morphology reference. Rendered
Mantis visuals are user-permitted only in the demonstration video; this is not
a general license or redistribution right. Raw Mantis URDF, meshes, source
assets, derived raw asset files, materializations, and asset payloads remain
excluded. This work package does not copy the external Mantis URDF into the
project, compiler bundle, receipt, or 219 backup.

## 219 source backup

The terminal source tree is archived from an explicit allowlist and published
to a fresh directory below:

`/data/mid8/backups/mantis-track3/source/wp-urdf-act-compiler-mvp-004/`

The phase is incomplete until the local archive and allowlist manifest verify,
the remote directory is newly created, and 219 independently recomputes the
same SHA-256 values.

## Claim boundary

This MVP proves only static inspection and bundle compilation. It does not yet
prove that a generated adapter executes in Genesis, that a second real robot
port works, that ACT succeeds, or that the AMD runtime has been optimized.
