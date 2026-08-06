# Adapter pseudo-MoE execution contract V1

This workstream implements the serving control plane for TODO 0801–0850 while
preserving a strict boundary between a role definition and a trained role
adapter. Evidence, Strategy, Creative, Copy, Art, Channel, Compliance, Memory,
Planner and Critic are present as typed capability templates. Every template
remains `training_observed=false` until a real content-addressed weight artifact
and all regression receipts exist.

## Verified mechanical surface

- The router makes a deterministic decision from task capability, uncertainty,
  market and risk. Risk forces Compliance; high uncertainty forces Critic.
- The registry is append-only, content-addressed, versioned and rollbackable.
- The cache is byte-bounded LRU and cannot evict the protected active adapter.
- The PEFT integration uses the official LoRA in-place hotswap API. A real tiny
  CPU integration probe verifies stable parameter storage and changed output;
  this is not reported as Radeon latency or model-quality evidence.
- The no-merge arm wins unless capability, safety, Claim and visual regression
  results are all observed and pass. TIES and DARE are research/implementation
  arms, not claimed executed merges.
- Main-model INT8 or lower precision is rejected without observed parity and a
  passed safety gate.
- The single-card plan admits one heavy base model, uses observed memory only,
  caps admission at 90%, and unloads the old heavy model before a swap.

## Open neural work

Real role-adapter training, teacher-output admission, offline GKD, merge
ablation, BF16/FP16 exports, INT8 auxiliary export, interference/safety/Claim/
visual regression, Radeon latency/memory, compression and final Stack V1 freeze
remain open. Their fields in the planned card are `null`, not zero.

Primary method references are the official [PEFT hotswap documentation](https://huggingface.co/docs/peft/package_reference/hotswap),
official [PEFT merge guide](https://huggingface.co/docs/peft/developer_guides/model_merging),
[TIES-Merging](https://arxiv.org/abs/2306.01708), and
[DARE](https://arxiv.org/abs/2311.03099). Referencing a method does not claim its
published gains were reproduced.
