# Pull Request

## Title

`Track 3, Yuhao Cao, Q-Forge`

## Description

This pull request submits **Q-Forge** to **Track 3: Physical AI**.

Q-Forge is a self-labeled value-guidance pipeline for improving a flow-matching
SmolVLA robot policy on AMD Radeon. Starting from 20 expert demonstrations, the
policy collects locally perturbed LIBERO rollouts, the simulator automatically
labels success and failure, and a conservative five-member Q ensemble learns
action-sensitive local value. At inference, constrained Q-gradient ascent makes
small corrections around the Base action. An optional residual-distillation path
removes the critic from deployment.

On the primary paired 50-state LIBERO-Spatial Task 7 evaluation, Q-guidance
improves success from **21/50 (42%) to 34/50 (68%)**, with 19
failure-to-success transitions, 6 regressions, and an exact two-sided McNemar
`p=0.0146`. A second Task 3 replication improves a stronger Base from
**38/50 (76%) to 44/50 (88%)**.

The complete workflow was run on one AMD Radeon `gfx1100` GPU with 96 compute
units and 48 GiB VRAM.

## Included deliverables

- English technical report
- Complete source code, configurations, tests, and compatibility patch
- Detailed reproduction guide and AMD/ROCm notes
- 4-minute-39-second English demonstration video
- Audited result summaries and machine-readable evidence
- Attention-backend and inference-optimization supplementary reports

The submission index is available at
`track3_YuhaoCao_Q-Forge/SUBMISSION.md`.

## Participant

**Yuhao Cao** — sole participant; project conception, system design,
implementation, AMD ROCm adaptation, experimentation, evaluation,
visualization, video production, and documentation.
