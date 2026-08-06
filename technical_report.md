# Contact-Confirmed Visual Pick-and-Place on AMD ROCm

## Technical Report

**Track:** Physical AI Challenge – Robotics Simulation and Application Design
on AMD Radeon GPUs and ROCm

**Project repository:** `Radeon-hackathon-2026-07`

**Team:** `[Insert team name]`  
**Members:** `[Insert member names and affiliations]`  
**Submission date:** `[Insert date]`

---

## 1. Executive Summary

This project presents a closed-loop visual pick-and-place system for a Franka
Panda robot simulated in Genesis and executed on an AMD Radeon ROCm platform.
The system picks a randomized red cube from a tabletop and places it on a
randomized green target tile. It combines calibrated image-based visual
servoing, dual-finger contact verification, a contact-confirmed grasp latch,
failure recovery, and a bounded PPO residual policy.

The core design principle is to keep a reliable model-based controller in the
loop. Visual perception estimates object and target positions, an IK skill
controller generates the nominal action, contact feedback verifies grasp
quality, and PPO learns only a small correction to the nominal joint command.
This avoids replacing a calibrated pick-and-place skill with an unconstrained
end-to-end policy.

On a held-out evaluation protocol, calibrated color visual servoing achieved a
success rate of **0.70**, while visual servoing with a PPO residual achieved
**0.85**. The Radeon/ROCm benchmark measured **0.1055 ms** mean residual-policy
inference latency and **46.17 FPS** for the complete Genesis-camera-visual
servo-residual control loop.

## 2. Target Application and Practical Value

The target application is **small-part visual sorting and precision placement**
for warehouse fulfillment, laboratory sample handling, and flexible production
lines. Such environments require a robot to localize objects, approach them
safely, verify grasp success, place them accurately, and recover from near-miss
placements without manual intervention.

The current single-object task is deliberately minimal and reproducible, but
its control stack maps directly to a color-coded sorting workflow:

```text
Visual object / target localization
        -> safe approach and grasp verification
        -> transport and placement correction
        -> post-release inspection and bounded retry
```

The design is suitable for later extension to multiple color-coded parts and
multiple target regions without changing the core perception-contact-control
interfaces.

## 3. System Architecture and Design

### 3.1 Closed-loop architecture

```text
Genesis RGB camera + robot proprioception + contact feedback
                         |
             Color marker perception and planar calibration
                         |
              VisualServoController / IK skill state machine
                         |
          ContactAwareGraspVerifier and recovery logic
                         |
       Nominal joint-position action + bounded PPO residual
                         |
                    Franka Panda in Genesis
```

### 3.2 Simulation environment

The environment is a Gymnasium-compatible Genesis scene containing:

- a Franka Panda arm with a parallel gripper;
- a movable red cube;
- a bright green, fixed, non-colliding target tile;
- a fixed RGB camera at `96 x 96` resolution;
- randomized object mass, friction, initial object position, and target
  position.

The target tile is visual-only and has collision disabled, so it improves
perception without modifying placement physics. The object and target colors
provide a transparent, application-relevant perception interface for a
color-coded sorting task.

### 3.3 Contact-confirmed grasping

Pure contact grasping was brittle under wide task randomization. The system
therefore uses a temporary assist latch only after consecutive dual-finger
contact has been observed. The latch is removed when the gripper opens. This
preserves contact evidence while keeping expert data collection and early
policy learning stable.

`ContactAwareGraspVerifier` requires configured consecutive dual-finger contact
evidence before allowing transport. If a contact-confirmed grasp is absent, the
controller returns to an approach state and retries within a bounded recovery
budget.

### 3.4 Visual servoing and recovery

The visual servo controller detects the red object and green target in HSV
space, computes their image centroids, and maps pixels to tabletop coordinates
with homographies calibrated from HDF5 demonstrations. It applies temporal
filtering, re-localizes inconsistent object estimates, and rechecks the placed
object after release. A visible placement miss triggers a bounded re-grasp and
re-place attempt.

The held-object offset is calibrated offline from successful lifted expert
states using the robust median of:

```text
object_position - end_effector_position
```

This compensates for systematic grasp geometry bias during transport and
placement.

### 3.5 Residual reinforcement learning

The PPO policy does not generate the entire robot action. It observes:

- 25-D proprioception;
- red-object and green-target planar estimates plus validity flags;
- contact features;
- skill-phase one-hot encoding;
- nominal visual-servo action.

It outputs a bounded 9-D joint-position residual with scale `0.005`. The final
action is the nominal visual-servo/IK action plus this small correction. An L2
penalty biases the residual toward zero so the learned policy only modifies the
base controller where beneficial.

## 4. Dataset and Training Data

### 4.1 Demonstration collection

Demonstrations are collected by a phase-based damped-least-squares IK expert.
The expert proceeds through approach, grasp, close, lift, transfer, place,
release, and retreat phases. Domain randomization samples:

- object mass: `0.04–0.30`;
- friction: `0.4–1.3`;
- object position: `x=0.54–0.72 m`, `y=-0.16–0.16 m`;
- target position: `x=0.36–0.56 m`, `y=0.12–0.34 m`.

The visual data collection configuration is
`configs/collect_expert_visual_smoke.yaml`. The current visual-training set
contains **100 expert episodes and 3,366 transitions**. Its exact per-episode
randomization, success fields, and schema are preserved in `manifest.json` and
`metadata.json` files.

### 4.2 HDF5 and JSON manifest format

Each demonstration is stored under `data/demo_######` in HDF5. A transition
contains:

- `obs/state`, `next_obs/state`: 39-D privileged simulation state;
- `obs/proprio`, `next_obs/proprio`: 25-D joint, velocity, and EEF state;
- `obs/rgb`, `next_obs/rgb`: RGB images in HWC layout;
- `actions`, `rewards`, `terminated`, `truncated`.

The sidecar JSON manifest records schema version, modalities, transition count,
and episode-level randomization and success metadata. Legacy `state.npy` and
`action.npy` datasets remain readable through `RobotInteractionDataset`.

### 4.3 Training procedures

1. Collect contact-confirmed randomized expert trajectories with RGB frames.
2. Calibrate red/green planar homographies from RGB frames and privileged
   tabletop labels.
3. Calibrate the median gripper-to-object offset from lifted expert states.
4. Evaluate the visual-servo baseline.
5. Train PPO online in Genesis using bounded residual actions over the frozen
   visual-servo base controller.
6. Evaluate base and residual policies with fixed held-out seeds.

## 5. AMD Radeon GPU and ROCm Usage

All major simulation, policy-training, and inference stages run in the official
competition ROCm environment at `/opt/venv`.

| Item | Verified value |
| --- | --- |
| OS | Linux 6.8.0-79-generic x86_64 |
| Python | 3.10.12 |
| PyTorch | 2.9.1+gitff65f5b |
| HIP | 7.2.53211-e1a6bc5663 |
| Genesis | 1.3.1 |
| GPU evidence | AMD `gfx1100`, device ID `0x744b` |
| Available VRAM | 47.98 GB |

The container exposes the AMD device through PyTorch's CUDA-compatible API:
`torch.cuda.is_available()` is true, while `torch.version.hip` identifies the
ROCm backend. The PyTorch/libdrm stack does not expose a marketing name; the raw
`rocm-smi --showproductname` report is preserved in
`results/rocm_benchmark.json`.

This submission uses Genesis' AMD GPU backend (`gs.amdgpu`) and PyTorch's HIP
backend without CUDA source changes. No custom HIP kernels, MIOpen tuning
environment variables, TensorRT, or vendor-specific compiler flags are claimed.
The ROCm contribution is therefore a reproducible compatibility and
measurement workflow, rather than an unverified kernel-level optimization.

```text
Genesis gs.amdgpu simulation and RGB rendering [AMD GPU]
                  -> RGB marker perception [CPU/OpenCV]
                  -> visual-servo features [CPU]
                  -> PyTorch residual PPO inference [AMD GPU / HIP]
                  -> joint-position action -> Genesis [AMD GPU]
```

### 5.1 ROCm performance measurements

| Measurement | Verified value |
| --- | ---: |
| PPO final training throughput | 48.93 FPS |
| PPO training GPU memory | 143.40 MB |
| Residual policy mean inference latency | 0.1055 ms |
| Residual policy inference throughput | 9475.28 Hz |
| End-to-end visual control loop | 46.17 FPS |
| End-to-end benchmark success | 1.00 over 5 episodes |
| Peak PyTorch GPU allocation | 111.93 MB |

The end-to-end measurement includes Genesis simulation, RGB rendering, marker
perception, visual servoing, contact verification, and residual-policy
inference. PPO rollout-internal terminal-step statistics are not used as final
task success metrics; held-out evaluation success is reported separately.

The 48.93-FPS training figure is an end-to-end single-environment PPO rollout
measurement, not a neural-network throughput claim. It includes synchronous
Genesis stepping, camera rendering, Python environment transitions, and PPO
updates. In contrast, the 0.1055-ms policy-only latency isolates the small MLP
on HIP. The current rollout uses `SyncVectorEnv(num_envs=1)`, so the 47.98-GB
device is intentionally under-utilized; parallel GPU environments and mixed
precision are future optimization work.

### 5.2 ROCm policy optimization decision

We measured the policy-only residual MLP for 10,000 synchronized inferences on
the same ROCm environment. The result is stored in
`results/rocm_policy_optimization.json`.

| Execution mode | Mean latency | Throughput | Relative to eager FP32 |
| --- | ---: | ---: | ---: |
| Eager FP32 | 0.1246 ms | 8,023.95 Hz | 1.00x |
| AMP FP16 | 0.1648 ms | 6,066.64 Hz | 0.76x |
| `torch.compile` FP32 | 0.2436 ms | 4,105.52 Hz | 0.51x |

For this small policy, eager FP32 is the selected deployment path: AMP is
approximately 32% slower and `torch.compile` approximately 95% slower in this
microbenchmark. This is an evidence-based configuration choice, not a negative
judgment about ROCm AMP or compilation for larger models, where kernel fusion,
batch size, and convolution workload can change the trade-off. The run emitted
a PyTorch Inductor advisory about float32 matrix-multiplication precision; it
was not changed during this benchmark, preserving a like-for-like comparison.

## 6. Technical Contributions and Innovation

1. **Contact-confirmed assisted grasping.** *Problem:* a geometric latch alone
   can mistake proximity for a grasp. *Method:* transport is gated by
   consecutive dual-finger evidence, with bounded recovery when verification is
   absent. *Verified benefit:* all 20 production visual-servo episodes obtained
   contact evidence before transport. In the 20-episode nominal no-contact-gate
   ablation, base visual-servo success remained 0.70; therefore this experiment
   does **not** establish a nominal-success gain from the gate. Its verified
   contribution is an observable grasp-quality condition and recovery trigger;
   stress testing with deliberately weak or asymmetric contacts is required to
   quantify its reliability benefit.
2. **Calibrated visual servo + contact fusion.** *Problem:* direct RGB-to-9-D
   action regression is difficult to stabilize in this small simulated dataset.
   *Method:* calibrated HSV object/target localization produces geometrically
   meaningful table coordinates, while contact resolves grasp ambiguity.
   *Verified comparison:* the repository's direct visual BC baseline recorded
   0.00 success on its 20-episode evaluation, whereas the calibrated visual
   servo baseline achieved 0.70 under its reported held-out protocol. This is a
   practical baseline comparison, not a claim that HSV generalizes to arbitrary
   objects or lighting.
3. **Offline grasp-geometry calibration.** *Problem:* a fixed nominal
   gripper-object transform creates repeatable placement bias after grasp.
   *Method:* estimate a robust median relative EEF-object offset from successful
   lifted demonstrations. *Evidence:* 3,639 held samples produced the offset
   `[-0.01034, 0.00229, -0.06905] m`, with median absolute deviations below
   3.27 mm in XY and 0.47 mm in Z.
4. **Bounded residual learning.** *Problem:* unconstrained RL can overwrite a
   competent controller with unsafe large joint updates. *Method:* PPO outputs
   only a 9-D correction clipped to 0.005 and regularizes the actor mean toward
   zero. *Verified benefit:* primary held-out success increased from 0.70 to
   0.85 while the mean residual L2 norm was 0.00178. A matched no-L2 ablation
   and phase-by-joint residual analysis are provided but are not reported until
   run.
5. **Auditable data and evaluation pipeline.** *Problem:* robotics claims are
   hard to compare without fixed seeds and artifacts. *Method:* HDF5
   trajectories, JSON manifests, versioned scenario configurations, and JSON
   result files. *Benefit:* every reported table can be regenerated from a
   named command and result path.

## 7. Experimental Results

### 7.1 Visual control comparison

All values below are measured on the same held-out evaluation protocol with 20
episodes.

| Policy | Success rate | Mean episode length | Mean final distance |
| --- | ---: | ---: | ---: |
| Calibrated color visual servo | 0.70 | 236.70 | 3.39 cm |
| Color visual servo + PPO residual | 0.85 | 149.55 | 2.28 cm |

The learned residual had mean L2 norm `0.00178`, indicating small corrective
actions rather than replacement of the nominal controller. The direct visual
BC baseline was evaluated separately and returned 0.00 success. It is retained
as a deliberately simple end-to-end action-regression baseline; it is not used
as the production controller.

### 7.2 Phase-by-joint residual analysis

The action-robust checkpoint was analyzed over 20 held-out episodes. For every
control step, the absolute value of each of the nine residual action dimensions
was accumulated by skill phase. The complete `8 x 9` matrix and phase sample
counts are stored in `results/residual_phase_analysis.json`; Table 3 reports a
compact phase-level summary.

| Skill phase | Control steps | Mean absolute residual | Largest action dimension (magnitude) |
| --- | ---: | ---: | --- |
| Approach | 875 | 0.000389 | J9 (0.000828) |
| Grasp | 25 | 0.000408 | J4 (0.000626) |
| Close | 511 | 0.000484 | J9 (0.000919) |
| Lift | 349 | 0.000508 | J1 (0.000911) |
| Transfer | 409 | 0.000555 | J6 (0.000858) |
| Place | 439 | 0.000461 | J1 (0.001102) |
| Release | 24 | 0.000644 | J1 (0.001622) |
| Retreat | 1,505 | 0.000471 | J4 (0.000704) |

All phase averages are well below the configured residual bound of `0.005`.
The largest mean correction occurs in release, followed by transfer and lift;
therefore the evidence supports **small phase-dependent corrections**, not the
stronger and unsupported claim that residuals act only during grasp or transfer.
The grasp and release estimates have only 25 and 24 samples respectively, so
their per-phase values should be interpreted cautiously.

### 7.3 Contact verification results

The contact-aware visual-servo evaluation verified dual-finger grasp evidence
in all 20 held-out episodes. Measured mean maximum contact force was `226.84`,
and mean maximum consecutive dual-finger contact duration was `313.75` control
steps. The visual-servo system reported zero marker-detection-failure episodes.

### 7.4 Contact-gate ablation

The no-contact-gate diagnostic disabled the dual-finger requirement for both
the temporary grasp latch and controller transport gate. It used 20 nominal
held-out episodes and `stage34_action_robust.pt`; the result is stored in
`results/evaluation_visual_no_contact_gate.json`.

| Policy | Success rate | Mean episode length | Mean final distance |
| --- | ---: | ---: | ---: |
| Visual servo without contact gate | 0.70 | 236.25 | 3.03 cm |
| Residual PPO without contact gate | 0.80 | 202.40 | 2.53 cm |

The base-controller result matches the contact-confirmed visual-servo nominal
success rate (0.70). Consequently, this limited nominal ablation does not show
a task-success advantage for the contact gate. The residual value is reported
for completeness but is not a clean gate-only comparison against the primary
residual result because it uses the action-robust checkpoint. The contact gate
remains justified as a safety and observability mechanism; its performance
advantage should be tested under targeted contact degradation rather than
claimed from this nominal result.

### 7.5 IK robustness baseline

The contact-confirmed IK baseline was evaluated with an independent seed under
four scenarios:

| Scenario | Success rate | Mean final distance |
| --- | ---: | ---: |
| Nominal held-out | 1.00 | 1.40 cm |
| Physics OOD | 0.95 | 1.56 cm |
| Observation noise | 1.00 | 1.46 cm |
| Action noise | 1.00 | 1.40 cm |

### 7.6 Visual-policy robustness benchmark

The action-robust residual policy was fine-tuned with execution noise of 0.004
and evaluated using an independent matched protocol (`seed=2027`, 10 episodes
per scenario). The held-out action-noise condition injects 0.008 joint-position
noise. Results are from
`results/robustness_visual_residual_action_robust.json`.

| Scenario | Visual servo success | Action-robust residual PPO success |
| --- | ---: | ---: |
| Nominal held-out | 0.50 | 0.60 |
| Physics OOD | 0.70 | 0.70 |
| Action noise | 0.50 | 0.60 |

Under action noise, the action-robust residual reduces mean final distance from
4.87 cm to 3.59 cm. Under physics OOD, it matches the base visual servo's
success rate but does not improve final distance. This benchmark uses only 10
episodes per scenario. The observed 0.50-to-0.60 changes are directional
trends, not statistically significant evidence of a general improvement; they
should not be interpreted as a replacement for a multi-seed confidence-interval
study.

## 8. Final Deliverables

The repository provides:

- Genesis/Gymnasium robot environment and task configurations;
- contact-confirmed IK expert and HDF5/JSON dataset pipeline;
- calibrated color-marker visual servo and contact verifier;
- visual-servo residual PPO training and held-out evaluation scripts;
- ROCm benchmark script and JSON results;
- robustness benchmark scripts and result files;
- controlled ablation protocol and result paths in `docs/ablation_protocol.md`;
- reproducibility README;
- headless MP4 recording script and English presentation overlay in
  `experiments/record_demo.py` and `demo/README.md`; the generated video and
  seed-level metadata are written under `demo/outputs/`.

## 9. Reproducibility

The supported competition-image workflow is:

```bash
bash setup_server.sh

/opt/venv/bin/python -m experiments.calibrate_color_markers \
  --dataset datasets/expert_visual_stage34_marker
/opt/venv/bin/python -m experiments.calibrate_grasp_offset \
  --dataset datasets/expert_visual_stage34_marker

/opt/venv/bin/python -m experiments.evaluate_color_servo \
  --config configs/evaluate_color_servo.yaml
/opt/venv/bin/python -m experiments.evaluate_visual_residual \
  --config configs/evaluate_visual_residual.yaml

/opt/venv/bin/python -m experiments.benchmark_rocm \
  --config configs/benchmark_rocm.yaml
/opt/venv/bin/python -m experiments.benchmark_visual_robustness \
  --config configs/benchmark_visual_robustness.yaml
```

The root `README.md` documents full environment setup, dependency
specifications, execution instructions, and step-by-step reproduction.

## 10. Limitations and Next Steps

The current task uses a single rigid cube and color-coded visual cues. The
approach should next be tested with multiple object categories, texture and
lighting randomization, and multi-object sorting. These extensions are outside
the verified results reported above and are not claimed as completed work.

The HSV detector can fail under severe lighting shift, color ambiguity, or hand
occlusion before the grasp latch is established. A next perception route is to
replace the marker detector with RGB-D segmentation and uncertainty-aware pose
estimation while retaining the same contact-gated controller interface.

The action-robust residual policy improves the matched nominal and action-noise
success rates from 0.50 to 0.60, but the absolute result remains moderate. A
future iteration should use a curriculum with randomized disturbance magnitude,
longer training, and more seeds/episodes before claiming broad robustness.

## 11. Team Members and Contributions

Replace this section with the final team information before submission.

| Member | Role | Contribution |
| --- | --- | --- |
| `[Name]` | `[Role]` | `[Contribution]` |
| `[Name]` | `[Role]` | `[Contribution]` |
