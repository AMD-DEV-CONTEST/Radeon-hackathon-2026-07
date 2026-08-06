# ProofLaunch Trajectory KD V1

This subsystem closes the gap between a golden-only task seed and a usable
trajectory-distillation seed. It does not claim that a model has been trained.

## Matched counterfactual collection

Every one of the 152 project-owned synthetic GTM tasks produces three records
against the same task fixture and environment revision:

- a clean positive trajectory, classified as success, fallback, stop, or human
  escalation according to the frozen operation oracle;
- a terminal negative trajectory that exhausts its action budget while leaving
  the issue unresolved;
- a recovery trajectory that records one rejected action followed by a verified
  retry and safe termination.

This matched construction controls task difficulty and input evidence when
comparing correct, failed, and recovered behavior.

## Role-local trajectories

Each outcome is decomposed into four independent visible traces:

- Planner: emits a bounded typed plan;
- Worker: preserves every observation, action, tool response, and next state;
- Critic: issues a kind-aware mechanical verdict;
- Supervisor: admits a positive/recovery trace or rejects a negative trace.

The records contain visible decision codes, hashes, and tool-state transitions;
they contain no hidden chain of thought.

## Policy supervision and rewards

Deployment-visible examples cover four bounded policies: stop, retry, fallback,
and single-request human escalation. Step rewards preserve correctness, safety,
progress, efficiency, recovery, and terminal signals separately. Trajectory
rewards preserve terminal success, verifier result, first-error repair, safe
stop, and efficiency. No single final-answer label replaces the step evidence.

Four additional visible execution-skill targets are compiled from every matched
trajectory: ordered task-decomposition DAGs, tool choice from an explicit
allowlist, exact-schema argument filling, and observation compression that must
retain every required fact hash inside a 128-token ceiling. All four remain
project-owned synthetic supervision; no hidden or privileged reasoning is
stored.

## Hierarchical credit and temporal curriculum

Planner, Worker, Critic, and Supervisor retain separate planning, execution,
detection, repair, supervision, and error-penalty fields. Error penalties apply
only to an explicit origin, amplifier, or missed detector. A downstream Worker
error therefore cannot silently penalize an upstream Planner. Recovery credit
does not erase the original error label.

The temporal curriculum uses role-local trace length and admits training
partitions in three immutable stages: one-step short traces, two-to-three-step
medium traces, then four-step long traces. Here “long” is relative to the
bounded four-action mechanical environment; it is not evidence of long-horizon
model performance. Validation and evaluation remain held out.

## Diagnostics and ablations

The runtime monitors mean categorical trajectory KL, post-first-error
compounding, controlled tool-noise sensitivity, and repeated state/action
loops. Controlled fixtures prove detector behavior; they are not model logits
or live-tool reliability measurements.

Three executable information contracts are frozen: full trajectory
supervision, no trajectory supervision, and final-answer-only KD. They expose
which metrics are scorable under each arm, but do not claim an ablation uplift
until all three arms train and run on the same held-out benchmark.

## Truth boundary

The corpus is a deterministic, project-owned mechanical seed. It is not a
human-authored 4A corpus, a trained adapter, an online-RL result, a calibrated
reward model, a Radeon execution receipt, or evidence of product uplift.
