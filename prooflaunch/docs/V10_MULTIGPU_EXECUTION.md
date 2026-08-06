# V10 multi-GPU execution contract

The 1,500-item program is multi-GPU-first, but it does not pretend that every
atomic requirement is GPU compute.

- Every TODO binds to one supervisor-owned multi-GPU DAG, dependency barrier,
  rank inventory, atomic stage commit, single-GPU equivalence check, and
  truthful fallback rule.
- Training defaults to DDP when a complete replica fits each GPU. FSDP2 is the
  memory fallback after an equivalence preflight. Training with
  `device_map=auto` is forbidden.
- Evaluation and media jobs shard stable sample IDs, prompts, or seeds exactly
  once across ranks. Data work uses deterministic rank-sharded preprocessing.
  Administrative and control-plane work runs on one state owner and
  participates in global barriers without manufacturing GPU utilization.
- A direct multi-GPU claim requires at least two physical Radeon GPUs, ROCm,
  an RCCL collective preflight, every-rank receipts, zero duplicate/missing
  shards, atomic checkpoints, three cold launches, two resume trials for
  training, and equivalence to the frozen single-GPU baseline.
- “Fastest” is admitted only after correctness, with identical immutable
  revisions, global batch, steps, seeds, precision, and output contract. The
  two-GPU floor is 1.5× throughput and 70% parallel efficiency across three
  repeats.

The single-GPU baseline and each multi-GPU repeat use the same distributed
trainer and global-batch invariant. `verify_multigpu_training_admission.py`
checks every rank receipt, immutable comparison contract, final validation
loss, median speedup, and parallel efficiency before a promoted multi-GPU
claim is allowed.

## Non-blocking accelerator portability

Product delivery does not depend on AMD instance availability. The same
immutable model revision, dataset revision, data split, seed, global batch,
BF16 policy, LoRA boundary and evaluation contract can run through either:

- `configs/accelerate/rocm_1gpu_baseline.yaml` / `rocm_2gpu_ddp.yaml` with
  `--accelerator-backend rocm`; or
- `configs/accelerate/cuda_1gpu_baseline.yaml` / `cuda_2gpu_ddp.yaml` with
  `--accelerator-backend cuda`.

`--accelerator-backend auto` selects only an observed HIP or CUDA runtime and
writes that backend into every rank receipt and the final manifest. A CUDA run
may advance model quality and product validation, but it is explicitly marked
ineligible as the competition's local Radeon evidence. No result is compared
across backends unless model/data revisions, global batch, steps, precision,
seed and frozen eval set match.

If the current Radeon instance exposes only one GPU, single-GPU work may
continue as a debugging fallback, but every direct multi-GPU evidence facet
remains unpassed. The generated contract is
`evidence/v10/multigpu-execution-plan.json`.
