# Extended Closed-Loop Evidence

All results below are closed-loop Genesis evaluations of the same kitchen task.
The paired 50-episode manifest is the stronger comparison because every camera
condition reuses the same cube placements.

## Model and Prompt Controls

| Experiment | Episodes | Seed | Success | Decision |
|---|---:|---:|---:|---|
| 4,000-step baseline, aligned prompt | 20 | 99 | 11/20 = 55% | Keep as submission model |
| 4,000-step baseline, second seed | 20 | 123 | 1/20 = 5% | Disclose placement variance |
| Effective 8,000-step baseline | 20 | 99 | 8/20 = 40% | More steps did not help |
| Prompt mismatch: `Pick up the red cube.` | 20 | 99 | 7/20 = 35% | Prompt wording matters |
| Targeted-only fine-tune | 20 | 99 | 1/20 = 5% | Negative control |
| Baseline, paired 50-episode manifest | 50 | 99 | 21/50 = 42% | Larger evidence set |
| Mixed replay candidate, paired manifest | 50 | 99 | 10/50 = 20% | Do not replace baseline |
| Mixed replay candidate, second seed | 20 | 123 | 5/20 = 25% | Still not a submission model |

The mixed dataset was built at exactly 2:1 broad replay to targeted data:
80 original episodes plus 40 failure-coordinate episodes, 120 episodes and
16,200 frames total. The candidate was trained for 2,000 steps at `5e-5`; its
lower training loss was not enough to justify promotion because its paired
closed-loop result fell below the baseline.

## Camera Ablation

| Camera condition | Episodes | Success | Retention vs paired two-camera baseline |
|---|---:|---:|---:|
| Both cameras | 50 | 21/50 = 42% | 100% |
| Overhead only | 50 | 5/50 = 10% | 24% |
| Wrist only | 50 | 1/50 = 2% | 5% |

This is evidence that the current policy uses complementary views. It is not
evidence that either camera can be permanently removed without retraining.

## Sim-to-Real Robustness Matrix

| Condition | Episodes | Success | Retention |
|---|---:|---:|---:|
| Nominal | 20 | 10/20 = 50% | 100% |
| Brightness `[0.85, 1.15]` | 20 | 11/20 = 55% | 110% |
| RGB noise, std 4 | 20 | 9/20 = 45% | 90% |
| Camera dropout, 50% observations | 20 | 4/20 = 20% | 40% |
| Local occlusion, 25% area | 20 | 4/20 = 20% | 40% |
| Action delay, 2 steps | 20 | 8/20 = 40% | 80% |
| Low friction, 1.2 | 20 | 8/20 = 40% | 80% |
| High friction, 1.8 | 20 | 11/20 = 55% | 110% |

The brightness and high-friction rows are not interpreted as improvements:
with 20 episodes, binomial variance can make a stressed condition exceed the
nominal count. The useful signal is sensitivity: camera evidence loss is the
largest measured degradation, followed by timing and low-friction stress.

## Multi-strength sweep

The expanded sweep uses 20 episodes at every point and the same placement
manifest. Severity is normalized within each family; the listed values are the
actual simulator parameters.

| Family | Levels | Success rates |
|---|---|---|
| Brightness | +/-5%, +/-15%, +/-25% | 40%, 60%, 45% |
| RGB noise | std 2, 4, 8 | 10%, 45%, 15% |
| Local occlusion | 10%, 25%, 40% image side length | 20%, 5%, 0% |
| Action delay | 1, 2, 4 steps | 55%, 55%, 45% |
| Friction low | 1.4, 1.2, 1.0 | 45%, 50%, 65% |
| Friction high | 1.6, 1.8, 2.0 | 60%, 50%, 30% |

The red occlusion curve is the clearest monotonic signal. The other curves
remain unsmoothed and include 95% Wilson bars in the SVG because episode-level
success is noisy at this sample size.

## Uncertainty Probe

The three-pass visual-consistency probe completed 10 episodes with 3/10
success. At threshold `0.03`, it triggered zero uncertain observations and
zero replans; mean action disagreement was `0.00313`. This validates the
diagnostic path without claiming a benefit. A future calibration sweep should
select the threshold on a held-out failure set before enabling recovery logic.
