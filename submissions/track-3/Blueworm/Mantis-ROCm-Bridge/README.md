# Mantis-ROCm Bridge

Mantis-ROCm Bridge contributes a reusable integration path for robot
manufacturers joining the **AMD embodied-AI ecosystem**. It turns a
vendor-specific URDF, kinematic and camera definitions, state/action interfaces,
controller assumptions, datasets, and learned policies into explicit contracts
that can be validated through Genesis, LeRobot, and AMD Radeon + ROCm.

Rather than treating every new robot as an isolated port, the project provides
a **contract-driven, evidence-gated robot adaptation and task-porting
framework**. It helps a user describe a source task, adapt its robot and
interfaces, validate simulation and dataset readiness, run a staged policy
workflow on AMD hardware, and distinguish configuration readiness from actual
robot capability.

The product is the framework. The first evidence-backed **reference case**
ports RoboTwin's `stack_bowls_three` task from the Tron embodiment to Mantis
using Genesis, LeRobot, and the official single-GPU AMD Radeon/ROCm path. One
reference port does not prove multi-robot runtime generality.

This individual, deadline-bound prototype has limited demonstration coverage
and training time, so the learned policy is not deployment-ready. Its primary
contribution is the reusable integration layer and evidence discipline: a
concrete foundation that lowers the engineering cost of bringing additional
vendor robots into the AMD stack without overstating the current 0/10 task
result.

**Demo:** [`submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`](submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4)

Participant: **Zhiwen Su**  
Team: **Blueworm**  
Application: **Mantis-ROCm Bridge**  
License: **Apache-2.0** for original project material Blueworm has the right to
license

## URDF-to-ROCm compiler MVP

The first compiler prototype accepts a strict URDF plus explicit robot
semantics and a task pack. For the admitted fixed-base boundary it identifies
single-arm 6/7-DoF and bimanual 6/7-DoF morphologies, then emits an exact
eleven-file executable port bundle:

- Embodiment IR and morphology report;
- robot-port profile, declarative Genesis Port Spec, and generated no-command
  Genesis runner;
- LeRobot feature schema and ACT training contract;
- ROCm runtime requirements, morphology-aware tuning plan, and monotonic ACT
  quality gates; and
- a bundle manifest with SHA-256 for every payload.

```bash
PYTHONPATH=src python3 tools/compile_robot_urdf.py inspect robot.urdf
PYTHONPATH=src python3 tools/compile_robot_urdf.py compile robot.urdf \
  --semantics robot-semantics.json \
  --task task-pack.json \
  --output new-port-bundle
PYTHONPATH=src python3 tools/compile_robot_urdf.py verify new-port-bundle
```

The compiler does not guess controller frequency, camera calibration, gripper
convention, workspace or emergency-stop behavior, task reset/success rules, or
asset rights. The generated runner has verified fixed-base load, unique arm-DoF
mapping, and no-command stepping on one current Radeon worker; controlled
motion still requires robot-specific IK, controller, and safety parity. ACT
deployability requires dataset admission, finite training and open-loop
evidence, at least 6/10 closed-loop G3 successes, and zero safety failures;
8/10 is the competitive target. Training loss alone never promotes capability.

The external Mantis reference was read-only inspected as two 7-DoF arms below
one shared waist degree of freedom. The source URDF is not copied into the
project or source backup. Mantis visual display is controlled by the project
owner, while redistribution of source URDFs, meshes, or derived assets remains
a separate rights gate.

## Framework surface

```text
source task audit
  -> source/target robot profile
  -> state/action/camera/clock/controller/safety contracts
  -> external asset and scene admission
  -> scripted expert and strict episode admission
  -> LeRobot export and dataset audit
  -> AMD/ROCm training and open-loop admission
  -> closed-loop multi-seed evaluation
  -> evidence, clean-room, and publication gates
```

The schema-v1 profile explicitly covers controller, safety, data, policy, and
evaluation. Policy and physical state/action dimensions have independent
ordered fields, so the framework does not assume that state and action
dimensions match.

Key artifacts:

- `configs/robot-port-profile-template-v1.json` — blocked copy-and-edit
  template;
- `configs/robot-port-profile-mantis-stack-bowls-v1.json` — Mantis reference
  profile;
- `tests/fixtures/robot-port-profile-synthetic-v1.json` — validation-only
  non-Mantis fixture, not a second real robot port;
- `tools/plan_robot_port.py` — deterministic read-only validator and stage
  planner.

```bash
PYTHONPATH=src python3 tools/plan_robot_port.py validate \
  configs/robot-port-profile-template-v1.json
PYTHONPATH=src python3 tools/plan_robot_port.py validate \
  configs/robot-port-profile-mantis-stack-bowls-v1.json
PYTHONPATH=src python3 tools/plan_robot_port.py plan \
  configs/robot-port-profile-mantis-stack-bowls-v1.json
```

These commands validate declarations and local references only. They do not
start simulation, collect data, train a policy, run inference, or contact a
remote host.

## Reference-case result

The official single-Radeon baseline completed a 60,000-step ACT optimization
run and passed open-loop interoperability. Its frozen closed-loop G3 evaluation
is a verified negative result: **0/10 strict successes**, with eight
`timeout` and two `collision_safety` failures.

The later six-trajectory CUDA correction also completed training, but its exact
representative seeds 101/107/108 produced zero successes and two safety
failures. Its terminal is **`COMPLETE_NOT_PROMOTABLE`**. Therefore no official
AMD corrective training or evaluation was started, and SmolVLA, G4, and
learned-policy capability promotion remain paused.

This separation is intentional: a completed optimization run and finite
open-loop actions are not closed-loop task success.

### Development ACT milestone

The CUDA development path has now produced nonzero real closed-loop ACT
success on represented training seed 1001. Checkpoint 030000 with the standard
30-action chunk / 30-action execution schedule succeeded in all three
infrastructure-valid cold-start evaluations, with three contact-triggered
attachments, three releases, zero safety failures, and no trajectory replay in
each run. One additional launch failed closed on an out-of-range gripper
readback and is retained as infrastructure-negative evidence rather than
counted in the policy denominator.

This result is deliberately classified as **training-seed memorization
repeatability**, not held-out generalization, official AMD/ROCm G3 evidence, or
a competition-gate pass. Both tested one-action receding schedules failed
0/1, so the standard 30/30 schedule remains the only promoted development
schedule. The official single-Radeon G3 result remains **0/10**. The aggregate
receipt is
`receipts/4090-act-seed1001-learned-adapter-30000-repeatability-summary-20260730-v14/`;
the independently verified 219 source-backup receipt is
`receipts/219-act-nonzero-success-source-backup-20260731-v2/`.

The current contest rules and operational links are frozen in
`configs/competition-resources-v1.json` and summarized in
[docs/COMPETITION_RESOURCES.md](docs/COMPETITION_RESOURCES.md).

Operational handoff state and private machine locations are intentionally kept
outside the public candidate. Public claims are indexed by
`submission/EVIDENCE_MATRIX.md`.

## Current status

`WP-ROCM-NATIVE-ROBOT-PORT-005` is complete at
`receipts/rocm-native-robot-port-terminal-20260729-v1/`. On the current
single-GPU Radeon worker, a generated project-owned bimanual 7+7 fixture port
requested and observed `gs.amdgpu`, mapped fourteen distinct arm DoFs, and
completed two finite no-command headless steps. A same-device ACT-shaped
microbenchmark admitted BF16 for this shape, with measured p50 speedups of
12.87% for inference and 26.81% for a forward/backward step. This reaches only
`ROCM_TUNING_MEASURED`; it is not ACT training or task-accuracy evidence and
does not change the Mantis G3 result of 0/10.

`WP-URDF-ACT-COMPILER-MVP-004` is complete at
`receipts/urdf-act-compiler-terminal-20260729-v1/`. The implementation passes
strict malformed/topology/semantics/no-overwrite tests, identifies the external
Mantis reference as bimanual 7+7 DoF, leaves all eight pinned Mantis runtime
files byte-identical, and is backed up with independent SHA-256 verification
on 219. This is static compiler evidence, not generated Genesis execution,
ACT accuracy, or an AMD optimization result.

`WP-FRAMEWORK-MVP-002` is complete at
`receipts/framework-mvp-terminal-20260729-v2/`. The template, Mantis reference
profile, synthetic fixture, read-only validator, and planner passed 22/22
focused tests; the Mantis profile resolved 20/20 required local references.
Eight existing Mantis runtime/controller/data/ACT runner files remained
byte-identical.

`WP-FRAMEWORK-STORY-003` synchronizes the local product narrative under
[docs/FRAMEWORK_STORY_V1.md](docs/FRAMEWORK_STORY_V1.md), with its terminal
evidence in `receipts/framework-story-terminal-20260729-v3/`. Local content and
integrity gates pass for this candidate. Clean-room reproduction, a public PR or
submission, competition acceptance, G3 success, convergence, robustness,
real-robot safety, raw-asset redistribution rights, and any AMD performance
advantage remain unproven. It is ready for an authorized public PR only after
independent `RELEASE_GO`. Archive clean-room source review remains
`CLEANROOM_RUNNER_NO_GO`; no runner executed, so clean-room reproduction is
unproven. Final rule review, repository fork, PR, and submission are pending
external actions. No public action is performed by this document update.

Rendered Mantis visuals are user-permitted only in the demonstration video.
This is not a general license or redistribution right. Raw Mantis URDF, meshes,
source assets, derived raw asset files, materializations, and asset payloads
remain excluded and externalized because no redistributable asset license has
been established. The accepted H.264 1280x720 demo with English narration and
burned-in subtitles is
`submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`, SHA-256
`220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`,
with a disclosed duration of 168 seconds. It shows the correct upright Mantis
three-bowl scene, a clearly labelled scripted expert trajectory, and an AMD
policy-in-loop smoke that is explicitly labelled as not completing the task.
The project does not claim
real-robot safety, generalization, robustness, a G3 pass, or an AMD performance
advantage.

## Offline validation

The end-to-end official-cloud command surface and evidence requirements are in
[docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

```bash
PYTHONPATH=src python tools/validate_contracts.py
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python tools/summarize_episodes.py examples/episodes.example.jsonl
PYTHONPATH=src python tools/check_rocm.py
PYTHONPATH=src python tools/audit_mantis_urdf.py /path/to/mantis.urdf \
  --package-root /path/to/mantis_description
PYTHONPATH=src python tools/check_gripper_mapping.py
PYTHONPATH=src python tools/audit_mantis_lerobot_dataset.py /path/to/mantis_dataset
PYTHONPATH=src python tools/audit_mantis_lerobot_dense.py \
  /path/to/mantis_dataset \
  --metadata-receipt /path/to/dataset-metadata-receipt.json \
  --episode-outcomes /path/to/strict-episode-outcomes.json
PYTHONPATH=src python tools/validate_episode_stage_trace.py /path/to/stage-trace.json
PYTHONPATH=/path/to/lerobot/src:src python tools/export_mantis_npz_to_lerobot.py \
  /path/to/capture-manifest.json /new/path/to/mantis_lerobot_dataset \
  --allow-unverified-sim-gripper
PYTHONPATH=/path/to/export-overlay:/path/to/lerobot/src:src \
  python tools/smoke_lerobot_export_runtime.py /new/path/to/schema-smoke
PYTHONPATH=/path/to/export-overlay:/path/to/lerobot/src:src \
  python tools/run_genesis_lerobot_capture_smoke.py \
  /path/to/mantis.urdf /path/to/bowl_asset \
  --ops-root /new/path/to/ops --run-id capture-smoke-v1 --backend cpu
PYTHONPATH=src python tools/preflight_act_rocm.py \
  /path/to/mantis_multiseed4_dataset \
  local/mantis_stack_bowls_multiseed4_reproduction_v1 \
  /path/to/new_act_output \
  --training-contract configs/act-rocm-baseline-v2.json \
  --dataset-receipt /path/to/dataset-metadata-receipt.json \
  --dense-receipt /path/to/dense-audit.json \
  --scripted-g1-receipt /path/to/scripted-g1-receipt.json \
  --rocm-receipt /path/to/rocm-receipt.json
PYTHONPATH=src python tools/run_genesis_mantis_smoke.py /path/to/mantis_fixed_base.urdf \
  --ops-root runs/genesis-smoke --run-id cpu-load-v1 --backend cpu
PYTHONPATH=src python tools/run_genesis_stack_bowls_preflight.py \
  /path/to/mantis_fixed_base.urdf /path/to/robotwin_002_bowl_model3_v1 \
  --ops-root runs/stack-bowls-preflight --run-id cpu-reset-ik-v1 --backend cpu
```

For a fresh official-cloud reproduction, follow
[docs/AMD_CLOUD_BOOTSTRAP.md](docs/AMD_CLOUD_BOOTSTRAP.md). The primary contest
recovery path treats `/workspace/persistent` as the only workspace entrypoint
to the durable PVC and freezes the project layout in
`configs/amd-persistence-layout-v2.json`. The earlier verified run used legacy
`/workspace/*` paths; those historical receipts remain unchanged. The
training-material target remains ROCm 7.2.1,
PyTorch 2.9.1, LeRobot 0.4.4, NumPy 2.1.2, and Genesis `gs.amdgpu`. The
recommended `proxy` Gallery template was absent when the verified instance was
created, so the recorded run used the available Blank OpenCode Workspace
template; this divergence is preserved in
`configs/amd-cloud-runtime-v1.json`. On that single-GPU AMD worker, capture a
strict receipt with:

```bash
PYTHONPATH=src python tools/check_rocm.py \
  --require-rocm \
  --output /workspace/persistent/mantis-track3/evidence/runtime/rocm-runtime.json
```

The strict command fails unless PyTorch reports a HIP runtime and at least one visible device. A passing receipt is evidence of runtime availability, not evidence that training or inference used the GPU; those require separate run receipts.

The older ROCm 6.4.1 container frozen by `configs/rocm-container-v1.json` is a
portable fallback, not the official cloud main path. If a non-cloud Radeon
worker requires it, build and open it with:

```bash
docker compose -f docker/compose.rocm.yaml build --pull
MANTIS_RUNTIME_ROOT=/absolute/path/to/runtime \
  docker compose -f docker/compose.rocm.yaml run --rm mantis-rocm
```

The fallback runtime root is bind-mounted because the provisional Mantis asset,
datasets, checkpoints, and receipts must not be baked into or redistributed
with the image. After the build, record the immutable image digest before
running `tools/check_rocm.py --require-rocm`; a Dockerfile alone is not AMD
execution evidence.

The ACT preflight emits an exact `lerobot-train` argument vector but never
starts training. The official AMD baseline was launched separately under a
non-overwriting supervisor and completed successfully. Archive clean-room
source review is `CLEANROOM_RUNNER_NO_GO`, neither reviewed runner was executed,
and reproduction from the published package remains an explicit unproven
limitation rather than a local package blocker.

Evidence-producing jobs can be wrapped in non-overwriting run markers:

```bash
PYTHONPATH=src python tools/run_marker.py runs act-g3-001 begin \
  --details '{"git_revision":"REPLACE_ME","config_sha256":"REPLACE_ME"}'
# Run the immutable training or evaluation command here.
PYTHONPATH=src python tools/run_marker.py runs act-g3-001 complete \
  --details '{"episodes":10}'
```

## Repository boundaries

- No raw Mantis meshes, URDFs, datasets, checkpoints, or private deployment code are vendored; the only URDF/STL files present are the nine synthetic, non-Mantis test fixtures under `tests/fixtures/`.
- `configs/mantis-port-config.json` is the source of truth for semantic reordering.
- `configs/task-pack-v1.json` is the source of truth for task and evaluation rules.
- `configs/source-task-stack-bowls-three.json` freezes the read-only RoboTwin task evidence and legacy protocol; see [the port contract](docs/STACK_BOWLS_PORT.md).
- The three resolved scene prerequisites and their evidence boundaries are documented in [docs/SCENE_GATES.md](docs/SCENE_GATES.md).
- The upstream Mantis LeRobot interface and normalization guard are documented in [docs/MANTIS_LEROBOT_GATE.md](docs/MANTIS_LEROBOT_GATE.md).
- `configs/source-reference-4090.json` records the sanitized, read-only NVIDIA
  reference snapshot; operational host details are excluded from the public
  package.
- `configs/competition-resources-v1.json` freezes the dated rule interpretation,
  reference links, language decision, and submission deadline.
- `configs/amd-cloud-runtime-v1.json` freezes the verified official-cloud
  runtime identity, image divergence, and required promotion receipts.
- `configs/amd-persistence-layout-v2.json` and
  `configs/amd-cloud-runtime-v3.json` freeze the current recovery layout under
  `/workspace/persistent`; the NFS PVC and one minimal write/read/delete
  canary are verified, while package installation and new-worker GPU workloads
  remain unverified and unauthorized.
- The fixed-base topology, guarded builder, and provisional 16D↔18D gripper mapping are documented in [docs/FIXED_BASE_ASSET.md](docs/FIXED_BASE_ASSET.md).
- The audited SAPIEN reference boundary and explicit Genesis CPU/CUDA/AMDGPU smoke workflow are documented in [docs/SIM_BACKEND.md](docs/SIM_BACKEND.md).
- The project is licensed under **Apache License 2.0** for original project
  source and documentation, copyright holder **Blueworm**, copyright year
  **2026**, decision recorded on **2026-07-29** (see `LICENSE` and
  `docs/PROJECT_LICENSE_DECISION.md`). This project license applies only to
  original project material that Blueworm has the right to license. It does not
  license, relicense, or authorize redistribution of the Mantis URDF/meshes or
  derived materializations, private adapters, the RoboTwin bowl asset, Genesis,
  LeRobot, datasets, checkpoints, or any other third-party material; those rights
  remain governed by `third_party/ASSET_LICENSES.md`. Mantis remains
  externalized while no redistributable asset license or owner authorization is
  established. The local release candidate remains gated on independent
  `RELEASE_GO` before an authorized public PR. It does not establish clean-room
  reproduction, a public repository, a submitted pull request, competition
  acceptance, a G3 pass, or third-party authorization.
- Submission identity is recorded as participant **Zhiwen Su**, team
  **Blueworm**, and application **Mantis-ROCm Bridge** in
  `configs/submission-identity-v1.json`.
