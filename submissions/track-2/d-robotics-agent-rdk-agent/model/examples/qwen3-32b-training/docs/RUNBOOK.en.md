> Chinese version: [RUNBOOK.md](RUNBOOK.md)

# Formal Training Runbook

## 1. Scope

This runbook describes only the verified single-GPU, 48 GB AMD path for `Qwen3-32B-bnb-4bit`. The core source files retain their original bytes; this directory does not attempt to “generalize” the hardware, data, or hyperparameters.

Canonical layout:

```text
/workspace/qwen36-agentic-sft/
├── .venv/
├── configs/
├── artifacts/training-plan/
├── artifacts/model-acquisition/
├── data/rdk-sft-v1-20260803-agentic/
├── models/Qwen3-32B-bnb-4bit-7f721e74/
└── runs/<fresh-run-id>/
```

## 2. Frozen Training Contract

- QLoRA: rank 8, alpha 16, dropout 0; targets are the q/k/v/o and gate/up/down projections
- Base compute: BF16; LoRA and AdamW state: FP32
- Assistant-only shifted CE; every optimizer step is normalized by the frozen supervised-token total
- Maximum 8192 tokens; no packing and no padding; long samples use frozen semantic-boundary windows and absolute position IDs
- 119 steps; validation at 0/30/60/90/119
- Checkpoints at 10/20/.../110/119
- Run `synchronize -> gc.collect -> empty_cache` after every micro backward
- Controller sampling every 250 ms, with a 44 GiB GPU hard limit and 48 GiB CPU hard limit

## 3. Phase 1 / Phase 2 Semantics

Phase 1 must be a fresh run and must not use `--resume`. It exits with `exit 75` after publishing the immutable `checkpoint-000010`; the Controller should classify it as `PASS / RESTART_READY`.

Phase 2 must be a fresh process and may use only:

```text
--resume <same-run>/checkpoints/checkpoint-000010
```

After GPU runtime initialization, the Trainer revalidates the adapter, optimizer, RNG, state, manifest, and Phase 1 process identity item by item, then atomically publishes `resume-ack-phase2.json`. The normal terminal state for Phase 2 is `exit 0 / PASS` plus `checkpoint-000119/COMPLETE`.

Once `resume-ack-phase2.json` exists, Phase 2 is one-shot. If a later failure occurs, do not delete the acknowledgment/checkpoint and rerun in place; perform a new recovery audit.

## 4. Historically Verified Commands

The complete argv and 13 environment variables are preserved verbatim in:

- Phase 1: `evidence/launch/launch-binding.json`
- Phase 2: `evidence/launch/phase2-launch-binding.json`

These two files prove the historical commands; they are not launchers for a new run. A new formal run must first complete identity, GPU-idle, process-exclusion, input-hash, and resource checks, then issue a new read-only authorization/launch binding for the new run ID.

Core Controller assembly differences:

| Item | Phase 1 | Phase 2 |
|---|---|---|
| controller run dir | `<run>/phase1-controller` | `<run>/phase2-controller` |
| expected exit | `75` | `0` |
| expected result | `RESTART_READY` | `PASS` |
| trainer phase | `phase1` | `phase2` |
| resume | forbidden | exact `checkpoint-000010` |

## 5. Restoring Weights and Permissions

Restore the four model shards and rehash each file against the verification JSON. Canonical inputs must be read-only: directories `0555`, files `0444`. Trainer, common code, plans, model verification, data, and model files must have neither write bits nor symbolic links.

Do not overwrite a published run. Use a new safe run ID for every formal training run; never use automatic recovery from `latest`.

## 6. Verification Boundary

The current bundle proves source equivalence, the data/plan contract, canonical Phase 1/2 execution, and checkpoint publication. After restoring the weights, fresh-launch readiness on the target machine still requires an independent preflight. Moving to another machine requires refreezing the entire contract.
