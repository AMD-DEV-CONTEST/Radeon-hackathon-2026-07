# Official AMD corrective ACT training gate v2

Date: 2026-07-29  
Status: **PREPARED; EXECUTION UNAUTHORIZED AND BLOCKED**  
Authority: `configs/act-rocm-corrective-multiseed6-v2.json`

> Superseded path warning (2026-07-29): this frozen v2 gate uses the
> participant-supplied `/workspace/persistence` notice path, which is absent on
> the recreated official workspace. It remains execution-unauthorized and must
> not be run. A separately authorized successor must use
> `/workspace/persistent/mantis-track3`.

This gate preserves every scientific and safety invariant from
`docs/AMD_ACT_CORRECTIVE_TRAINING_GATE_V1.md` and changes only the future
Radeon Cloud storage boundary.

## Additional entry gates

Before any corrective run, all of the following must pass:

1. A fresh cloud instance and exact image inventory are recorded.
2. `/workspace/persistence` is observed as present and writable.
3. `tools/check_amd_persistence.py --check-filesystem` passes.
4. Dataset, training output, preflight receipt, evidence, external assets,
   caches, source, and Genesis resolve beneath
   `/workspace/persistence/mantis-track3`.
5. The restored dataset and retained checkpoint hashes match their local
   authorities.
6. A fresh, execution-ready version of
   `configs/amd-experiment-backup-219-v2.json` records the instance identity
   and destination.
7. The unchanged CUDA representative promotion dependency from v1 passes.
8. The user separately authorizes AMD execution.

The v2 config intentionally carries `execution_authorized=false`; the
preflight therefore cannot emit an authorized training result in the current
state.

## Planned paths

| Artifact | Fresh planned path |
|---|---|
| Dataset | `/workspace/persistence/mantis-track3/datasets/mantis_stack_bowls_multiseed6_gripper_v2_20260727_v1` |
| Preflight | `/workspace/persistence/mantis-track3/evidence/preflight/mantis_act_rocm_multiseed6_correction_20260729_v2` |
| Training output | `/workspace/persistence/mantis-track3/training/mantis_act_rocm_multiseed6_correction_20260729_v2` |
| Training evidence | `/workspace/persistence/mantis-track3/evidence/training/mantis_act_rocm_multiseed6_correction_20260729_v2` |

Reuse, overwrite, destructive migration, and fallback to a legacy
`/workspace/*` output are forbidden.

## Claim boundary

This is a local recovery and path-safety gate. It proves no cloud mount,
runtime, restored artifact, training, inference, corrected G3 result,
robustness, or AMD performance advantage.
