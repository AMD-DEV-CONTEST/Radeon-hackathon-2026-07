# CPT Execution Contract V1

This layer freezes the executable continued-pretraining contract for canonical
TODO 0601–0650. It is deliberately split into mechanism evidence and runtime
evidence so a planning artifact cannot be mistaken for trained weights.

## Locally sealed mechanisms

The implementation seals 0601 and 0604–0643 as deterministic, tested local
mechanisms:

- an immutable Gemma base identifier and revision;
- an observed-ROCm-memory-only 4B/2B profile selector;
- twelve multimodal and GTM objectives, each with an explicit negative control;
- normalized modality/task mixtures and a gap-free three-stage curriculum;
- a frozen visual tower and ordered connector/adapter/language learning rates;
- isolated packing, gradient checkpointing, accumulation, BF16 and fixed seed;
- a six-hour wall-clock budget and resumable model/optimizer/scheduler/RNG state;
- train/validation loss, visual/language retention, schema, Claim grounding and
  state-prediction monitors; and
- gate-first checkpoint comparison that can reject the last checkpoint.

The executable configuration is
`config/cortex_x_v10_cpt_contract.json`. The planned card is
`evidence/v10/cpt-card.planned.json`.

## Evidence that remains open

TODO 0602, 0603 and 0644–0650 remain open until real execution produces:

- a frozen Base evaluation receipt;
- an observed Radeon ROCm/HIP memory receipt;
- token throughput, peak VRAM and an energy proxy;
- the exact admitted data revision and observed learning curve;
- an observed CPT Card; and
- a content-addressed frozen CPT checkpoint.

The planned card therefore uses `null` for every runtime metric and sets
`training_observed=false` and `promotion_eligible=false`. AMD Token Factory
responses may review this contract, but they are not weight-training evidence.

## Promotion rule

A checkpoint is admissible only if it passes all retention and capability
floors. Selection then uses the declared weighted score. The final checkpoint
has no special status; a better earlier checkpoint must win, and a late
checkpoint that regresses visual or language retention must be rejected.
