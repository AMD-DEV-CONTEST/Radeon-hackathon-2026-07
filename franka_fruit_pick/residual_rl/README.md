# Privileged-state residual SAC

This package trains or evaluates a bounded 9-D residual correction on top of a frozen
SmolVLA policy. The current actor uses simulation privileged state and is therefore an
exploratory simulator policy, not a deployable visual residual controller.

From the repository root, reproduce the lift-only training configuration with:

```bash
bash scripts/train_residual_sac_lift.sh
```

Use `DRY_RUN=1` to print the command without loading the dataset, policy, or simulator.

External artifacts:

```text
artifacts/models/smolvla_fruit_pick_dr_600ep/
artifacts/models/plum_residual_sac_lift/last.pt
artifacts/datasets/fruit_pick_dr_600ep/
```

Paired evaluation:

```bash
python -m franka_fruit_pick.residual_rl.evaluate \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --residual-checkpoint artifacts/models/plum_residual_sac_lift/last.pt \
  --repo-id demo/fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --episodes 100 --seed 2000 \
  --out reproductions/residual_rl/lift_no_gate_100ep.json
```

Saved preliminary result: 34/100 baseline to 43/100 residual. It has not been validated
on an independent seed set. Existing ablations are under `results/residual_rl/`.
