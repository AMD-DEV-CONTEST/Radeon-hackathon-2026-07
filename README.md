# Contact-Confirmed Visual Pick-and-Place on AMD ROCm

The English technical report draft is available at
[docs/technical_report.md](docs/technical_report.md).

This Track 3 project runs a Franka Panda pick-and-place task in Genesis on an
AMD ROCm GPU. The robot picks a randomized red cube and places it on a
randomized, visible green target tile.

```text
RGB camera + 25-D proprioception
              |
      visual object/target estimator
              |
IK phase controller + contact-confirmed grasp latch
              |
         Franka joint-position action
```

The grasp latch is enabled only after both fingers contact the cube for the
configured consecutive steps, and is removed when the gripper opens. This
keeps data collection stable while retaining contact evidence in every episode.

## 1. Environment Setup

### Supported platform

- Linux x86_64 with a compatible AMD Radeon GPU and ROCm driver;
- official competition image: its preinstalled `/opt/venv` ROCm PyTorch is the
  supported interpreter;
- Python 3.10.

Do **not** use bare `/usr/bin/python` on the competition image, and do not
replace its PyTorch with a generic CUDA wheel. ROCm PyTorch exposes AMD devices
through the `torch.cuda` API, so an AMD GPU is normally reported as `cuda:0`.

### Competition-image installation

Run from the repository root. The script preserves the image's ROCm-enabled
PyTorch, installs the remaining project packages, configures headless EGL, and
checks GPU availability.

```bash
bash setup_server.sh
source /opt/venv/bin/activate
```

For non-interactive shells, use the interpreter explicitly:

```bash
/opt/venv/bin/python tests/test_gpu.py
/opt/venv/bin/python -m simulation.test_env
```

`setup_server.sh` requires root only when the host still needs the EGL/Mesa
system packages. The official competition container normally runs as root.

### Conda/micromamba alternative

`environment.yml` specifies a Python 3.10 environment and ROCm 6.4 PyTorch
wheels. Use it only on a host with a matching ROCm runtime and working package
network access:

```bash
micromamba create -f environment.yml
micromamba run -n Radeon-hackathon-2026-07 python tests/test_gpu.py
```

## 2. Dependency Specification

The authoritative dependency definitions are [environment.yml](environment.yml)
and [setup_server.sh](setup_server.sh).

| Component | Specification / source |
| --- | --- |
| Python | `3.10` |
| PyTorch | ROCm-enabled PyTorch preinstalled at `/opt/venv`; conda alternative pins `torch==2.9.1+rocm6.4` |
| Simulator | `genesis-world[render]` with headless EGL |
| Numerical ABI | `setup_server.sh` enforces `numpy<2` with `scipy` and `scikit-image` |
| RL and environment | `gymnasium`, `cleanrl`, `tensorboard` |
| Data and utilities | `h5py`, `pyyaml`, `tqdm`, `pytest` |
| Vision/export | `opencv-python`, `onnx` |

The NumPy 1.x constraint avoids binary incompatibility with rendering-related
extension wheels. The setup script also removes a stale `127.0.0.1:7890` proxy
configuration if one was inherited from another machine.

## 3. Execution and Usage

### Simulator smoke test

```bash
/opt/venv/bin/python tests/test_gpu.py
/opt/venv/bin/python -m simulation.test_env
```

Expected behavior: Genesis initializes with the AMD GPU backend and creates the
headless scene without requiring an X11 display.

### Visual perception + IK policy

The current visual pipeline uses RGB plus proprioception to estimate cube and
target positions. The estimator drives the existing calibrated IK phase
controller; it does not directly regress a nine-dimensional robot action.

```bash
# Collect 100 randomized, RGB-labelled expert episodes.
/opt/venv/bin/python -m experiments.collect_expert \
  --config configs/collect_expert_visual_smoke.yaml

# Train RGB + proprioception -> object/target position estimator.
/opt/venv/bin/python -m experiments.train_visual_state_estimator \
  --config configs/train_visual_ik.yaml

# Evaluate held-out visual perception + IK rollouts.
/opt/venv/bin/python -m experiments.evaluate_visual_ik \
  --config configs/evaluate_visual_ik.yaml
```

The visual-IK trainer keeps table-level pre-grasp object observations for this
task. This prevents a single estimator from averaging visually incompatible
table, lifted, and placed-object poses. It uses worker-safe HDF5 loading and
writes `*_latest.pt` every configured interval plus `*_best.pt` checkpoints.

The evaluation reports closed-loop `success_rate` and position RMSE values.
`initial_*_rmse_m` is the first-frame perception error; it should be used to
separate a perception failure from an error accumulated during control.

### Calibrated color-marker visual servo baseline

The red cube and green target tile also support an interpretable image-based
visual-servo baseline. A homography is fitted from HDF5 RGB frames to table
coordinates, then the calibrated marker positions drive the same contact-aware
IK phase controller.

```bash
/opt/venv/bin/python -m experiments.calibrate_color_markers \
  --dataset datasets/expert_visual_stage34_marker

# Estimate the fixed gripper-to-object geometry from successful expert lifts.
/opt/venv/bin/python -m experiments.calibrate_grasp_offset \
  --dataset datasets/expert_visual_stage34_marker

/opt/venv/bin/python -m experiments.evaluate_color_servo \
  --config configs/evaluate_color_servo.yaml
```

The controller re-localizes a disagreeing object estimate and performs a
bounded re-approach/re-grasp when closing times out without a contact-confirmed
grasp. Evaluation records recovery counts, dual-finger-contact evidence, final
phase distribution, and final target distance for failure analysis. When the
red object remains visible in the contact-confirmed latch frame, its aligned
camera/EEF measurement calibrates the placement-relevant XY grasp offset.
After an unsuccessful release, the controller checks the visible object against
the green tile and performs a bounded re-grasp/re-place recovery when needed.
Before lift/transport, `ContactAwareGraspVerifier` requires the latch to be
backed by configured consecutive dual-finger contact steps; contact-force and
verification metrics are included in evaluation output.

With the marker dataset, offline grasp-offset calibration, and held-out seed
`777`, the verified color-servo result is `0.70` success rate over 20 episodes.
The measured mean object/target XY errors are `4.65 mm` / `10.08 mm`; these are
the current visual-servo baseline, not the final robustness result.
The contact verifier preserved this result while confirming dual-finger grasp
evidence in all 20 evaluation episodes.

### Visual-servo residual PPO

PPO can be trained as a bounded joint-position residual over the calibrated
visual-servo controller. Its observation contains marker estimates,
proprioception, contact state, skill phase, and the base action; RGB is not
flattened. Run the 4k-step plumbing check before a longer training run:

```bash
/opt/venv/bin/python -m experiments.train_visual_residual \
  --config configs/train_visual_residual_smoke.yaml
```

After the smoke checkpoint is created, run the formal training and a held-out
base-versus-residual comparison:

```bash
/opt/venv/bin/python -m experiments.train_visual_residual \
  --config configs/train_visual_residual.yaml

/opt/venv/bin/python -m experiments.evaluate_visual_residual \
  --config configs/evaluate_visual_residual.yaml
```

The verified held-out comparison over 20 episodes is:

| Policy | Success rate | Mean final distance |
| --- | ---: | ---: |
| Color visual servo | 0.70 | 3.39 cm |
| Color visual servo + residual PPO | 0.85 | 2.28 cm |

The learned residual has mean L2 norm `0.00178`, showing that it makes bounded
placement corrections instead of replacing the calibrated base controller.

### State-policy baseline

The state baseline is included for comparison. It combines deterministic IK
with a learned PPO residual, and reports IK-only, zero-residual, and learned
residual variants.

```bash
/opt/venv/bin/python -m experiments.collect_expert \
  --config configs/collect_expert_stage34_stress.yaml
/opt/venv/bin/python -m experiments.train_cli \
  --config configs/train_stage34_stress.yaml
/opt/venv/bin/python -m experiments.evaluate_cli \
  --config configs/evaluate_stage34_stress.yaml
```

### Dataset inspection

Use this read-only check before changing model capacity or recollecting data.
It verifies image variation, label ranges, and checkpoint error on the training
dataset.

```bash
/opt/venv/bin/python -m experiments.inspect_visual_state_estimator \
  --dataset datasets/expert_visual_stage34_marker \
  --checkpoint checkpoints/visual_ik/stage34.pt
```

## 4. Step-by-Step Reproduction

The commands below reproduce the current visual-IK experiment from a clean
competition image.

1. Clone or copy this repository to the server, then enter its root directory.

   ```bash
   cd /workspace/Radeon-hackathon-2026-07
   ```

2. Install dependencies into the prebuilt ROCm environment and validate it.

   ```bash
   bash setup_server.sh
   /opt/venv/bin/python tests/test_gpu.py
   /opt/venv/bin/python -m simulation.test_env
   ```

3. Collect new visual demonstrations. This dataset must be collected after the
   green target marker and red object surface are present; older visual HDF5
   files do not contain those visual cues.

   ```bash
   /opt/venv/bin/python -m experiments.collect_expert \
     --config configs/collect_expert_visual_smoke.yaml
   ```

4. Confirm dataset content before training.

   ```bash
   /opt/venv/bin/python -m experiments.inspect_visual_state_estimator \
     --dataset datasets/expert_visual_stage34_marker
   ```

5. Train the visual state estimator. The resulting checkpoint is written to
   `checkpoints/visual_ik/stage34.pt`.

   ```bash
   /opt/venv/bin/python -m experiments.train_visual_state_estimator \
     --config configs/train_visual_ik.yaml
   ```

6. Re-run the inspection with the checkpoint and record its training-set RMSE.

   ```bash
   /opt/venv/bin/python -m experiments.inspect_visual_state_estimator \
     --dataset datasets/expert_visual_stage34_marker \
     --checkpoint checkpoints/visual_ik/stage34.pt
   ```

7. Run the held-out evaluation. Preserve this final JSON-like console output
   for the technical report.

   ```bash
   /opt/venv/bin/python -m experiments.evaluate_visual_ik \
     --config configs/evaluate_visual_ik.yaml
   ```

## 5. Data, Outputs, and Current Scope

Each HDF5 dataset stores episodes under `data/demo_######` with:

- `obs/state` and `next_obs/state`: 39-D privileged state;
- `obs/proprio` and `next_obs/proprio`: 25-D robot proprioception;
- `obs/rgb` and `next_obs/rgb`: HWC RGB frames;
- `actions`, `rewards`, `terminated`, `truncated`.

`manifest.json` records schema version, modalities, transition count, and
episode metadata. `RobotInteractionDataset` also reads legacy `state.npy` /
`action.npy` pairs.

The current implementation scope is: HDF5 data pipeline, contact-confirmed IK
expert, state residual PPO baseline, and visual state estimation plus IK.
Visual residual PPO and the final robustness benchmark are subsequent project
stages, not prerequisites for running the commands above.

### Held-out robustness benchmark

The benchmark uses an evaluation-only seed and tests nominal, wider physical
randomization, noisy observations, and noisy joint-position commands. It writes
per-scenario success, grasp-evidence, lift, final-distance, and episode-length
metrics to `results/robustness_ik.json`.

```bash
/opt/venv/bin/python -m experiments.robustness_benchmark \
  --config configs/robustness_benchmark.yaml
```

The verified IK baseline results are `1.00` success for nominal, observation
noise, and action-noise scenarios, and `0.95` for the wider physics-OOD
scenario. These values are baseline evidence, not visual-policy results.

### AMD Radeon / ROCm benchmark

This command writes environment versions, HIP availability, GPU name/memory,
checkpoint training metrics, pure residual-policy latency, end-to-end
Genesis-plus-visual-servo control FPS, and peak GPU memory to
`results/rocm_benchmark.json`.

```bash
/opt/venv/bin/python -m experiments.benchmark_rocm \
  --config configs/benchmark_rocm.yaml
```

On the verified competition server, the residual policy measured `0.105 ms`
mean GPU inference latency (`9,488 Hz`), while the full Genesis-camera-visual
servo-residual loop measured `45.83 FPS` over five rollouts with `1.00` success
rate and about `112 MB` peak PyTorch GPU allocation. The separate held-out
task-success evaluation remains the authoritative policy metric.
The ROCm SMI report identifies the accelerator as an AMD `gfx1100` device
(`0x744b`) with 47.98 GB VRAM. The container's PyTorch/libdrm stack does not
expose a marketing name, so the report preserves the raw ROCm SMI evidence.

### Visual-policy robustness benchmark

Evaluate the base visual servo and PPO residual policy under identical held-out
nominal, physics-OOD, and action-noise sequences:

```bash
/opt/venv/bin/python -m experiments.benchmark_visual_robustness \
  --config configs/benchmark_visual_robustness.yaml
```

The result is written to `results/robustness_visual_residual.json`.

If action-noise evaluation reveals a residual-policy distribution shift, use
the provided action-robust fine-tuning configuration and rerun the matched
benchmark before reporting final robustness values:

```bash
/opt/venv/bin/python -m experiments.train_visual_residual \
  --config configs/train_visual_residual_action_robust.yaml

/opt/venv/bin/python -m experiments.benchmark_visual_robustness \
  --config configs/benchmark_visual_robustness_action_robust.yaml
```

The verified matched action-robust benchmark (`seed=2027`, 10 episodes per
scenario) reports base/residual success of `0.50/0.60` for nominal held-out,
`0.70/0.70` for physics OOD, and `0.50/0.60` for action noise. These values are
separate from the 20-episode seed-777 primary evaluation and are reported with
their protocol to avoid conflating the two measurements.

### Controlled ablations and ROCm optimization checks

The report does not claim an ablation result until its JSON file has been
generated. Run the English [ablation protocol](docs/ablation_protocol.md) to
produce: the direct RGB action-regression baseline, a no-contact-gate
diagnostic, an L2-prior ablation, a phase-by-joint residual analysis, and an
eager/AMP/`torch.compile` ROCm policy microbenchmark.

The completed phase analysis (`results/residual_phase_analysis.json`, 20
episodes) confirms that every phase-average residual is below `0.00065`, far
inside the configured `0.005` bound. The largest average correction occurs in
release; this is reported as phase-dependent local correction rather than an
unsupported claim that only one phase benefits.

The completed ROCm policy microbenchmark
(`results/rocm_policy_optimization.json`, 10,000 synchronized inferences)
selects eager FP32 for this small MLP: `0.1246 ms` / `8023.95 Hz`, versus AMP
FP16 at `0.1648 ms` / `6066.64 Hz` and `torch.compile` FP32 at `0.2436 ms` /
`4105.52 Hz`. These policy-only measurements do not replace the end-to-end
Genesis benchmark.

The nominal no-contact-gate diagnostic
(`results/evaluation_visual_no_contact_gate.json`, 20 episodes) records visual
servo success of `0.70` and residual-PPO success of `0.80`. The base result
matches the contact-confirmed visual-servo success rate, so the repository does
not claim a nominal-success improvement from contact gating; it is retained as
a verified grasp-evidence and recovery constraint.

## 6. Optional Docker Execution

```bash
docker build -t radeon-hackathon .
docker run --rm -it --device=/dev/kfd --device=/dev/dri --group-add video radeon-hackathon
```

The ROCm kernel driver must be installed on the host.
