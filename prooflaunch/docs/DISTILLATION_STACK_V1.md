# Distillation Stack V1

Distillation Stack V1 closes the execution-contract gap between a generic teacher episode and a runnable, falsifiable experiment. It does not claim that training has run, that an adapter has improved, or that an external model is licensed for training.

## Twelve bounded lanes

The frozen registry contains exactly twelve source-ordered lanes: model logits, projected hidden features, visual crops, layout graphs, video temporal events, visible Agent plans, tool calls, stop decisions, failure attribution, 4A critique abstractions, audit repairs, and mature workflow transitions. Every lane has a content alignment key, explicit loss, at least two objective metrics, a two-hour GPU ceiling, an output-rights gate, and a ban on hidden reasoning.

Visual crops bind an approved source image hash to a normalized in-bounds box. Layout targets bind unique nodes, directed constraints, and complete reading order. Video targets require strictly increasing timestamps inside the source duration. Agent targets contain only visible observations and typed public events; chain-of-thought, private scratchpads, and other hidden reasoning fields are rejected.

The 4A critique lane permits only owned, licensed, or synthetic material and rights-approved derived abstractions. Public campaign work can inform research questions, but the original creative asset or unauthorized hosted-model output cannot enter this training lane.

## Matched five-arm control

The exact controls are CaOPD, offline KD, on-policy KD, self-KD, and no-KD. They share a frozen base revision, dataset hash, evaluation hash, hardware fingerprint, random seed, and train-token ceiling. A result is invalid if any of those matched variables differs silently.

The four required result measures are mechanically defined:

- capability retention sums `min(before, after)` per capability, so a gain in one capability cannot hide a regression in another;
- expected calibration error is calculated from aligned confidence, prediction, and label rows;
- token efficiency is verified successes per 1,000 generated tokens;
- wall-clock benefit is the same-hardware baseline duration divided by candidate duration.

## Teacher elimination and truth boundary

A teacher is eliminated when its revision is unverified, output-training rights are not approved, fewer than 30 examples were observed, or measured information gain is below 0.02. A model name discovered in marketing or a third-party router is not enough. MiniMax-H3 now has an official callable API identity, but it remains outside teacher training until its exact revision, hosted-output rights, and measured information gain pass the same gates; API availability alone is not training permission.

The generated Distillation Card remains planned: runtime metrics, teacher winner, control winner, adapter, and promotion are all null. Synthetic mechanical values prove formula execution only and must not be quoted as model quality.

## Artifacts

- `config/cortex_x_v10_distillation_stack_v1.json` — frozen lanes, controls, teacher gates, planned card, and content hash.
- `evidence/v10/distillation-stack-v1-mechanical-fixture.json` — deterministic synthetic computations and zero-runtime truth receipt.
- `src/prooflaunch_remix/v10_distillation_stack.py` — executable target, control, metric, elimination, and card contracts.
- `tests/test_v10_distillation_stack.py` — negative and positive mechanical verification.
