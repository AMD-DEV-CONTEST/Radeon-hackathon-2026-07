# G3 single-correction contract — ACT trajectory distribution v1

Date: 2026-07-27  
Status: **FROZEN; dataset and development training complete; representative evaluation frozen**  
Authority: `configs/act-trajectory-distribution-correction-v1.json`

## Decision

The first corrective experiment changes exactly one independent variable:
the empirical distribution of accepted successful Mantis demonstrations used
to train ACT. The four original training episodes (1001, 1004, 1007, 1008)
are retained and two independently accepted episodes (1012, 1016) are added.
The resulting dataset must contain six episodes and 7,085 frames.

The ACT architecture, random seed, optimizer schedule, 60,000-step budget,
batch size, normalization, action chunk, controller, 250 Hz→30 Hz timing,
joint/gripper projection, robot and bowl geometry, cameras, reset
distribution, evaluator, collision logic, thresholds, and evaluation seeds
remain unchanged.

## Causal basis

The exact CUDA R1/R2 replay reproduced the official timeout and collision
families and excluded action-queue or 250 Hz→30 Hz clock drift. It also
measured target/readback error at the collision terminals.

The follow-up commanded-target counterfactual evaluated collision geometry at
the recorded ACT target configurations without advancing physics:

- seed 107 target configurations entered the bowl1/right-wrist/source-mesh
  collision family at steps 27 and 28;
- seed 108 target configurations entered the bowl2/right-wrist/source-mesh
  collision family at steps 25, 26, and 27;
- all pose admissions passed, and the compatibility shim invocation count
  remained zero.

Therefore controller tracking error is observable but is not required to
produce the diagnosed collision family. Changing gains, forces, geometry, or
the safety classifier would confound the first corrective comparison. The
selected intervention instead changes the learned action-trajectory
distribution while preserving the physical and evaluation protocols.

## Dataset admission

Each of the six raw captures must independently satisfy:

1. exact NPZ and stage-trace SHA-256 match the correction contract;
2. successful `competition_strict_v1` stage trace;
3. 12 strict final-stability rows and zero safety failures;
4. 30 Hz timestamps, 16D exported state/action, and the frozen three-camera
   shapes;
5. LeRobot metadata, dense-frame, and direct-runtime sample-decode gates.

The exporter must use a fresh, non-existing dataset root. A partial staging
directory is negative evidence and must not be promoted.

### Completed dataset gate

The fresh dataset
`mantis_stack_bowls_multiseed6_gripper_v2_20260727_v1` contains exactly six
accepted episodes and 7,085 frames. Source admission, metadata, dense all-frame
audit, real LeRobot CPU decode, and direct Parquet decode all pass. The initial
decode audit failed closed only because CUDA was visible in a CPU-only evidence
gate; the dataset was left unchanged and a fresh audit with
`CUDA_VISIBLE_DEVICES=""` passed. Receipt:
`receipts/4090-multiseed6-trajectory-correction-20260727-v1/`.

## Controlled development experiment

After dataset admission, train ACT from scratch on one RTX 4090 with the exact
`configs/act-rocm-baseline-v2.json` architecture and hyperparameters. The
training random seed remains 20260723. Evaluate checkpoint 060000
sequentially on seeds 101, 107, and 108 under the frozen G3 protocol.

The single-step CUDA runtime and checkpoint gate passes in
`receipts/4090-act-multiseed6-training-smoke-20260727-v1/`. The formal
60,000-step run completed with training and supervisor exit codes `0/0` at
`/data01/suzw_data/tron/amd_track3/training/mantis_act_cuda_multiseed6_20260727_v1`
on physical GPU0 only. It produced the exact twelve 5,000-step checkpoints
through 60,000, 600 raw metric records, zero exact fatal signatures, and
verified output and terminal-evidence manifests. Terminal receipt:
`receipts/4090-act-multiseed6-training-final-20260727-v1/`.

The executable representative comparison is frozen in
`configs/act-corrective-representative-g3-v1.json` and
`docs/G3_CORRECTIVE_ACT_REPRESENTATIVE_EVAL_V1.md`. It must pass its CPU code
gate before sequential single-GPU CUDA evaluation of seeds 101/107/108.

Promotion requires an improved representative terminal-outcome taxonomy and
no additional safety failure. A promoted correction is then retrained and
evaluated on the official single-Radeon ROCm worker; CUDA evidence never
substitutes for AMD evidence.

## Evidence boundary

The target counterfactual supports selection of a policy-data intervention; it
does not prove that six episodes are sufficient or that retraining will pass
G3. Dataset acceptance does not prove training convergence or task success.
Only a fresh official-AMD exact-seed 101–110 evaluation can establish the
corrected G3 result.
