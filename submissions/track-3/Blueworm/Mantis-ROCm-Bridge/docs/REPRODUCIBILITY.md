# Reproducibility runbook

> Status: **release-gated public reproduction surface**. Local content and
> integrity gates pass for this candidate. Clean-room reproduction, a public PR
> or submission, competition acceptance, G3 success, convergence, robustness,
> real-robot safety, raw-asset redistribution rights, and any AMD performance
> advantage remain unproven. It is ready for an authorized public PR only after
> independent `RELEASE_GO`. Archive clean-room source review remains
> `CLEANROOM_RUNNER_NO_GO`; no runner executed, so clean-room reproduction is
> an explicit unproven limitation rather than a local package blocker. Existing
> receipts remain evidence for prior runs, not clean-room evidence.

## 1. Framework profile walkthrough

Mantis-ROCm Bridge is a contract-driven, evidence-gated robot adaptation and
task-porting framework. The Tron/RoboTwin `stack_bowls_three` → Mantis path is
the first reference case. Before installing a simulator or materializing an
asset, validate the generic template and inspect the Mantis plan:

```bash
PYTHONPATH=src python3 tools/plan_robot_port.py validate \
  configs/robot-port-profile-template-v1.json
PYTHONPATH=src python3 tools/plan_robot_port.py validate \
  configs/robot-port-profile-mantis-stack-bowls-v1.json
PYTHONPATH=src python3 tools/plan_robot_port.py plan \
  configs/robot-port-profile-mantis-stack-bowls-v1.json
```

These commands are deterministic and read-only. They establish structural and
local-reference consistency, not generic runtime execution or a second real
robot port. The reference parity terminal is
`COMPLETE_FRAMEWORK_PROFILE_AND_READ_ONLY_PLANNER_VERIFIED`.

The six-trajectory CUDA correction is not the clean-room promotion path: its
seeds 101/107/108 completed with terminal `COMPLETE_NOT_PROMOTABLE`. No
official AMD corrective run followed. The clean-room instructions below
therefore reproduce the verified four-trajectory AMD ACT v2 baseline and its
honest 0/10 closed-loop result.

## 2. Evidence and safety boundary

The repository does not distribute the Mantis URDF or meshes, simulator
datasets, trained checkpoints, credentials, or private deployment payloads.
Before running:

- obtain the Mantis description through an authorized channel;
- verify its revision and local file hashes against
  `configs/mantis-port-config.json`;
- obtain the MIT-licensed RoboTwin2.0 `002_bowl` model 3 source and retain its
  attribution and license;
- use a fresh output directory for every command;
- expose exactly one GPU;
- never interpret optimization loss as closed-loop success.

Rendered Mantis visuals are user-permitted only in the demonstration video.
This is not a general license or redistribution right. Raw Mantis URDF, meshes,
source assets, derived raw asset files, materializations, and asset payloads
remain externalized. The Mantis materialization command requires an explicit
local-use acknowledgement because no redistributable asset license was
detected. That flag authorizes nothing and must not be used to publish the
asset.

The accepted H.264 1280x720 demonstration with English narration and subtitles
is `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`, SHA-256
`220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`,
with a disclosed duration of 168 seconds.

## 3. Required software

The official target is:

| Component | Target |
|---|---|
| Host | official Radeon Cloud, one Radeon GPU |
| ROCm | 7.2.1 teaching image |
| PyTorch | 2.9.1 ROCm wheel supplied by the image |
| torchvision / torchaudio | 0.24.0 / 2.9.0 image wheels |
| Triton | 3.5.1 image wheel |
| Genesis | 1.2.3-compatible checkout with `gs.amdgpu` |
| LeRobot | 0.4.4 |
| NumPy | 2.1.2 |
| Python project | editable install from this repository |

Follow [AMD_CLOUD_BOOTSTRAP.md](AMD_CLOUD_BOOTSTRAP.md) to install only the
instance-provided ROCm wheels. Never run an unconstrained `pip install torch`.
The older `docker/Dockerfile.rocm` is a portable ROCm 6.4.1 fallback and is not
the authoritative official-cloud environment.

After activating the durable environment, install and validate the project:

```bash
cd /workspace/persistent/mantis-track3/src/mantis-rocm-bridge
source /workspace/persistent/mantis-track3/envs/rdna/bin/activate
export REPRO_ROOT=/workspace/persistent/mantis-track3/evidence/reproduction/mantis-track3-v1
mkdir -p "$REPRO_ROOT"
python -m pip install --no-deps -e .
PYTHONPATH=src python tools/check_amd_persistence.py --check-filesystem
PYTHONPATH=src python tools/validate_contracts.py
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python tools/check_rocm.py \
  --require-rocm \
  --output "$REPRO_ROOT/rocm-runtime.json"
```

`check_rocm.py` proves runtime availability only. Training and inference need
their own GPU/process/exit-code evidence.

## 4. External asset materialization

Set only task-specific variables; do not place credentials in the environment
or command line:

```bash
export MANTIS_DESCRIPTION_ROOT=/workspace/persistent/mantis-track3/assets/external/mantis_description
export MANTIS_SOURCE_URDF="$MANTIS_DESCRIPTION_ROOT/urdf/mantis.urdf"
export BOWL_SOURCE_ROOT=/workspace/persistent/mantis-track3/assets/external/robotwin_002_bowl_model3
test -d "$REPRO_ROOT"
```

Materialize the licensed bowl asset into a new directory:

```bash
PYTHONPATH=src python tools/materialize_bowl_asset.py \
  "$BOWL_SOURCE_ROOT" \
  --plan configs/bowl-asset-plan.json \
  --output "$REPRO_ROOT/bowl"
```

Materialize a local fixed-base Mantis copy without changing the external
source:

```bash
PYTHONPATH=src python tools/build_mantis_fixed_base.py \
  "$MANTIS_SOURCE_URDF" \
  --package-root "$MANTIS_DESCRIPTION_ROOT" \
  --port configs/mantis-port-config.json \
  --output "$REPRO_ROOT/mantis-fixed" \
  --materialize \
  --acknowledge-unresolved-license-for-local-use
export MANTIS_FIXED_URDF="$REPRO_ROOT/mantis-fixed/urdf/mantis_fixed_base.urdf"
export BOWL_ASSET_ROOT="$REPRO_ROOT/bowl"
```

The builders fail closed on source-hash, topology, joint-order, mesh, or
license-plan drift. See [FIXED_BASE_ASSET.md](FIXED_BASE_ASSET.md) and
[SCENE_GATES.md](SCENE_GATES.md).

## 5. Genesis scene admission

On the official worker, use `amdgpu`; CPU is permitted only for contract
debugging:

```bash
PYTHONPATH=src python tools/run_genesis_scene_gate_smoke.py \
  "$MANTIS_FIXED_URDF" "$BOWL_ASSET_ROOT" \
  --backend amdgpu \
  --ops-root "$REPRO_ROOT/ops" \
  --run-id scene-smoke-amdgpu-v1 \
  --steps 2
```

Admission requires the frozen scene, camera, fixed-base, gripper, collision,
and 250 Hz physics / 30 Hz policy contracts. A scene smoke is not learned-policy
evidence.

Run the canonical seed-1 online scripted G1 separately and retain its terminal
receipt for the later training preflight:

```bash
PYTHONPATH=src python tools/run_genesis_stack_bowls_scripted_g1.py \
  "$MANTIS_FIXED_URDF" "$BOWL_ASSET_ROOT" \
  --backend amdgpu \
  --generation-mode online \
  --seed 1 \
  --ops-root "$REPRO_ROOT/ops" \
  --run-id canonical-scripted-g1-seed1-v1
export SCRIPTED_G1_RECEIPT="$REPRO_ROOT/ops/canonical-scripted-g1-seed1-v1/receipt.json"
```

The receipt must carry the canonical online G1 claim, twelve clean terminal
strict rows, and zero safety failures. It does not prove learned-policy
success.

## 6. Demonstration generation and dataset export

The verified official-AMD baseline dataset uses exactly seeds `1001`, `1004`,
`1007`, and `1008`. Generate a probe and deterministic replay for each seed
with `tools/run_genesis_stack_bowls_scripted_g1.py`. Only replays whose stage
trace passes the strict task evaluator may enter the dataset. Failed probes and
replays remain negative evidence and must not be relabeled.

For each seed, first generate a fresh probe:

```bash
PYTHONPATH=src python tools/run_genesis_stack_bowls_scripted_g1.py \
  "$MANTIS_FIXED_URDF" "$BOWL_ASSET_ROOT" \
  --backend amdgpu \
  --generation-mode probe \
  --seed SEED \
  --probe-max-policy-steps 2400 \
  --ops-root "$REPRO_ROOT/ops" \
  --run-id "probe-SEED-v1"
```

Then replay the emitted `replay_plan.json` into another fresh run:

```bash
PYTHONPATH=src python tools/run_genesis_stack_bowls_scripted_g1.py \
  "$MANTIS_FIXED_URDF" "$BOWL_ASSET_ROOT" \
  --backend amdgpu \
  --generation-mode replay \
  --replay-plan "$REPRO_ROOT/ops/probe-SEED-v1/replay_plan.json" \
  --seed SEED \
  --capture \
  --ops-root "$REPRO_ROOT/ops" \
  --run-id "replay-SEED-v1"
```

Create `capture-manifest.json` next to the accepted NPZ and stage-trace files:

```json
{
  "schema_version": 1,
  "repo_id": "local/mantis_stack_bowls_multiseed4_reproduction_v1",
  "episodes": [
    {
      "seed": 1001,
      "npz": "seed1001/episode_seed_1001.npz",
      "stage_trace": "seed1001/stage_trace.json"
    }
  ]
}
```

Repeat the episode entry for all four exact seeds, then export to a fresh
LeRobot root:

```bash
export DATASET_ROOT="$REPRO_ROOT/datasets/mantis_stack_bowls_multiseed4_v1"
PYTHONPATH=src python tools/export_mantis_npz_to_lerobot.py \
  "$REPRO_ROOT/captures/capture-manifest.json" \
  "$DATASET_ROOT" \
  --allow-unverified-sim-gripper
PYTHONPATH=src python tools/audit_mantis_lerobot_dataset.py \
  "$DATASET_ROOT" \
  --output "$REPRO_ROOT/dataset-metadata-receipt.json"
PYTHONPATH=src python tools/audit_mantis_lerobot_dense.py \
  "$DATASET_ROOT" \
  --metadata-receipt "$REPRO_ROOT/dataset-metadata-receipt.json" \
  --episode-outcomes "$DATASET_ROOT/strict_episode_outcomes.json" \
  --output "$REPRO_ROOT/dense-audit.json"
```

The exact accepted official-AMD reference dataset has 4 episodes and 4,738
frames. A different total is a new dataset and must not reuse the reference
identity.

## 7. Frozen ACT training

Use the verified official-AMD baseline contract
`configs/act-rocm-baseline-v2.json`. The separate six-trajectory corrective
contract remains historical development material; its CUDA dependency
terminated `COMPLETE_NOT_PROMOTABLE`, so it is not substituted here.

Run preflight first with absolute, fresh paths and a separately verified
canonical scripted-G1 receipt:

```bash
export ACT_OUTPUT="$REPRO_ROOT/training/act-multiseed4-v2"
PYTHONPATH=src python tools/preflight_act_rocm.py \
  "$DATASET_ROOT" \
  local/mantis_stack_bowls_multiseed4_reproduction_v1 \
  "$ACT_OUTPUT" \
  --training-contract configs/act-rocm-baseline-v2.json \
  --dataset-receipt "$REPRO_ROOT/dataset-metadata-receipt.json" \
  --dense-receipt "$REPRO_ROOT/dense-audit.json" \
  --scripted-g1-receipt "$SCRIPTED_G1_RECEIPT" \
  --rocm-receipt "$REPRO_ROOT/rocm-runtime.json" \
  --output "$REPRO_ROOT/act-preflight.json"
```

Require `training_authorized=true`. With `HIP_VISIBLE_DEVICES=0`, launch the
exact emitted argument vector. Its expanded form is:

```bash
export HIP_VISIBLE_DEVICES=0
export ROCR_VISIBLE_DEVICES=0
export CUDA_VISIBLE_DEVICES=0
lerobot-train \
  --dataset.repo_id=local/mantis_stack_bowls_multiseed4_reproduction_v1 \
  --dataset.root="$DATASET_ROOT" \
  --policy.type=act \
  --policy.device=cuda \
  --output_dir="$ACT_OUTPUT" \
  --job_name=mantis_stack_bowls_act_rocm_v2 \
  --seed=20260723 \
  --steps=60000 \
  --batch_size=8 \
  --num_workers=4 \
  --save_freq=5000 \
  --eval_freq=5000 \
  --log_freq=100 \
  --save_checkpoint=true \
  --wandb.enable=false \
  --policy.chunk_size=30 \
  --policy.n_action_steps=30 \
  --policy.n_obs_steps=1 \
  --policy.push_to_hub=false
```

PyTorch exposes ROCm through the `cuda` device API; `torch.version.hip`, AMD
SMI, KFD process evidence, and the single visible Radeon device establish the
backend. Require natural exit code 0, twelve exact 5,000-step checkpoints, no
OOM/NaN/Traceback/RuntimeError signature, and terminal file manifests.
The command above is a reproduction command surface; it is not evidence that a
new clean-room run has started.

## 8. Open-loop and G3 closed-loop evaluation

Run saved-processor open-loop admission against a fresh output:

```bash
export CHECKPOINT_ROOT="$ACT_OUTPUT/checkpoints/060000"
PYTHONPATH=src python tools/run_act_openloop_inference.py \
  "$DATASET_ROOT" \
  --repo-id local/mantis_stack_bowls_multiseed4_reproduction_v1 \
  --pretrained-model "$CHECKPOINT_ROOT/pretrained_model" \
  --gate "$(pwd)/configs/act-openloop-inference-v3.json" \
  --interface "$(pwd)/configs/mantis-lerobot-interface-v1.json" \
  --port-config "$(pwd)/configs/mantis-port-config.json" \
  --fixed-plan "$(pwd)/configs/fixed-base-plan.json" \
  --output-dir "$REPRO_ROOT/openloop-v1"
```

Only after open-loop admission, run one fresh closed-loop directory for each
exact seed `101` through `110`:

```bash
PYTHONPATH=src python tools/run_genesis_act_closedloop_g3.py \
  "$CHECKPOINT_ROOT" \
  --seed SEED \
  --output-dir "$REPRO_ROOT/g3/seed-SEED-v1" \
  --gate "$(pwd)/configs/act-closedloop-g3-v1.json" \
  --task "$(pwd)/configs/task-pack-v1.json" \
  --port-config "$(pwd)/configs/mantis-port-config.json" \
  --fixed-plan "$(pwd)/configs/fixed-base-plan.json" \
  --scene-contract "$(pwd)/configs/stack-bowls-genesis-v1.json" \
  --camera-contract "$(pwd)/configs/camera-extrinsics-v1.json" \
  --source-task "$(pwd)/configs/source-task-stack-bowls-three.json" \
  --interface "$(pwd)/configs/mantis-lerobot-interface-v1.json" \
  --bowl-asset-root "$BOWL_ASSET_ROOT" \
  --mantis-urdf "$MANTIS_FIXED_URDF" \
  --backend amdgpu
```

Run seeds sequentially on one GPU. Do not change scene, camera, mapping,
controller, collision, timing, evaluator, or thresholds between seeds.
Aggregate success requires at least 6/10 successes, success rate at least 0.6,
and zero safety failures. The verified official baseline is honestly retained
as **0/10**, with eight `timeout` and two `collision_safety` failures. The
reproduction must preserve that outcome if observed; it must not replace failed
seeds or relabel a negative gate.

## 9. Final evidence requirements

For every terminal run preserve:

- exact command and environment identity;
- dataset/config/source hashes;
- before/during/after GPU and KFD process evidence;
- process exit code and UTC start/finish timestamps;
- checkpoint and output inventories;
- SHA-256 manifests verified independently with `sha256sum -c`;
- negative results and exact failure taxonomy.

Finally run the publication gate in `release` mode:

```bash
PYTHONPATH=src python tools/build_publication_candidate.py \
  --repository-root . \
  --config configs/publication-allowlist-v1.json \
  --output /workspace/persistent/mantis-track3/evidence/reproduction/publication-release-v1 \
  --mode release
```

Release mode must report `COMPLETE_RELEASE`. A dated historical candidate
reached that terminal with 246 allowlisted files, zero content findings, zero
promotion findings, 12/12 local Markdown links resolved, and 163 inventoried
provenance paths (`receipts/publication-release-20260729-v6/`). Local content
and integrity gates pass; an authorized public PR remains gated on independent
`RELEASE_GO`; no future release identity or acceptance result is asserted
here. The project license is selected:
original project source and documentation are licensed under Apache License
2.0, copyright holder Blueworm, copyright year 2026, decision recorded on
2026-07-29 (`LICENSE`, `docs/PROJECT_LICENSE_DECISION.md`). That license covers
only original project material; it does not license or authorize redistribution
of the Mantis URDF/meshes, derived materializations, private adapters, the
RoboTwin bowl asset, Genesis, LeRobot, datasets, checkpoints, or other
third-party material. Archive clean-room source review remains
`CLEANROOM_RUNNER_NO_GO` and neither runner executed, so no completed
reproduction is claimed.
