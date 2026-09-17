# Experiment Log

Project: AMD Radeon / Genesis + SmolVLA kitchen pick task
Current best checkpoint: output/train/smolvla_kitchen_wrist/final

## Dataset

| Dataset | Episodes | Frames | FPS | Cameras | Generation success |
|---|---:|---:|---:|---|---:|
| local/franka-kitchen-wrist-live | 1 | 135 | 30 | up + wrist | 1/1 = 100% |
| local/franka-kitchen-wrist-100ep | 100 | 13,500 | 30 | up + wrist | 100/100 = 100% |
| local/franka-kitchen-wrist-targeted | targeted hard-case supplement | generated successfully | 30 | up + wrist | 40/40 = 100% |
| local/franka-kitchen-wrist-targeted-v2 | failure-coordinate supplement | 40 | 30 | up + wrist | 40/40 = 100% |
| local/franka-kitchen-wrist-mixed-replay-v4 | 2:1 broad replay + targeted | 120 | 16,200 | up + wrist | protocol valid |

## Training Runs

| Run | Init checkpoint | Dataset | Steps in run | Effective steps | Batch | Workers | Final loss | Time | Peak VRAM | Output |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| smolvla_kitchen_wrist_smoke | /workspace/models/smolvla_base | local/franka-kitchen-wrist-live | 20 | 20 | 1 | 0 | 0.0524 | 8s | 2.07 GB | output/train/smolvla_kitchen_wrist_smoke/final |
| smolvla_kitchen_wrist | /workspace/models/smolvla_base | local/franka-kitchen-wrist-100ep | 4,000 | 4,000 | 4 | 4 | 0.0113 | 599s | 2.26 GB | output/train/smolvla_kitchen_wrist/final |
| smolvla_kitchen_wrist_8000 | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | 4,000 | 8,000 | 4 | 4 | 0.0165 | 616s | 2.26 GB | output/train/smolvla_kitchen_wrist_8000/final |
| smolvla_kitchen_wrist_targeted_4000 | /workspace/models/smolvla_base or baseline local init | local/franka-kitchen-wrist-targeted | 4,000 | targeted control | 4 | 4 | recorded in remote train output | completed | about 2.3 GB | output/train/smolvla_kitchen_wrist_targeted_4000/final |
| smolvla_kitchen_mixed_replay_v4 | /workspace/models/smolvla_base | local/franka-kitchen-wrist-mixed-replay-v4 | 2,000 | 2,000 | 4 | 4 | 0.03282 | 308s | 2.32 GB | output/train/smolvla_kitchen_mixed_replay_v4/final |

## Evaluation Runs

| Eval run | Checkpoint | Dataset | Prompt | Episodes | Seed | Success | Video dir | Notes |
|---|---|---|---|---:|---:|---:|---|---|
| kitchen_eval | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the red cube. | 20 | 99 | 7/20 = 35% | output/eval/kitchen_eval/videos | Prompt mismatch vs training task |
| kitchen_eval_prompt_cube | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 20 | 99 | 11/20 = 55% | output/eval/kitchen_eval_prompt_cube/videos | Current best controlled result |
| kitchen_eval_prompt_cube_8000 | output/train/smolvla_kitchen_wrist_8000/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 20 | 99 | 8/20 = 40% | output/eval/kitchen_eval_prompt_cube_8000/videos | More steps did not help this closed-loop sample |
| kitchen_eval_prompt_cube_baseline_seed123 | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 20 | 123 | 1/20 = 5% | output/eval/kitchen_eval_prompt_cube_baseline_seed123/videos | Second seed; exposes high placement variance |
| kitchen_eval_prompt_cube_targeted_4000 | output/train/smolvla_kitchen_wrist_targeted_4000/final | local/franka-kitchen-wrist-targeted | Pick up the cube. | 20 | 99 | 1/20 = 5% | output/eval/kitchen_eval_prompt_cube_targeted_4000/videos | Targeted-only fine-tune collapsed; do not submit this checkpoint |
| baseline_4000_camera_both_seed99_50 | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 50 | 99 | 21/50 = 42% | copied to analysis/new_eval | Paired two-camera control |
| baseline_4000_camera_overhead_only_seed99_50 | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 50 | 99 | 5/50 = 10% | copied to analysis/new_eval | Neutral wrist-camera ablation |
| baseline_4000_camera_wrist_only_seed99_50 | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 50 | 99 | 1/50 = 2% | copied to analysis/new_eval | Neutral overhead-camera ablation |
| mixed_replay_nominal_seed99_50 | output/train/smolvla_kitchen_mixed_replay_v4/final | local/franka-kitchen-wrist-mixed-replay-v4 | Pick up the cube. | 50 | 99 | 10/50 = 20% | copied to analysis/new_eval | Candidate rejected |
| mixed_replay_nominal_seed123_20 | output/train/smolvla_kitchen_mixed_replay_v4/final | local/franka-kitchen-wrist-mixed-replay-v4 | Pick up the cube. | 20 | 123 | 5/20 = 25% | copied to analysis/new_eval | Second-seed subset |
| uncertainty_probe_seed99_10 | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 10 | 99 | 3/10 = 30% | copied to analysis/new_eval | Zero threshold crossings at 0.03 |
| robustness_intensity_sweep | output/train/smolvla_kitchen_wrist/final | local/franka-kitchen-wrist-100ep | Pick up the cube. | 19 x 20 | 99 | see sweep table | copied to analysis/robustness | 1 nominal + 18 multi-strength stress points |

## Analysis Artifacts

| Artifact | Purpose |
|---|---|
| analysis/raw_eval/*.json | Local copies of all evaluation summaries |
| analysis/eval_episode_records.csv | One row per evaluated episode with cube coordinates and success flag |
| analysis/eval_comparison.md | Experiment comparison and interpretation |
| analysis/failure_coordinate_scatter.svg | Scatter plot of success/failure by cube coordinate |
| analysis/extended_eval_comparison.md | Paired model, camera, replay, and robustness results |
| analysis/manifests/*.json | Fixed 50-episode and targeted placement manifests |
| analysis/new_eval/*.json | Camera, mixed replay, and uncertainty summaries |
| analysis/robustness/robustness_summary.md | Wilson intervals and retention table |
| analysis/robustness/robustness_envelope.svg | Sim-to-Real robustness envelope plot |
| analysis/robustness/robustness_sweep_runs.json | Raw 19-point intensity sweep summaries |
| analysis/robustness/robustness_sweep_summary.csv | Sweep rates, Wilson intervals, and retention |
| analysis/robustness/robustness_sweep_summary.md | Human-readable intensity table |
| analysis/robustness/robustness_intensity_envelope.svg | Multi-strength performance curves |
| analysis/mixed_replay_v4_summary.json | Exact dataset composition and protocol validation |
| analysis/mixed_replay_train_summary.json | Candidate training configuration and loss |

## Current Takeaways

- Keep the original 4,000-step baseline as the current submission checkpoint because it is the best controlled seed-99 result.
- The prompt comparison improved success from 35% to 55%, showing that language conditioning affects the action policy.
- The effective 8,000-step control dropped from 55% to 40%, showing that more training steps and loss tracking alone are not reliable optimization targets.
- The second seed dropped to 5%, so the project should disclose high evaluation variance and avoid overstating robustness.
- The targeted-only fine-tune also dropped to 5%, which suggests hard-case data should be mixed with replay from the original broad dataset rather than replacing it.
- The paired camera ablation measured 42% with both views, 10% overhead-only, and 2% wrist-only; the current policy relies on complementary views.
- The exact 2:1 mixed replay candidate used 80 broad plus 40 targeted episodes, but scored 20% on the paired 50-episode set and was rejected.
- The robustness matrix measured 50% nominal, 20% under camera dropout, 20% under local occlusion, 40% under two-step delay, and 40% under low friction.
- The uncertainty probe completed 3/10 with zero threshold crossings at `0.03`; it remains a diagnostic interface, not a demonstrated recovery gain.
- The multi-strength sweep kept all 19 points visible. Local occlusion fell from 20% to 5% to 0% at 10%, 25%, and 40% side-length stress; the other families show the expected sampling variance of 20-episode binomial estimates.

## Decision

The original 4,000-step checkpoint remains the submission model. The targeted
data generation, exact 2:1 mixed replay, camera ablation, robustness matrix,
and uncertainty probe are completed and recorded. The next model iteration
should train with camera-dropout augmentation and use a held-out paired
manifest; no such retrained checkpoint is claimed in this submission.

## Reproducibility Status (2026-08-05)

Completed in the repository:

- Added deterministic brightness and RGB sensor-noise perturbations to data
  generation and custom-scene evaluation.
- Added `both`, `overhead_only`, and `wrist_only` camera ablation modes.
- Added fixed evaluation manifests for paired 50-episode comparisons.
- Added failure-coordinate targeted placement manifests with deterministic
  jitter.
- Added a LeRobot mixed replay dataset builder with schema checks.
- Added a LeRobot dataset protocol validator.
- Added optional TensorBoard event logging to the training script.
- Added Wilson confidence intervals to generated evaluation summaries.
- Added `docs/sim_to_real.md` and `submission/TECHNICAL_REPORT.md`.

Completed on the ROCm cloud runtime:

1. Generated the fixed 50-episode manifests and ran all three camera conditions.
2. Generated and validated targeted data, built the exact 2:1 mixed dataset,
   and trained the conservative candidate.
3. Evaluated the candidate on the paired manifest and a second-seed subset.
4. Ran the baseline robustness matrix and copied JSON, CSV, Markdown, and SVG
   evidence into the repository.

The final local video has been uploaded publicly to YouTube:
https://youtu.be/N06ePLwqoqk

The original 4,000-step checkpoint remains the submission fallback until a
new candidate beats it on a paired evaluation set without hiding the
seed-123 negative control.
