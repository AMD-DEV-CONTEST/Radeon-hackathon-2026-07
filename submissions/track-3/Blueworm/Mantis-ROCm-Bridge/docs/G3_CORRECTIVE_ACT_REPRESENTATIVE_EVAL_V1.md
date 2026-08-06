# G3 corrective ACT representative evaluation v1

Date: 2026-07-27  
Status: **FROZEN; code gate required before GPU launch**  
Authority: `configs/act-corrective-representative-g3-v1.json`

## Objective

Evaluate whether the one admitted intervention—expanding successful ACT
training trajectories from four to six episodes—improves the previously
observed representative G3 terminal-outcome taxonomy without introducing a
new safety failure.

This is a bounded CUDA development comparison. It is not official AMD
evidence and cannot establish a G3 pass.

## Frozen inputs

- Training terminal receipt:
  `receipts/4090-act-multiseed6-training-final-20260727-v1/`
- Checkpoint:
  `/data01/suzw_data/tron/amd_track3/training/mantis_act_cuda_multiseed6_20260727_v1/checkpoints/060000`
- Checkpoint-manifest SHA-256:
  `7284bc690e6238dd5378944cf05c4c56994edd7a341f464fe8f8b24cd61a8844`
- Single correction:
  `configs/act-trajectory-distribution-correction-v1.json`
- Ordered representative seeds: `101`, `107`, `108`
- Physical GPU: RTX 4090 index `0`, one process at a time
- Evidence mode: `cuda_diagnostic_replay`,
  `competition_gate_eligible=false`

The ACT architecture, training seed and budget, saved processors, policy
chunk, 30 Hz policy clock, 250 Hz physics clock, causal zero-order hold,
controller, camera calibration, state/action and gripper mappings, robot and
bowl geometry, reset distribution, allowed-contact matrix, collision
classifier, strict evaluator, thresholds, and seed identity remain unchanged.

## Baseline comparator

| Seed | Frozen baseline terminal | Safety failures |
|---|---|---:|
| 101 | `timeout` | 0 |
| 107 | `collision_safety` | 1 |
| 108 | `collision_safety` | 1 |

The comparator is the verified CUDA dynamic replay in
`receipts/g3-r1r2-dynamic-replay-20260727-v2/`, which reproduced the official
failure families under the unchanged policy/physics clock and queue.

## Pre-GPU code gate

Before any episode starts:

1. verify this package manifest and the 11-file checkpoint manifest;
2. verify the frozen diagnostic runner and core source hashes;
3. validate the corrective G3 JSON with `validate_config`;
4. run syntax checks and the focused closed-loop G3 test suite;
5. prove physical GPU0 has no compute process;
6. verify the CUDA compatibility shim and its prior zero-invocation preflight;
7. require fresh, non-existing batch and supervisor paths.

Any failed condition blocks the batch without starting GPU work.

## Per-seed evidence

Each seed must record:

- launch exit code and terminal receipt availability;
- `task_success`, `terminal_reason`, `safety_failure_count`, and policy-step
  count;
- diagnostic-record count and one-record-per-completed-policy-tick alignment;
- CUDA diagnostic identity and competition-ineligible status;
- compatibility-shim invocation count exactly zero;
- GPU0 before/after process evidence;
- immutable episode and supervisor manifests.

## Decision matrix

Evidence completeness requires all three ordered seeds, valid terminal
receipts, aligned diagnostics, zero infrastructure failures, and zero shim
invocations.

Safety non-regression is evaluated per seed: the corrected policy may not
exceed the frozen baseline safety count for that same seed. In particular,
seed 101 must remain safety-clean.

Strict improvement requires at least one of:

1. one or more strict task successes; or
2. fewer than two total safety failures,

while the per-seed safety non-regression rule holds.

Only an evidence-complete, strictly improved, safety-nonregressing result may
advance to a fresh official single-Radeon exact-seed 101–110 G3 evaluation.
Failure to promote is retained as negative evidence; it does not authorize a
second simultaneous correction.

## Claim boundary

This representative comparison tests one correction on three already-known
failure seeds on NVIDIA CUDA. It does not prove training convergence, official
AMD/ROCm execution, 6/10 G3 success, generalization, robustness, unseen-scene
performance, real-robot safety, or an AMD performance advantage.
