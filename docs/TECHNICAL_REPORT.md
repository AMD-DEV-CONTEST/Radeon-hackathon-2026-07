# Franka Multimodal Fruit-Picking System on AMD Radeon GPU and ROCm

English | [Chinese version](TECHNICAL_REPORT_ZH.md)

## Technical Report

> Project status: competition submission draft based on experiments completed by August 5, 2026.  
> Important: this report claims only experiments that were completed and whose results were saved. Unexecuted work is listed in Section 12 as future work and is not presented as a current result.

## Abstract

This project targets unstructured fruit-sorting tasks with a closed-loop vision-language-action system executed by a Franka Panda robot in the Genesis physics simulator. A scripted expert generated 600 successful episodes, with 200 episodes each for banana, lemon, and plum. Appearance, object color, table, camera, object pose, friction, and mass were randomized during data generation. The open-source SmolVLA model was fine-tuned on this dataset for 20,000 steps with a batch size of 128 and evaluated in 100 closed-loop episodes per fruit.

The main engineering contribution is SmolVLA inference optimization for AMD Radeon GPUs and ROCm. The HIP Graph backend reduced mean full `sample_actions()` latency from 153.81 ms to 102.76 ms, a 1.497x speedup, while producing zero numerical error relative to eager execution on both fixed and changing inputs. Across 300 closed-loop episodes, HIP Graph reduced weighted steady-state policy latency from 8.536 ms to 6.838 ms, a 1.248x speedup. Task successes changed from 224/300 to 227/300; an exact McNemar test gave `p=0.549`, with no significant success-rate degradation observed.

The project also implements an experimental Targeted Compile backend. It reduced full-inference latency to 63.86 ms, a 2.409x speedup. In a separate 300-episode evaluation, steady-state latency fell from 8.521 ms to 6.295 ms, a 1.354x speedup, while successes changed from 218/300 to 222/300. Because strict offline validation detected numerical differences, Targeted Compile is treated as a high-performance experimental backend rather than the default deployment backend.

To address the lower plum success rate, the project additionally combines a frozen SmolVLA policy with privileged-state residual SAC. The current lift-only, ungated residual improved success from 34% to 43% on seeds 2000–2099. This result has not yet been validated on independent seeds and is therefore reported as exploratory evidence rather than a final generalization claim.

![Project results dashboard](figures/fig10_results_dashboard.png)

## 1. Target Application Definition

### 1.1 Application scenario

The target application is flexible sorting of fruit, food, and other fragile irregular objects. From visual observations and a language instruction, the robot must pick the specified fruit from a table and place it in a target container.

Three YCB objects with different geometric and physical properties are used:

- `011_banana`: elongated, with substantial pose variation;
- `014_lemon`: relatively regular geometry but variable contact locations;
- `018_plum`: smaller and more prone to grasping, lifting, and transport failures.

### 1.2 Inputs, outputs, and closed loop

The inputs are RGB camera images, a language instruction, and robot state. SmolVLA produces action chunks that command the Franka joints and gripper. Genesis simulates contact, gravity, collision, camera rendering, and object motion, then returns the next observation to close the perception-decision-control loop.

```text
RGB images + language instruction + robot state
                       ↓
                    SmolVLA
                       ↓
                  action chunk
                       ↓
           Franka control + Genesis
                       ↓
                next observation
```

### 1.3 Success definition and evaluation

Final episode success is the primary metric. The evaluation also records termination step, divergence state, first-call and steady-state inference latency, inference-call count, and episode wall-clock time. Paired outcome agreement, the exact McNemar test, and Wilson 95% confidence intervals are used to determine whether switching inference backends changes task capability.

## 2. Overall Architecture and Solution Design

The project implements a complete path from simulated data generation to learned-policy deployment:

```text
Genesis physics scene
        ↓
scripted expert + domain randomization
        ↓
600 successful episodes in LeRobot format
        ↓
SmolVLA fine-tuning (20,000 steps)
        ↓
Eager / HIP Graph / Targeted Compile
        ↓
three-fruit closed-loop Franka evaluation
        ↓
frozen SmolVLA + residual SAC for the difficult plum task
```

![Complete simulation-to-policy and ROCm pipeline](figures/fig5_full_pipeline.png)

![AMD ROCm inference and robot closed-loop architecture](figures/fig1_system_architecture.png)

The code is organized by function:

- `franka_fruit_pick/`: scene construction, randomization, expert demonstrations, recording, training, and closed-loop evaluation;
- `franka_fruit_pick/residual_rl/`: residual SAC on top of frozen SmolVLA;
- `optimization/amd/`: standalone AMD/ROCm optimization experiments;
- `optimization/runtime/`: production `sample_actions()` backends, numerical validation, and closed-loop tools;
- `docker/`: ROCm 7.2.1 development and runtime environment.

## 3. Simulation, Expert Policy, and Domain Randomization

Genesis is used to construct the Franka Panda, table, target bowl, three fruit objects, and camera scene. A scripted expert uses inverse kinematics and predefined manipulation stages to produce grasp, lift, transport, and release actions. Only successful episodes are written to the training dataset.

| Category | Setting |
|---|---|
| Appearance | Scene appearance and object-color randomization |
| Table | `--dr-table-jitter 0.15` |
| Camera field of view | `--dr-fov-jitter 2.0` |
| Camera position | `--dr-cam-pos 0.01` |
| Camera look-at point | `--dr-cam-lookat 0.02` |
| Object state | Randomized initial position and orientation |
| Friction | Relative range `0.6–1.4` |
| Mass | Relative range `0.8–1.2` |
| Scene rebuild | Rebuild the randomized appearance scene every five episodes |

Randomization covers both observation and physical variation. Its purpose is to reduce dependence on fixed textures, a fixed camera, and a single set of contact parameters.

![Dataset composition and domain randomization](figures/fig6_dataset_domain_randomization.png)

## 4. Dataset

The training dataset is expected at `artifacts/datasets/fruit_pick_dr_600ep`, with repo ID `demo/fruit_pick_dr_600ep`.

| Object | Successful episodes | Share |
|---|---:|---:|
| Banana | 200 | 33.3% |
| Lemon | 200 | 33.3% |
| Plum | 200 | 33.3% |
| Total | 600 | 100% |

The LeRobot-format dataset stores robot observations, camera frames, actions, episode metadata, and task identifiers. Because the complete dataset is large, the competition release should distribute it through external artifact storage or Git LFS with its version, size, SHA256, license, and download procedure. Duplicate copies should not be committed.

Data and asset provenance is bounded as follows:

- the Franka model comes from the Genesis asset chain;
- fruit and bowl models come from the YCB/ManiSkill asset chain;
- training is based on open-source SmolVLA and LeRobot;
- the final release should include `THIRD_PARTY_NOTICES.md` with license and citation requirements for each dependency.

## 5. SmolVLA Fine-Tuning

The entry point is `scripts/train_smolvla_fruit_pick.sh`, which calls `franka_fruit_pick/train_policy.py` and the LeRobot 0.6.0 trainer. The final checkpoint is expected at:

```text
artifacts/models/smolvla_fruit_pick_dr_600ep
```

| Configuration | Value |
|---|---:|
| Model | SmolVLA |
| Training data | `fruit_pick_dr_600ep` |
| Training steps | 20,000 |
| Batch size | 128 |
| Save interval | 2,000 steps |
| Training interface | LeRobot |
| Device argument | `--device cuda` |

Original checkpoint metadata confirms step 20,000, single-process training, batch size 128, seed 1000, optimizer learning rate `1e-4`, 1,000 warmup steps, and 30,000 decay steps. The vision encoder was frozen while the expert and state projection were trained. Ten periodic checkpoints from `002000` through `020000` were retained. The final `model.safetensors` is 906,712,520 bytes with SHA256 `a0e735af8bc127d103ba89b7c9a1fa1e94d025a4170403712cd6bf689038d99d`.

The original training directory did not retain per-step loss logs, so this report does not invent a loss curve that cannot be reconstructed from evidence. Model quality is evaluated by closed-loop task success rather than using training loss as a substitute for task performance.

ROCm PyTorch uses the standard PyTorch `cuda` device interface for HIP GPUs. Therefore, `--device cuda` selects the AMD GPU backend in this environment; it does not imply NVIDIA CUDA. A release environment should also record `torch.version.hip`, the GPU model, and the ROCm version.

## 6. Closed-Loop SmolVLA Capability and Failure Analysis

This section answers what the fine-tuned model learned and where it fails. Eager inference is used as the behavioral baseline. GPU performance, correctness, and behavior preservation are addressed in Section 7.

### 6.1 Evaluation setup

The final 20,000-step checkpoint directly controls Franka in Genesis. Each fruit is evaluated for 100 episodes using seeds 2000–2099. Success requires the object to be grasped, transported, and placed in the bowl. Eager execution leaves the model path unchanged and serves as the behavioral reference for accelerated backends.

### 6.2 Eager model baseline

| Fruit | Successes | Success rate | Assessment |
|---|---:|---:|---|
| Banana | 99/100 | 99% | Highly stable |
| Lemon | 94/100 | 94% | Highly stable |
| Plum | 31/100 | 31% | Current difficult task |
| Overall | 224/300 | 74.7% | Large variation across objects |

The same checkpoint learned the full approach, grasp, lift, transport, and placement sequence for all three fruits, but robustness differs substantially. Banana and lemon offer larger tolerance margins. The smaller plum has limited contact area and is more sensitive to end-effector position, gripper timing, and transport stability.

### 6.3 Video evidence

The [English-narrated success and failure video](video/smolvla_success_failure_demo.mp4) shows successful closed-loop runs for all three fruits, saved lemon and plum failures, success rates, and failure analysis. Individual successful episodes are also available:

- [Banana pick-and-place success](video/success_examples/banana_success.mp4)
- [Lemon pick-and-place success](video/success_examples/lemon_success.mp4)
- [Plum pick-and-place success](video/success_examples/plum_success.mp4)

All successful videos come from the fine-tuned SmolVLA closed-loop evaluation, not scripted-expert playback. All ten saved banana visualization episodes succeeded, so no old-model banana failure was substituted. The formal 99% result still records one unsaved failure among 100 episodes.

The narrated video reports deployment results of 99%, 94%, and 34%, whereas the pure eager baseline here is 99%, 94%, and 31%. These paired runs use the same seed range. Backend attribution and statistical interpretation are given in Section 7.5; the three-success difference must not be interpreted as improved model capability.

### 6.4 Main failure causes

Saved lemon and plum failures show that a high aggregate success rate does not exclude approach, grasp, or placement failures. Plum risks can be grouped by stage:

1. **Approach error:** a small target makes position error more likely to cause a miss or collision.
2. **Unstable grasp:** limited contact area can produce a missed or weak grasp.
3. **Lift failure:** the object slips before leaving the table or fails to reach a valid lift height.
4. **Transport drop:** a grasped object falls while moving toward the bowl.
5. **Placement and success-boundary error:** the object approaches the bowl but does not settle inside the success region.

The conclusion is therefore not merely that three successful videos exist. SmolVLA demonstrates closed-loop capability on all three fruits; banana and lemon are stable, while plum grasp and transport robustness remain the main model limitation. This motivates the residual SAC study in Section 8.

## 7. AMD Radeon GPU and ROCm

### 7.1 Environment and optimization scope

The Docker environment uses ROCm 7.2.1, Python 3.12, ROCm PyTorch 2.9.1, Triton 3.5.1, LeRobot 0.6.0, and Genesis, and was validated on an AMD Radeon AI PRO R9700. A clean image build and container smoke test are still required before final release; this delivery check does not change the experimental conclusions.

The project evaluated mixed precision, SDPA/Flash Attention, `torch.compile`, TunableOp/hipBLASLt, HIP Graph, Triton, BLAS routing, and image-memory layout. To avoid presenting microbenchmarks as end-to-end gains, formal results focus on the real `sample_actions()` path and closed-loop robot execution.

### 7.2 HIP Graph backend

HIP Graph captures only the relatively shape-stable diffusion denoiser inside `sample_actions()`. Image, language, and state prefixes remain eager. Dynamic masks, KV cache, and diffusion noise are copied before every replay, and the graph is recaptured when static shapes change.

Strict validation compares eager and HIP Graph with identical inputs, noise, and weights on both fixed and changing image/state inputs. After correcting the timestep-frequency dtype issue, maximum absolute error and RMSE are both zero for both input classes.

### 7.3 Targeted Compile backend

Targeted Compile compiles only `model.denoise_step()` inside `model.sample_actions()`:

```text
backend = inductor
mode = max-autotune-no-cudagraphs
fullgraph = false
matmul_precision = high
```

The saved full-inference benchmark and strict validation use `matmul_precision=high`. This backend achieves the highest steady-state performance but differs numerically from eager: fixed-input maximum absolute error is 0.067798 with RMSE 0.002732; changing-input maximum absolute error is 0.023839 with RMSE 0.001462. It is therefore clearly labeled experimental and is not equated with zero-error HIP Graph.

### 7.4 Full `sample_actions()` benchmark

| Backend | Mean | P50 | P95 | Samples/s | Speedup | First call | Peak memory | Correctness |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Eager | 153.81 ms | 151.94 ms | 154.93 ms | 6.50 | 1.000x | 1224.62 ms | 1022 MiB | Baseline |
| HIP Graph | 102.76 ms | 102.70 ms | 103.47 ms | 9.73 | 1.497x | 1558.50 ms | 1134 MiB | Zero error on fixed/changing inputs |
| Targeted Compile | 63.86 ms | 63.30 ms | 66.14 ms | 15.66 | 2.409x | 23357.21 ms | 1203 MiB | Numerical mismatch |

Longer first-compilation times were observed in a separate cold-cache run, so the first-call column should not be interpreted as a universal cold-start metric across machines. Deployment must distinguish cold compilation, disk-cache reuse, and steady-state inference.

![Inference performance and correctness trade-off](figures/fig4_backend_performance_correctness.png)

### 7.5 HIP Graph closed-loop A/B and behavior preservation

HIP Graph A/B uses seeds 2000–2099, matching Section 6, with 100 episodes per fruit. Its purpose is to determine whether acceleration preserves task behavior and success, not to reassess what SmolVLA learned.

| Fruit | Eager steady state | HIP Graph steady state | Speedup | Eager success | Graph success |
|---|---:|---:|---:|---:|---:|
| Banana | 8.623 ms | 6.778 ms | 1.272x | 99/100 | 99/100 |
| Lemon | 8.430 ms | 6.892 ms | 1.223x | 94/100 | 94/100 |
| Plum | 8.546 ms | 6.842 ms | 1.249x | 31/100 | 34/100 |
| Weighted overall | 8.536 ms | 6.838 ms | 1.248x | 224/300 | 227/300 |

![Eager and HIP Graph success with Wilson 95% confidence intervals](figures/fig3_success_rate_wilson_ci.png)

Success outcomes agree in 289/300 episodes and exact termination steps agree in 178/300. Eager failed while HIP Graph succeeded seven times; eager succeeded while HIP Graph failed four times. The exact McNemar result is `p=0.549`. The supported conclusion is that no significant task-success degradation was observed after switching to HIP Graph—not that HIP Graph improves SmolVLA success.

Closed-loop wall time per policy step decreased from 46.93 ms to 45.16 ms, about 1.039x. Camera rendering, preprocessing, action queues, and physics simulation dilute the model-side gain.

### 7.6 Targeted Compile 300-episode closed loop

Targeted Compile uses seeds 1000–1099, different from the HIP Graph seeds. It can only be compared with its paired eager baseline; raw success totals cannot rank it against HIP Graph.

| Fruit | Eager steady state | Compile steady state | Speedup | Eager success | Compile success |
|---|---:|---:|---:|---:|---:|
| Banana | 8.658 ms | 6.313 ms | 1.371x | 99/100 | 99/100 |
| Lemon | 8.654 ms | 6.397 ms | 1.353x | 95/100 | 94/100 |
| Plum | 8.373 ms | 6.227 ms | 1.345x | 24/100 | 29/100 |
| Weighted overall | 8.521 ms | 6.295 ms | 1.354x | 218/300 | 222/300 |

Outcomes agree in 286/300 episodes and exact termination steps agree in 159/300. Eager failed while compile succeeded nine times; eager succeeded while compile failed five times. The exact McNemar result is `p=0.424`. No significant success-rate degradation was observed, but this does not remove the strict offline numerical mismatch, so Targeted Compile remains experimental.

Closed-loop wall time per policy step decreased from 46.49 ms to 44.35 ms, about 1.048x.

![HIP Graph and Targeted Compile under three latency scopes](figures/fig2_three_level_latency.png)

### 7.7 Deployment choice

| Scenario | Recommended backend | Reason |
|---|---|---|
| Default demo and stable reproduction | HIP Graph | Passed zero-error validation with stable closed-loop behavior |
| High-performance research | Targeted Compile | Faster, but has numerical differences and compilation cost |
| Debugging and reference | Eager | Behavioral baseline and easiest path for diagnosis |

## 8. Residual Reinforcement Learning

### 8.1 Motivation and method

Plum baseline success is only 31%–34%. To test whether the difficult stage could be improved without retraining SmolVLA, the project freezes SmolVLA and trains privileged-state residual SAC to output a bounded nine-dimensional joint-target correction.

| Configuration | Value |
|---|---:|
| Task mode | lift |
| Training steps | 100,000 |
| Warmup | 10,000 |
| Batch size | 256 |
| Replay buffer | 500,000 |
| Gamma | 0.99 |
| Tau | 0.005 |
| Learning rate | 0.0003 |
| Arm residual scale | 0.015 |
| Finger residual scale | 0.003 |
| Training seeds | 3000–4999 |

Best checkpoint:

```text
artifacts/models/plum_residual_sac_lift/last.pt
```

Checkpoint metadata confirms step 100,000, a 62-dimensional privileged state, and a nine-dimensional residual action. Training saved ten periodic checkpoints at 10,000-step intervals plus `last.pt`. The log contains 361 completed episodes with 169 successes (46.8%); the final 100 training episodes contain 45 successes. Because these episodes were collected while the policy was being updated, they are monitoring data rather than held-out performance. The formal exploratory effect remains the paired 34/100 to 43/100 result on seeds 2000–2099.

![Frozen SmolVLA with privileged-state residual SAC](figures/fig7_residual_sac_architecture.png)

### 8.2 Completed exploratory results

| Variant | Baseline | Residual | Interpretation |
|---|---:|---:|---|
| Lift-only, ungated, seeds 2000–2099 | 34/100 | 43/100 | Best current result; not independently validated |
| Lift checkpoint, hard-off after lift | 32/100 | 30/100 | Hard gating was ineffective |
| Full residual | 31/100 | 33/100 | Frequent transport drops; below the best variant |

For ungated lift residual, both policies succeeded in 26 episodes, baseline alone in eight, residual alone in 17, and both failed in 49. This suggests that residual control can improve some trajectories but does not yet prove a stable gain on an independent environment distribution.

![Paired ablation of three residual SAC variants](figures/fig8_residual_rl_ablation.png)

Failure-stage counts for baseline were 28 approach failures, three grasp failures, two lift failures, 33 transport drops, and 34 successes. Residual SAC produced two, 16, five, 34, and 43 respectively. Residual control sharply reduced approach failures but increased grasp failures and barely changed transport drops. This explains why expanding residual scope or applying a hard gate did not reliably solve complete placement.

![Plum failure-stage distribution](figures/fig9_plum_failure_distribution.png)

### 8.3 Result boundaries

- The residual policy depends on privileged simulator state and is not a directly deployable vision-only policy.
- Independent validation on seeds 5000–5099 has not been run.
- Genesis AMD GPU physics trajectories are not bitwise deterministic across processes.
- The 43% result is not presented as a formal headline claim and does not replace the three-fruit SmolVLA baseline.
- Negative full-residual and hard-gating results are retained as evidence of stage coupling and transport instability.

## 9. Innovations and Key Technical Contributions

1. **Complete Physical AI pipeline:** Genesis simulation, expert data, LeRobot dataset, SmolVLA fine-tuning, and closed-loop control are integrated end to end.
2. **Multi-layer domain randomization:** visual appearance, camera, initial state, and contact physics are varied rather than applying image augmentation alone.
3. **Module-level HIP Graph for a VLA diffusion denoiser:** dynamic prefixes stay eager while the shape-stable denoiser is captured, with dynamic replay inputs safely refreshed.
4. **Joint performance and task-capability validation:** offline numerical error, full-model latency, closed-loop inference, end-to-end wall time, and 300-episode success are reported together.
5. **Explicit boundary for an experimental high-performance backend:** Targeted Compile reaches 2.409x full-inference speedup but is not presented as deployment-stable because of numerical mismatch.
6. **Residual RL on a frozen VLA:** action correction is investigated without modifying the base model, and negative ablations are preserved to inform future design.

## 10. Application Value, Strengths, and Limitations

### 10.1 Application value

The approach can extend to food sorting, post-harvest agricultural handling, flexible warehousing, and small-batch manufacturing. Its value is not a single demonstration, but a low-barrier path to repeatable training, quantitative evaluation, and incremental optimization using open-source simulation, open-source models, and AMD GPUs.

### 10.2 Strengths

- Complete data, training, inference, closed-loop evaluation, and optimization path;
- 100-episode evaluation per fruit rather than success videos alone;
- AMD/ROCm is used in the real model and control path;
- stable and experimental backends are reported separately;
- residual RL investigates the difficult plum task rather than hiding its lower success rate.

### 10.3 Known limitations

- Plum baseline success is substantially lower than banana and lemon.
- All results are simulated; no real Franka validation has been completed.
- A 1.25–1.35x steady-state policy speedup yields only about 1.04–1.05x end-to-end improvement.
- Targeted Compile has numerical differences and substantial cold-compilation cost.
- Residual SAC depends on privileged state and lacks independent-seed validation.
- Genesis physics trajectories are not bitwise deterministic across processes.

## 11. Final Deliverables

| Deliverable | Form/location |
|---|---|
| Source code | This dedicated repository |
| Genesis simulation and data generation | Core source under `franka_fruit_pick/` |
| SmolVLA training | `franka_fruit_pick/train_policy.py`, configs, and external checkpoint |
| ROCm optimization | `optimization/runtime/`, `scripts/*rocm*`, and closed-loop A/B entry points |
| Residual reinforcement learning | `franka_fruit_pick/residual_rl/`, config, and external checkpoint |
| Historical training records | `results/training/README.md`, verified from checkpoint metadata and logs |
| Formal experimental data | JSON, CSV, Markdown summaries, and report figures |
| Docker environment | `docker/Dockerfile` |
| Reproducibility instructions | `docs/REPRODUCIBILITY.md` and root README |
| Technical report | This document and planned PDF export |
| Main demo video | `docs/video/smolvla_success_failure_demo.mp4`, 3:20 with English narration |
| Individual success videos | Banana, lemon, and plum episodes under `docs/video/success_examples/` |
| Animated preview | `docs/video/preview.gif` |

Large datasets and weights should be published as versioned external artifacts with URLs and SHA256 values in the manifest. Compact success videos are included so evaluators can inspect behavior immediately.

The three successful episodes are closed-loop outputs of the fine-tuned SmolVLA policy, not scripted-expert data-generation footage:

- [Banana pick and place](video/success_examples/banana_success.mp4)
- [Lemon pick and place](video/success_examples/lemon_success.mp4)
- [Plum pick and place](video/success_examples/plum_success.mp4)

The synchronized three-view videos include a world camera, wrist camera, and third-person view across approach, grasp, lift, transport, and placement. Videos provide qualitative evidence, while the 100-episode-per-fruit evaluation supports capability claims.

The narrated video also includes saved lemon and plum failures and explains deployment success rates of 99%, 94%, and 34%. All ten saved banana visualization episodes succeeded, so an old-model failure was not substituted. The failure analysis covers small-object alignment, weak contact, lift failure, and transport drops.

## 12. Future Experimental Plan (Not Executed)

The following items are not current results:

1. Independently validate ungated lift residual on seeds 5000–5099.
2. Investigate Genesis cross-process nondeterminism under identical seeds.
3. Test soft gating, separate arm/gripper residuals, and stage-specific dual actors.
4. Distill privileged residuals or replace them with a visual residual policy.
5. Run eager, HIP Graph, and Targeted Compile A/B/C on identical seeds.
6. Add end-to-end breakdowns, P99, peak memory, and cold/warm-cache startup tests.
7. Isolate BF16 accumulation, Inductor fusion, and multi-step denoising error in Targeted Compile.
8. Analyze plum failures by miss, slip, collision, transport drop, placement failure, and success-boundary error.
9. Validate control frequency, safe stop, fallback behavior, and sim-to-real transfer on a real Franka.
10. Upstream relevant ROCm compatibility fixes, tests, or documentation.

## 13. Team Members and Contributions

Replace or confirm the following information before formal submission:

| Member | Role | Main contributions |
|---|---|---|
| Thomas Yang | Project lead | System design, task definition, and coordination |
| Thomas Yang | Simulation and data | Genesis scene, expert policy, domain randomization, and dataset |
| Yang Jing | Model and evaluation | SmolVLA training, closed-loop evaluation, and result analysis |
| Thomas Yang | AMD optimization | ROCm, HIP Graph, Targeted Compile, and correctness validation |
| Thomas Yang | Reinforcement learning | Residual SAC, reward design, and ablations |

## 14. Reproduction Entry Points and Result Sources

- English project entry: [`README.md`](../README.md)
- Chinese project entry: [`README_ZH.md`](../README_ZH.md)
- Evaluator reproduction guide: [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md)
- Runtime backends: [`optimization/runtime/README.md`](../optimization/runtime/README.md)
- Residual RL: [`franka_fruit_pick/residual_rl/README.md`](../franka_fruit_pick/residual_rl/README.md)
- HIP Graph closed loop: `results/closed_loop/hip_graph/summary_100ep.md`
- Targeted Compile closed loop: `results/closed_loop/targeted_compile/summary_100ep.md`
- Full-inference summary: `results/runtime/summary.md`
- Residual SAC result: `results/residual_rl/lift_no_gate_100ep.json`
- [Banana success video](video/success_examples/banana_success.mp4)
- [Lemon success video](video/success_examples/lemon_success.mp4)
- [Plum success video](video/success_examples/plum_success.mp4)
- [English-narrated success/failure video](video/smolvla_success_failure_demo.mp4)
- [Narration and rebuild notes](video/NARRATION_EN.md)
- [Animated preview](video/preview.gif)
- [Competition figures](figures/README.md)

Compact result summaries used by this report are included under `results/`. Training data and weights remain external and are managed by `artifacts/manifest.json`; unpublished artifact URLs remain a release blocker.

## 15. References

### 15.1 Models, robot learning, and datasets

[1] J. Shukor et al., “SmolVLA: A Vision-Language-Action Model for Affordable and Efficient Robotics,” 2025. [Online]. Available: [https://arxiv.org/abs/2506.01844](https://arxiv.org/abs/2506.01844)

[2] Hugging Face, “SmolVLA: Efficient Vision-Language-Action Model Trained on LeRobot Community Data,” 2025. [Online]. Available: [https://huggingface.co/blog/smolvla](https://huggingface.co/blog/smolvla)

[3] Hugging Face, “LeRobot: An Open-Source Library for End-to-End Robot Learning,” 2026. [Online]. Available: [https://arxiv.org/abs/2602.22818](https://arxiv.org/abs/2602.22818)

[4] B. Calli et al., “Benchmarking in Manipulation Research: The YCB Object and Model Set and Benchmarking Protocols,” *IEEE Robotics & Automation Magazine*, vol. 22, no. 3, pp. 36–52, 2015. [Online]. Available: [https://publications.ri.cmu.edu/benchmarking-in-manipulation-research-the-ycb-object-and-model-setand-benchmarking-protocols](https://publications.ri.cmu.edu/benchmarking-in-manipulation-research-the-ycb-object-and-model-setand-benchmarking-protocols)

### 15.2 Simulation and domain randomization

[5] Genesis Embodied AI, “Genesis: A Generative and Universal Physics Engine for Robotics and Beyond.” [Online]. Available: [https://genesis-embodied-ai.github.io/](https://genesis-embodied-ai.github.io/)

[6] J. Tobin, R. Fong, A. Ray, J. Schneider, W. Zaremba, and P. Abbeel, “Domain Randomization for Transferring Deep Neural Networks from Simulation to the Real World,” 2017. [Online]. Available: [https://arxiv.org/abs/1703.06907](https://arxiv.org/abs/1703.06907)

[7] X. B. Peng, M. Andrychowicz, W. Zaremba, and P. Abbeel, “Sim-to-Real Transfer of Robotic Control with Dynamics Randomization,” 2017. [Online]. Available: [https://arxiv.org/abs/1710.06537](https://arxiv.org/abs/1710.06537)

### 15.3 Reinforcement learning

[8] T. Haarnoja, A. Zhou, P. Abbeel, and S. Levine, “Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor,” in *Proceedings of the 35th International Conference on Machine Learning*, 2018, pp. 1861–1870. [Online]. Available: [https://proceedings.mlr.press/v80/haarnoja18b.html](https://proceedings.mlr.press/v80/haarnoja18b.html)

[9] T. Johannink et al., “Residual Reinforcement Learning for Robot Control,” in *2019 International Conference on Robotics and Automation (ICRA)*, 2019. [Online]. Available: [https://arxiv.org/abs/1812.03201](https://arxiv.org/abs/1812.03201)

### 15.4 AMD GPU, ROCm, and inference compilation

[10] AMD, “Using Graphs in HIP,” *ROCm Documentation*. [Online]. Available: [https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/hip_runtime_api/hipgraph.html](https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/hip_runtime_api/hipgraph.html)

[11] AMD, “HIP Graph API Tutorial,” *ROCm Documentation*. [Online]. Available: [https://rocm.docs.amd.com/projects/HIP/en/develop/tutorial/graph_api.html](https://rocm.docs.amd.com/projects/HIP/en/develop/tutorial/graph_api.html)

[12] AMD, *AMD ROCm Programming Guide*. [Online]. Available: [https://rocm-handbook.amd.com/_/downloads/amd-rocm-programming-guide/en/latest/pdf/](https://rocm-handbook.amd.com/_/downloads/amd-rocm-programming-guide/en/latest/pdf/)

[13] PyTorch, “torch.compile,” *PyTorch Documentation*. [Online]. Available: [https://docs.pytorch.org/docs/stable/generated/torch.compile.html](https://docs.pytorch.org/docs/stable/generated/torch.compile.html)

[14] AMD, *Getting Started with PyTorch on AMD Radeon AI PRO R9700 Series*. [Online]. Available: [https://www.amd.com/content/dam/amd/en/documents/products/graphics/workstation/radeon-ai-pro-rocm-pytorch-guide.pdf](https://www.amd.com/content/dam/amd/en/documents/products/graphics/workstation/radeon-ai-pro-rocm-pytorch-guide.pdf)
