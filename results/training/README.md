# Historical Training Record

English | [Chinese version](README_ZH.md)

This record is derived from original local checkpoint metadata and training logs. Large checkpoints and the 600-episode dataset are managed as external artifacts and are not duplicated here.

## SmolVLA Fine-Tuning

| Field | Verified value |
|---|---:|
| Dataset | `demo/fruit_pick_dr_600ep`, 600 successful episodes |
| Final step / batch size | 20,000 / 128 |
| Seed | 1000 |
| Save interval | 2,000 steps |
| Periodic checkpoints | 10 (`002000` through `020000`) |
| Optimizer learning rate | 1e-4 |
| Scheduler warmup / decay | 1,000 / 30,000 steps |
| Training selection | Frozen vision encoder; trained expert and state projection |
| Final model size | 906,712,520 bytes |
| Final model SHA256 | `a0e735af8bc127d103ba89b7c9a1fa1e94d025a4170403712cd6bf689038d99d` |

The final `training_step.json` records `step=20000`, `num_processes=1`, and `batch_size=128`. The original output retained checkpoint state but no per-step loss log; therefore, this submission does not invent or infer a loss curve.

## Lift-Only Residual SAC

| Field | Verified value |
|---|---:|
| Final step / warmup | 100,000 / 10,000 |
| Batch size / replay capacity | 256 / 500,000 |
| Training seed range | 3000–4999 |
| Save interval | 10,000 steps |
| Periodic checkpoints | 10 plus `last.pt` |
| State / residual dimensions | 62 / 9 |
| Completed training episodes | 361 |
| Training-time successes | 169/361 (46.8%) |
| Final 100 training episodes | 45/100 |
| Final checkpoint size | 2,389,351 bytes |
| Final checkpoint SHA256 | `f05fce079fbc5a057f90c5b97d06d7075a29f4252d05ff210425e4b2a00dce86` |

Training episodes come from an online SAC process whose policy changes continuously; they are not a held-out evaluation set. Therefore, 169/361 and 45/100 are optimization-monitoring statistics only. The formal exploratory result remains the paired fixed-seed evaluation on seeds 2000–2099: eager baseline 34/100 and lift residual 43/100. Independent-seed validation has not been performed.

## Post-Migration Script Tests

Both training entry points completed a temporary one-step test on an AMD GPU. SmolVLA loaded the data and model, ran forward and backward passes, updated the optimizer, and saved a checkpoint. Residual SAC built the Genesis scene, loaded the frozen policy, executed one environment action, and saved a checkpoint. Temporary artifacts were deleted and are not counted as formal training results.
