# Q-Forge Demo Storyboard

Target: 1920×1080, 16:9, approximately 4 minutes 16 seconds, English narration,
and burned-in English subtitles.

| Time | Visual | Narration purpose |
|---|---|---|
| 00:00–00:15 | Q-Forge title, 42% → 68%, AMD Radeon | State the question and primary result |
| 00:15–00:47 | SmolVLA and learning-from-experience overview | Explain why demonstrations alone leave recovery states uncovered |
| 00:47–01:05 | Frozen prefix, Action Expert, and replay architecture | Introduce the Base policy and offline value-learning loop |
| 01:05–01:24 | Five-head critic and MC → TD/Cal-QL training | Explain action-sensitive value learning and critic gates |
| 01:24–01:42 | Perturbed rollout collection | Show 50 states × 6 rollouts, 300 episodes, and mixed outcomes |
| 01:42–01:59 | Selection, direct guidance, and residual distillation | Compare the three critic-use paths |
| 01:59–02:10 | Paired evaluation protocol | Establish shared states, seed, checkpoint, and replanning schedule |
| 02:10–02:30 | Task 7 and Task 3 paired rollout evidence | Show Base timeout versus guided completion under matched conditions |
| 02:30–02:50 | Task 7 result chart and paired transitions | Report 42% → 68%, 19 improvements, 6 regressions, and exact p-value |
| 02:50–03:09 | Task 3 replication | Report 76% → 88%, 6 improvements, and no regressions |
| 03:09–03:33 | AMD Radeon and attention-backend evidence | Show ROCm execution and phase-specific CK/SDPA/Triton choices |
| 03:33–03:48 | End-to-end policy inference optimization | Report the 10.1% replan-latency reduction |
| 03:48–04:01 | Judging-category evidence map | Connect results to capability, AMD adoption, innovation, value, and engineering |
| 04:01–end | Closing card with participant and Track 3 | Restate guidance, residual deployment, and AMD optimization |

## Paired episode evidence

The video includes matched Base and guided episodes from both reported tasks:

```text
Task 7:
  reset state 1, inference seed 2001
  Base: timeout at 240 steps
  Q-guidance: success

Task 3:
  reset state 14, matched reset and inference method comparison
  Base: timeout
  conservative Q-guidance: successful placement
```

The Task 7 recorder preserves CPU, GPU, and NumPy random-number state around its
adapter diagnostic so the recorded episode follows the sweep's paired random
stream.
