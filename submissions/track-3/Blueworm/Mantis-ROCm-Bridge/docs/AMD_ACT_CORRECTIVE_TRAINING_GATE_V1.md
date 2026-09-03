# Official AMD corrective ACT training gate v1

Date: 2026-07-27  
Status: **PREPARED; EXECUTION BLOCKED BY CUDA REPRESENTATIVE GATE**  
Authority: `configs/act-rocm-corrective-multiseed6-v1.json`

## Objective

Prepare one reproducible single-Radeon ACT optimization run that changes only
the empirical distribution of successful training trajectories from four
episodes / 4,738 frames to six episodes / 7,085 frames.

No GPU execution is authorized by this document. The package becomes
executable only after the frozen CUDA representative evaluation of seeds
101/107/108 terminates `COMPLETE_PROMOTABLE`.

## Frozen causal intervention

The only changed independent variable is the successful demonstration
trajectory distribution:

- retained seeds: `1001`, `1004`, `1007`, `1008`;
- added seeds: `1012`, `1016`;
- corrected dataset: 6 episodes / 7,085 frames;
- correction authority:
  `configs/act-trajectory-distribution-correction-v1.json`.

The ACT architecture, optimizer, training seed, 60,000-step budget, batch
size, checkpoint cadence, policy chunk, state/action interface, cameras,
250 Hz physics / 30 Hz policy clock, controller, robot and bowl geometry,
collision classification, evaluator, thresholds, and G3 seeds remain frozen.

## Entry criteria

All conditions must be true:

1. `configs/act-corrective-representative-g3-v1.json` has a complete terminal
   receipt with status `COMPLETE_PROMOTABLE`.
2. The six-seed source dataset and
   `receipts/4090-multiseed6-trajectory-correction-20260727-v1/` still verify.
3. The official worker exposes exactly one AMD Radeon device through
   ROCm-enabled PyTorch and a fresh strict `tools/check_rocm.py` receipt passes.
4. The dataset is copied to the planned `/workspace` root and its archive,
   source files, metadata, dense audit, LeRobot 0.4.4 sample decode, and direct
   Parquet decode all pass on the official worker.
5. The canonical scripted G1 and project tests pass on the promoted source.
6. The planned preflight, output, and evidence roots do not exist.
7. No GPU/KFD process is active before launch.

Failure of any entry criterion blocks execution without altering the CUDA
representative result, original AMD baseline, or prior negative G3 evidence.

## Planned official paths

| Artifact | Fresh planned path |
|---|---|
| Dataset | `/workspace/mantis_stack_bowls_multiseed6_gripper_v2_20260727_v1` |
| Preflight | `/workspace/mantis_act_rocm_multiseed6_correction_preflight_20260727_v1` |
| Training output | `/workspace/mantis_act_rocm_multiseed6_correction_20260727_v1` |
| Supervisor evidence | `/workspace/mantis_act_rocm_multiseed6_correction_training_evidence_20260727_v1` |

These are planned identities, not assertions that the paths exist. Reuse or
overwrite is forbidden.

## Non-executing preflight

After the entry criteria pass, construct the exact command with:

```bash
PYTHONPATH=src python tools/preflight_act_rocm.py \
  /workspace/mantis_stack_bowls_multiseed6_gripper_v2_20260727_v1 \
  local/mantis_stack_bowls_multiseed6_gripper_v2_20260727_v1 \
  /workspace/mantis_act_rocm_multiseed6_correction_20260727_v1 \
  --training-contract configs/act-rocm-corrective-multiseed6-v1.json \
  --dataset-receipt /ABSOLUTE/FRESH/amd-dataset-metadata.json \
  --dense-receipt /ABSOLUTE/FRESH/amd-dense-audit.json \
  --scripted-g1-receipt /ABSOLUTE/VERIFIED/scripted-g1-receipt.json \
  --rocm-receipt /ABSOLUTE/FRESH/rocm-runtime.json \
  --output /workspace/mantis_act_rocm_multiseed6_correction_preflight_20260727_v1/preflight.json
```

Only the emitted argument vector may be launched, and only when
`training_authorized=true`. The preflight builds a command; it does not execute
training.

## Execution and evidence invariants

- expose exactly GPU0 with `HIP_VISIBLE_DEVICES=0`,
  `ROCR_VISIBLE_DEVICES=0`, and `CUDA_VISIBLE_DEVICES=0`;
- run one training process and one owned supervisor;
- record exact command, environment, package freeze, source/config/dataset
  hashes, process identity, UTC timestamps, and GPU/KFD state;
- sample device telemetry periodically without changing the workload;
- preserve checkpoints at exact 5,000-step intervals through step 60,000;
- detect exact OOM, NaN, Traceback, and RuntimeError signatures;
- never infer convergence or task success from loss;
- create `output.SHA256SUMS` and `final_evidence.SHA256SUMS` after natural
  process termination;
- never overwrite the original four-seed AMD training output or G3 evidence.

## Terminal conditions

`COMPLETE_TRAINING_EVIDENCE` requires:

- natural training and supervisor exit codes `0/0`;
- exact final step 60,000;
- twelve checkpoints `005000` through `060000`, each with the expected
  LeRobot file inventory and matching hashes;
- finite descriptive metrics and zero exact fatal signatures;
- before/during/after single-Radeon telemetry;
- independently verified output and final-evidence manifests.

Any other result is a versioned negative or blocked receipt. Training
completion authorizes only a fresh open-loop admission step. It does not
authorize a positive G3 claim.

## Downstream order

1. saved-processor open-loop admission on the same single Radeon GPU;
2. exact G3 seeds 101–110, sequentially, under the unchanged protocol;
3. G4 only if G3 reaches at least 6/10 successes with zero safety failures.

## Claim boundary

This prepared package proves only that the official-AMD corrective run is
specified and locally contract-tested. It does not prove that the six-seed
dataset is present on AMD, that training has started or completed, that the
correction is effective, that G3 passes, or that AMD has a performance
advantage.
