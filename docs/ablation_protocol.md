# Controlled Ablation Protocol

This document prevents the report from claiming an ablation before the result
file exists. All commands use the official ROCm interpreter.

## A. End-to-end visual behavior cloning baseline

```bash
/opt/venv/bin/python -m experiments.evaluate_visual_bc \
  --config configs/evaluate_visual_bc.yaml
```

Output: `results/evaluation_visual_bc.json`.

## B. Contact-gate ablation

This removes the dual-finger requirement from both the temporary grasp latch
and controller transport gate. It is intentionally an unsafe diagnostic mode,
not a deployment configuration.

```bash
/opt/venv/bin/python -m experiments.evaluate_visual_residual \
  --config configs/evaluate_visual_residual_no_contact_gate.yaml
```

Compare its `color_visual_servo` field with the production contact-confirmed
evaluation in `results/evaluation_visual_residual_action_robust.json`.

## C. Residual L2-prior ablation

Both runs start from `stage34.pt`, use seed 628, 32,768 timesteps and action
noise standard deviation 0.004. The only changed optimization parameter is
`residual_l2_coef`.

```bash
/opt/venv/bin/python -m experiments.train_visual_residual \
  --config configs/train_visual_residual_no_l2.yaml
/opt/venv/bin/python -m experiments.evaluate_visual_residual \
  --config configs/evaluate_visual_residual_no_l2.yaml
```

Compare with `results/evaluation_visual_residual_action_robust.json`. Report
both success/final distance and mean residual L2 norm; a lower norm alone is
not enough to establish a performance benefit.

## D. Phase-by-joint residual analysis

```bash
/opt/venv/bin/python -m experiments.analyze_visual_residual \
  --config configs/evaluate_visual_residual_action_robust.yaml \
  --results-path results/residual_phase_analysis.json
```

The output has an 8 by 9 table: mean absolute residual for each skill phase
and each joint. Plot that matrix as a heatmap only after the JSON is generated.

## E. ROCm policy optimization microbenchmark

```bash
/opt/venv/bin/python -m experiments.benchmark_rocm_policy_optimization \
  --config configs/benchmark_rocm.yaml \
  --results-path results/rocm_policy_optimization.json
```

It compares eager FP32, AMP FP16 and `torch.compile` policy inference. A
compiler failure is written to JSON and must be reported as unsupported rather
than hidden.
