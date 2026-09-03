# G3 single-correction contract — targeted failure-state coverage v2

Date: 2026-07-28  
Status: **FROZEN; collection not yet started**  
Authority: `configs/act-targeted-failure-state-coverage-v2.json`

## Decision

The next corrective experiment changes exactly one independent variable:
the empirical distribution of successful Mantis training trajectories.
Everything in the simulator, controller, policy architecture, optimizer,
timing, mapping, evaluator, and evaluation split remains frozen.

The predecessor six-episode dataset produced a valid ACT checkpoint but did not
change the causal G3 failure families. Seed 101 remained a no-interaction
timeout. Seeds 107 and 108 retained the right-wrist/source-mesh collision
family, with more contacts after correction. The new collection therefore
targets successful trajectory coverage rather than changing controller,
geometry, or safety semantics.

## Candidate allocation

The already frozen training allocation supplies seeds 1021–1050. All 30 seeds
are disjoint from evaluation seeds and were unattempted when this contract was
frozen.

Every candidate is attempted exactly once, in ascending order, using a
two-stage CPU-only Genesis protocol:

1. probe the source-distribution reset and write a hash-linked replay plan;
2. replay that exact plan once with capture enabled, but only if the probe
   passes.

There is no retry, seed substitution, replay fallback, trajectory ranking, or
post-hoc rejection of an admitted candidate. Every candidate passing the
frozen per-candidate gate enters the dataset.

## Coverage gate

The collection may proceed to dataset export only when all of the following
hold:

- all 30 predeclared candidates have terminal audit records;
- at least six new candidates pass the complete probe and capture gate;
- at least two admitted trajectories begin with a left-arm grasp;
- at least two admitted trajectories begin with a right-arm grasp;
- at least two admitted trajectories complete the top placement with the
  right arm;
- every admitted trajectory has a complete eight-stage trace, exactly 12
  strict stability frames, zero safety failures, and a captured NPZ;
- no GPU compute process is observed at any frozen collection guard.

The predecessor set already includes left-first and right-first trajectories,
but no successful top-right placement. The final stratum is therefore a direct
coverage falsification test, not a success-threshold relaxation. Failure to
reach any aggregate threshold produces
`COMPLETE_INSUFFICIENT_COVERAGE`; training remains forbidden.

## Dataset and training progression

If the coverage gate passes, create a fresh LeRobot dataset containing the six
predecessor episodes plus every newly admitted episode in ascending seed order.
The dataset must pass source hash, metadata, dense all-frame, direct LeRobot
sample, and direct Parquet decode gates.

Only after dataset admission may ACT be trained from scratch for 60,000 steps
on one RTX 4090. The training seed and every hyperparameter remain identical to
`configs/act-rocm-baseline-v2.json`. Checkpoint 060000 is then evaluated on
seeds 101, 107, and 108 in that exact order under the unchanged G3 protocol.

Official AMD corrective training is gated by
`COMPLETE_PROMOTABLE`. CUDA collection, training, and replay evidence never
substitute for Radeon/ROCm evidence.

## Evidence boundary

Successful scripted demonstrations prove only admissible training samples.
They do not prove learned-policy success, G3 passage, generalization,
robustness, real-robot safety, official AMD execution, or a performance
advantage.
