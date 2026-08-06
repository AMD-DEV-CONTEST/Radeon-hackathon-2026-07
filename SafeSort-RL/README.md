<img width="792" height="611" alt="image" src="https://github.com/user-attachments/assets/3c218539-78e0-467d-99e3-97cec39ce192" />

# SafeSort-RL



**Language-Conditioned Reinforcement Learning for Simulated Hazardous-Waste Sorting on AMD Radeon GPUs**

SafeSort-RL is a Track 3 robotics simulation project that uses **Genesis 1.3.1**, a **Franka Panda** robot, **Stable-Baselines3 PPO**, **PyTorch**, and **AMD ROCm**. The system receives one of four symbolic task instructions and predicts small Cartesian gripper movements for sorting batteries, chemical bottles, plastic bottles, and syringes into hazard or recycling bins.

The submitted policy uses a compact 23-value state observation and a 3-value continuous action. Genesis simulation and rendering run on the AMD Radeon GPU through the `gs.amdgpu` backend. The PPO policy is loaded and evaluated on the CPU in the submitted notebook.

---
## Quick Links
Video: <video src="SafeSort-RL/videos/safesort_final_realistic_sidepanel_showcase.mp4" width="100%" controls></video>


---

## 1. Submitted Results

The submitted checkpoint produced the following balanced evaluation results across 100 fixed-seed episodes, with 25 episodes per task:

| Task | Success rate |
|---|---:|
| Overall | **81%** |
| Battery to hazard bin | 44% |
| Chemical bottle to hazard bin | 92% |
| Plastic bottle to recycling bin | 88% |
| Syringe to hazard bin | 100% |
| Random-action baseline | 0% |

Additional reported metrics:

| Metric | Value |
|---|---:|
| Mean reward | 38.930 |
| Reward standard deviation | 19.871 |
| Mean episode length | 70.1 steps |
| Mean final object-to-bin distance | 0.158 m |

---

## 2. Required Submission Files

The reproduction package should contain at least the following files:

```text
SafeSort-RL/
├── README.md
├── requirements.txt
├── SafeSort_RL_FINAL_PRESENTATION_READY.ipynb
├── models/
│   └── safesort_genesis_amd_final_best.zip
├── results/
│   ├── final_evaluation.json
│   ├── amd_environment.json
│   └── amd_environment.txt
├── videos/
│   └── safesort_final_realistic_sidepanel_showcase.mp4
└── Genesis/                         # Include when Genesis is installed from bundled source
```

The trained checkpoint is required for policy evaluation and video generation. If it is missing, the notebook can still build the environment and export hardware information, but model-dependent sections are skipped.

---

## 3. Hardware Requirements

Recommended reproduction hardware:

- AMD Radeon GPU supported by the installed ROCm release
- ROCm-compatible Linux environment
- At least 8 GB of system memory
- Sufficient storage for the Python environment, Genesis build cache, checkpoint, results, and video

The submitted run reported:

```text
GPU: AMD Radeon Graphics
PyTorch: 2.8.0+rocm6.4
HIP: 6.4.43482-0f2d60242
Genesis: 1.3.1
Stable-Baselines3: 2.9.0
Python: 3.12.3
```

> PyTorch uses the `torch.cuda` API for ROCm devices. Seeing a device such as `cuda:0` in PyTorch or Genesis output is expected on an AMD ROCm system and does not mean that an NVIDIA GPU is being used.

---

## 4. Software Dependencies

Core dependencies:

| Dependency | Submitted version or requirement |
|---|---|
| Python | 3.12.3 |
| AMD ROCm / HIP | ROCm 6.4 environment used for submission |
| PyTorch | 2.8.0+rocm6.4 |
| Genesis | 1.3.1 |
| Stable-Baselines3 | 2.9.0 |
| Gymnasium | Required |
| NumPy | Required |
| OpenCV (`cv2`) | Required |
| ImageIO | Required |
| ImageIO-FFmpeg | Required for MP4 export |
| JupyterLab or Jupyter Notebook | Required to run the submission notebook |
| IPython / IPykernel | Required by notebook display and kernel execution |

Install the AMD ROCm build of PyTorch using the method provided by the Radeon Cloud image or the ROCm environment administrator. Do not replace it with a generic CPU-only PyTorch installation.

---

## 5. Recommended Environment Setup

The most reliable reproduction path is the same AMD Radeon Cloud environment used for the submission.

### 5.1 Open the project directory

```bash
cd SafeSort-RL
```

### 5.2 Create and activate a Python environment

Skip this step when the provided **Genesis AMD ROCm** environment or kernel is already available.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### 5.3 Install ROCm-enabled PyTorch

Install the ROCm-enabled PyTorch build that matches the host ROCm stack. Verify that the installed build reports a HIP version before continuing.

### 5.4 Install the remaining Python dependencies

```bash
python -m pip install -r requirements.txt
```

### 5.5 Install Genesis

When the submission includes the bundled `Genesis/` source directory:

```bash
python -m pip install -e ./Genesis
```

The notebook expects Genesis version `1.3.1`. If Genesis is already installed in the provided Radeon Cloud environment, confirm the version instead of reinstalling it.

### 5.6 Register the Jupyter kernel

```bash
python -m ipykernel install --user \
  --name genesis-amd \
  --display-name "Genesis AMD ROCm"
```

---

## 6. Verify the AMD ROCm Environment

Run this check before opening the notebook:

```bash
python - <<'PY'
import importlib.metadata
import torch
import genesis as gs

print("PyTorch:", torch.__version__)
print("HIP:", torch.version.hip)
print("GPU available:", torch.cuda.is_available())
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "Unavailable")
print("Genesis:", gs.__version__)
print("Stable-Baselines3:", importlib.metadata.version("stable-baselines3"))

assert torch.cuda.is_available(), "AMD ROCm GPU is not available to PyTorch."
assert torch.version.hip is not None, "The installed PyTorch build does not include ROCm/HIP support."
assert gs.__version__.startswith("1.3.1"), "Genesis 1.3.1 is required."
PY
```

Expected checks:

- `GPU available: True`
- `HIP` is not `None`
- An AMD Radeon device is displayed
- Genesis reports version `1.3.1`
- Stable-Baselines3 reports version `2.9.0`

---

## 7. Notebook Configuration

Open:

```text
SafeSort_RL_FINAL_PRESENTATION_READY.ipynb
```

Select the **Genesis AMD ROCm** kernel. Restart the kernel before every complete rerun because Genesis maintains global simulator state and must be initialized only once per process.

The first notebook configuration cell contains these flags:

```python
RUN_TRAINING = False
RUN_FULL_EVALUATION = False
RUN_RANDOM_BASELINE = False
RUN_INSTRUCTION_SWAP_PROBE = False
RUN_AMD_SNAPSHOT = False
RUN_BENCHMARK = False
RUN_VIDEO = True
```

### Standard submission rerun

Use the default settings above to:

1. verify the AMD ROCm environment,
2. initialize Genesis with `gs.amdgpu`,
3. build the Franka Panda workcell,
4. run the environment smoke test,
5. load the final PPO checkpoint,
6. load the previously verified evaluation values,
7. generate the showcase video,
8. export hardware and result JSON files.

### Full evaluation rerun

To execute a fresh 100-episode balanced evaluation, change:

```python
RUN_FULL_EVALUATION = True
```

The evaluation cycles evenly through all four instructions, uses deterministic PPO actions, and uses evaluation seeds beginning at `150000`.

### Random baseline rerun

To repeat the 50-episode random-action baseline, change:

```python
RUN_RANDOM_BASELINE = True
```

### Fresh training run

Training is disabled by default so evaluators do not accidentally overwrite or replace the submitted checkpoint. To intentionally train a new PPO model, change:

```python
RUN_TRAINING = True
```

The included training function uses:

```text
Policy: MlpPolicy
Learning rate: 3e-4
Rollout length: 1024
Batch size: 256
Epochs per update: 10
Gamma: 0.995
GAE lambda: 0.95
Clip range: 0.2
Entropy coefficient: 0.005
Policy network: [256, 256]
Value network: [256, 256]
Training seed: 42
PPO device in submitted configuration: CPU
Genesis simulation device: AMD GPU through ROCm
```

A fresh training run does not guarantee the exact submitted 81% score unless the same training stages, checkpoints, software versions, random seeds, and hardware conditions are used. The provided checkpoint should be used when reproducing the official submitted evaluation.

---

## 8. Run the Notebook Interactively

Start JupyterLab:

```bash
jupyter lab
```

Then:

1. Open `SafeSort_RL_FINAL_PRESENTATION_READY.ipynb`.
2. Select **Kernel → Change Kernel → Genesis AMD ROCm**.
3. Select **Kernel → Restart Kernel and Run All Cells**.
4. Allow the initial Genesis scene build and JIT compilation to finish.
5. Do not rerun the Genesis initialization cell in the same kernel.
6. Confirm that the final status cell reports a loaded checkpoint and generated video.

---

## 9. Run the Notebook Non-Interactively

A complete automated notebook execution can be started with:

```bash
jupyter nbconvert \
  --to notebook \
  --execute SafeSort_RL_FINAL_PRESENTATION_READY.ipynb \
  --ExecutePreprocessor.kernel_name=genesis-amd \
  --ExecutePreprocessor.timeout=-1 \
  --output SafeSort_RL_REPRODUCED.ipynb
```

Use a fresh process for every run. This avoids the `Genesis already initialized` error.

---

## 10. Expected Output Files

After a successful standard rerun, verify these files:

```text
results/final_evaluation.json
results/amd_environment.json
results/amd_environment.txt
videos/safesort_final_realistic_sidepanel_showcase.mp4
```

The final evaluation JSON contains:

- project and simulator information,
- selected checkpoint path,
- GPU and HIP information,
- overall and per-task success rates,
- random-policy baseline,
- instruction-swap probe results,
- fresh evaluation results when enabled.

The final notebook status should include values similar to:

```text
Genesis device: cuda:0
GPU: AMD Radeon Graphics
Checkpoint loaded: True
Video generated: True
Verified overall success: 81%
```

---

## 11. Reproduction Validation Checklist

Before reporting that reproduction succeeded, verify all of the following:

- [ ] PyTorch detects an AMD ROCm device.
- [ ] `torch.version.hip` is not `None`.
- [ ] Genesis is version `1.3.1`.
- [ ] Genesis initializes with `backend=gs.amdgpu`.
- [ ] The Genesis scene builds without an initialization error.
- [ ] The environment smoke test returns a 23-value finite observation.
- [ ] `models/safesort_genesis_amd_final_best.zip` loads successfully.
- [ ] The policy device is reported as CPU.
- [ ] The Genesis simulation device is reported as the ROCm GPU.
- [ ] The 100-episode evaluation uses 25 episodes per instruction when enabled.
- [ ] `results/final_evaluation.json` is created.
- [ ] AMD environment JSON and text files are created.
- [ ] The final showcase MP4 is created.

---

## 12. Important Scope and Limitations

- The task instruction is represented as a four-way symbolic one-hot vector; it is not encoded by CLIP or another pretrained language model.
- The PPO policy receives a 23-value state vector; it does not infer actions directly from a 64×64 RGB image.
- The simulation environment is Genesis, not PyBullet.
- Grasp attachment and release are deterministic safety operations rather than learned end-to-end behaviors.
- The final showcase video uses a deterministic, physically checked manipulation sequence for presentation. It is separate from the PPO evaluation.
- All reported results are from simulation; the project has not yet been validated on a physical Franka Panda robot.

---

## 13. Troubleshooting

### `ROCm GPU is not available`

Confirm that the host exposes the AMD GPU, the ROCm runtime is installed, and the active Python environment contains a ROCm-enabled PyTorch build.

### `This is not a ROCm PyTorch build`

A CPU-only or incompatible PyTorch package is active. Switch to the provided Radeon Cloud environment or reinstall the correct ROCm build.

### `Genesis already initialized`

Restart the notebook kernel or start a new Python process. Do not rerun the Genesis initialization cell in the same process.

### No checkpoint was found

Place this file in the `models/` directory:

```text
models/safesort_genesis_amd_final_best.zip
```

The notebook also checks these fallback names:

```text
models/safesort_genesis_amd_balanced.zip
models/safesort_genesis_amd_targeted.zip
models/safesort_genesis_amd_stable.zip
```

### Video was not generated

Confirm that:

```python
RUN_VIDEO = True
```

Also verify that the final checkpoint loaded successfully and that ImageIO/FFmpeg support is installed.

### Fresh evaluation does not exactly match 81%

Confirm the checkpoint, Genesis version, PyTorch/ROCm versions, deterministic policy setting, and evaluation seed. Small differences may occur when the simulator, numerical libraries, or hardware environment differ from the submitted setup.

---

## 14. Reproducibility Summary

For the closest reproduction of the submitted result:

1. Use the provided AMD Radeon Cloud environment.
2. Select the **Genesis AMD ROCm** kernel.
3. Confirm PyTorch `2.8.0+rocm6.4`, Genesis `1.3.1`, and Stable-Baselines3 `2.9.0`.
4. Include `models/safesort_genesis_amd_final_best.zip`.
5. Set `RUN_FULL_EVALUATION=True` to recompute all 100 balanced episodes.
6. Restart the kernel and run every notebook cell once, in order.
7. Confirm the exported JSON files and showcase MP4.
8. Compare fresh metrics with the submitted 81% overall result and per-task scores.
