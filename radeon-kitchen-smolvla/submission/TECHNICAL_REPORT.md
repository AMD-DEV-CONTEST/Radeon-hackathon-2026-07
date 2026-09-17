# Radeon Kitchen Pick with SmolVLA

## 1. Application

The project studies a Physical AI manipulation task: a Franka Panda robot must
pick up a cube placed at randomized positions in a rustic-kitchen Genesis
simulation. The policy receives two RGB views, robot joint state, and the
language instruction `Pick up the cube.` It predicts joint-position actions in
a closed loop.

The intended application is a compact **failure-aware benchmark for cluttered
kitchen manipulation**. It diagnoses where a vision-language-action policy
breaks before a future real-robot deployment, then supplies targeted hard cases
without discarding broad replay data.

## 2. System Architecture

```text
Genesis scripted expert
        |
        v
LeRobot episode dataset
        |
        v
SmolVLA fine-tuning on AMD ROCm
        |
        v
Genesis closed-loop evaluation
        |
        +--> videos, success summaries, failure coordinates
```

The data generator records synchronized `observation.state`, `action`, two
image streams, task text, and cube placement metadata. The evaluator resets a
fixed scene, renders both cameras, predicts an action chunk, executes one or
more actions, and repeats until the episode ends.

## 3. Data

The main dataset contains 100 expert episodes, 13,500 frames at 30 FPS, and
two RGB cameras: an overhead camera and an eye-in-hand wrist camera. The
Franka state and action are both 9-dimensional joint-position vectors.

The repository includes:

- `scripts/02_gen_data_custom_scene.py` for deterministic expert generation.
- `scripts/06_make_mixed_dataset.py` for broad replay plus targeted episodes.
- `scripts/08_validate_dataset.py` for protocol checks.
- `analysis/` for copied evaluation summaries and failure plots.

Large datasets and model weights are intentionally not committed to Git.

## 4. Model and Training

The policy is SmolVLA initialized from a local SmolVLA checkpoint. The
successful baseline used 4,000 training steps, batch size 4, and frozen visual
encoder settings from the workshop recipe. A continued effective 8,000-step
control was also evaluated.

The training script records per-step JSON metrics and can write TensorBoard
events under `output/train/<run-name>/tensorboard`. Closed-loop success is
treated as the primary task metric because imitation loss alone does not
capture compounding control error or contact dynamics.

## 5. AMD Radeon and ROCm Usage

The project was developed on an AMD Radeon cloud GPU with a ROCm-enabled
PyTorch environment. GPU use covers SmolVLA fine-tuning and policy inference;
Genesis uses the available GPU rendering/physics backend when the cloud image
supports it. Offline Hugging Face and Transformers modes are enabled so local
model files are reused without network access.

The repository documents the local SmolVLM2 backbone path because evaluation
must work in the offline cloud environment. FFmpeg and TorchCodec are used for
video data and evidence clips.

## 6. Results

| Experiment | Episodes | Seed | Success |
|---|---:|---:|---:|
| Prompt mismatch: `Pick up the red cube.` | 20 | 99 | 7/20 = 35% |
| Baseline: `Pick up the cube.` | 20 | 99 | 11/20 = 55% |
| Effective 8,000-step control | 20 | 99 | 8/20 = 40% |
| Baseline second seed | 20 | 123 | 1/20 = 5% |
| Targeted-only fine-tune | 20 | 99 | 1/20 = 5% |
| Paired baseline, both cameras | 50 | 99 | 21/50 = 42% |
| Paired baseline, overhead only | 50 | 99 | 5/50 = 10% |
| Paired baseline, wrist only | 50 | 99 | 1/50 = 2% |
| Mixed replay candidate, paired manifest | 50 | 99 | 10/50 = 20% |
| Mixed replay candidate, second-seed subset | 20 | 123 | 5/20 = 25% |

The mixed replay dataset used exactly 80 broad episodes plus 40 targeted
failure-coordinate episodes, a 2:1 ratio and 16,200 frames. It was trained
for 2,000 steps at learning rate `5e-5`. The candidate was rejected because
its paired closed-loop success was below the original baseline. This is an
important negative control: lower training loss does not automatically imply
better manipulation.

The larger paired camera comparison shows that the current policy depends on
complementary views. Keeping both cameras achieved 42%, while neutralizing the
wrist or overhead input reduced success to 10% and 2% respectively.

The multi-strength sweep uses one nominal control plus three levels for each
stress family, with 20 episodes per point and the same placement manifest:

| Stress family | Levels | Success rates |
|---|---|---|
| Brightness | +/-5%, +/-15%, +/-25% | 40%, 60%, 45% |
| RGB noise | std 2, 4, 8 | 10%, 45%, 15% |
| Local occlusion | 10%, 25%, 40% image side length | 20%, 5%, 0% |
| Action delay | 1, 2, 4 steps | 55%, 55%, 45% |
| Friction low | 1.4, 1.2, 1.0 | 45%, 50%, 65% |
| Friction high | 1.6, 1.8, 2.0 | 60%, 50%, 30% |

The envelope plot includes 95% Wilson interval bars. The results are not
smoothed: the sharp local-occlusion decline is the clearest causal signal,
while the other families show finite-sample variance rather than a guaranteed
monotonic law.

The baseline remains the submission checkpoint because it has the best
controlled seed-99 result. The seed-123 result is disclosed as evidence that
the current policy is not yet robust.

## 7. Technical Contributions

- Reproducible Genesis expert data generation in a custom kitchen scene.
- LeRobot-compatible synchronized state, action, image, and task fields.
- Offline local-backbone loading for SmolVLA on ROCm.
- Closed-loop evaluation with fixed scene, anchor, camera layout, and seed.
- Prompt, training-step, seed, and targeted-data controls.
- Failure-coordinate analysis and a mixed replay data pipeline.
- Camera ablation, random camera dropout, localized occlusion, action-delay and
  friction stress tests, plus fixed episode manifests for paired comparisons.
- A visual-consistency uncertainty probe that can slow down and replan when
  perturbed action predictions disagree.
- A robustness-matrix runner that emits a success/retention table and SVG
  envelope without requiring plotting packages.

## 8. Sim-to-Real Evaluation Protocol

The project separates nominal performance from transfer stress tests. Every
condition uses the same placement manifest, and the nominal result is the
denominator for robustness retention:

```text
retention = stressed success rate / nominal success rate
```

The stressors are deliberately interpretable: brightness and RGB noise probe
the visual sensor gap; camera dropout and local occlusion probe missing visual
evidence; action delay probes timing; friction sweeps probe contact dynamics.
The results are stored under `output/eval/robustness_matrix/` and summarized by
`scripts/10_summarize_robustness.py` with Wilson intervals.

The completed 20-episode paired matrix measured: nominal 50%; brightness
`[0.85, 1.15]` 55%; RGB noise std 4, 45%; camera dropout 20%; local occlusion
20%; two-step action delay 40%; low friction 40%; and high friction 55%.
Relative to nominal, the most important measured degradations were camera
dropout and occlusion at 40% retention, followed by delay and low friction at
80% retention. The two 55% rows are not interpreted as improvements because
the matrix is a small binomial sample and the stressed placements can be
slightly easier by chance.

## 9. Limitations and Next Experiments

Completed evidence now includes the paired 50-episode camera ablation, the
exact 2:1 mixed replay candidate, and the robustness matrix. The highest-value
remaining experiment is to retrain with camera-dropout augmentation and select
the checkpoint on a held-out paired manifest. The uncertainty probe also needs
threshold calibration on a held-out failure set: the current threshold `0.03`
triggered zero warnings in 10 episodes, so it is not claimed as a benefit.

Before any hardware claim, the synthetic stressor ranges must be calibrated
from real camera and controller measurements.

These experiments are designed to improve evidence quality and technical depth
without hiding the negative controls.

## 9. Team

Chen Weiliang: environment setup, synthetic data generation, ROCm
configuration, SmolVLA training, closed-loop evaluation, failure analysis,
documentation, and demo preparation.
