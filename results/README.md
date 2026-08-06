# Frozen submission results

This directory contains compact copies of the results cited by the report. It does not
contain training data, checkpoints, rollout videos, or every raw episode.

| Directory | Content |
|---|---|
| `runtime/` | Full `sample_actions()` performance and strict validation JSON/CSV/Markdown |
| `closed_loop/hip_graph/` | 100 episodes per fruit, eager vs HIP Graph summary |
| `closed_loop/targeted_compile/` | 100 episodes per fruit, eager vs compile summary |
| `residual_rl/` | Existing paired 100-episode residual-RL JSON results |
| `training/` | Verified historical checkpoint metadata and training-log summary |

HIP Graph and Targeted compile closed-loop tests use different seed ranges and must only
be compared with their own paired eager baselines.

The `params` blocks in frozen Residual-RL JSON files retain historical source-workspace
paths as provenance. Runnable commands use the portable `artifacts/` paths documented in
`docs/REPRODUCIBILITY.md`.
