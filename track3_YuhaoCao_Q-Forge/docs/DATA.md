# Data and Evaluation Splits

## Expert demonstrations

Q-Forge uses LIBERO-Spatial demonstrations to initialize SmolVLA. The experiment
matrix contains 10-, 20-, and 50-demonstration SFT variants; the primary result
uses 20 demonstrations. LIBERO data is third-party content and is not redistributed
in this repository. Obtain it under the upstream project's terms.

## Automatically labeled policy rollouts

The Base policy generates additional trajectories in LIBERO. Labels are not model
pseudo-labels: simulator reward and terminal success are the supervision. We call
them self-labeled in the operational sense of automatically labeled,
policy-generated interaction.

The primary dataset contains 300 episodes and 60,505 transitions:

- 50 reset states;
- 6 episodes per state;
- action-noise schedule `{0.00, 0.01, 0.03, 0.03, 0.05, 0.05}`;
- gripper action is not perturbed;
- rollout seed family begins at 3300;
- 36/50 states contain both success and failure outcomes.

This same-state outcome diversity is essential for learning useful local action
gradients.

## Task 3 replication data

The second-task replication uses LIBERO-Spatial Task 3: *pick up the black bowl
on the cookie box and place it on the plate*. The supervised dataset is formed
by sorting the public task-specific episodes by global episode index and taking
the first 20, without filtering by trajectory length or outcome.

The same local-perturbation protocol produces:

- 300 policy rollouts from 50 reset states;
- 38,509 transitions;
- 225 successful and 75 failed episodes;
- 22/50 reset states with both successful and failed outcomes.

Task 3 uses the same 0–39 critic-training and 40–49 critic-validation state split
and the same paired inference seed 2001 for the final four-way comparison.

## Splits

- critic training reset states: 0–39;
- critic/guidance validation reset states: 40–49;
- reported closed-loop benchmark: reset states 0–49, seed 2001.

The final 50-state benchmark includes the guidance-validation states, so it should
not be interpreted as an untouched test-state split. The closed-loop inference
trajectories remain distinct from the rollout-training trajectories through their
different seed protocols.

## Storage and privacy

Raw rollout pickle files, image streams, feature caches, and model checkpoints are
large generated artifacts and are excluded from the source repository. They
contain simulated robot observations rather than personal data. Commands to
regenerate them are in `REPRODUCTION.md`.
