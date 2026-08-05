# ChronoSafe-Drive Reproducibility Guide

This guide reproduces the competition results on the official AMD Radeon cloud
environment. Commands are divided into three levels so reviewers can validate
the submitted checkpoint and closed loop without first rebuilding every raw
dataset.

## 1. Validated environment

### Hardware and software

| Component | Validated configuration |
|---|---|
| GPU | AMD Radeon Graphics, `gfx1100`, 47.984 GiB VRAM |
| ROCm/HIP | HIP `7.2.53211` |
| PyTorch | `2.9.1+rocm7.2.1` |
| Python | 3.12.3 |
| OS | Linux 6.8 x86_64 |
| Simulator | MetaDrive 0.4.3 |

The official cloud virtual environment is located at `/workspace/rdna`. The
persistent project directory is `/workspace/persistent/ChronoSafe-Drive`.

### System packages

The closed-loop RGB camera path requires Xvfb on display-less instances:

```bash
sudo apt-get update
sudo apt-get install -y xvfb ffmpeg
```

The official cloud image already provides these packages. `ffmpeg` is used only
for demonstration-video assembly and is not required for model evaluation.

## 2. Environment setup

```bash
source /workspace/rdna/bin/activate
cd /workspace/persistent/ChronoSafe-Drive

python -m pip install -e .
python -m pip install -r requirements.txt
```

Do not reinstall `torch` from the default PyPI index. The generic wheel may not
contain AMD ROCm support.

Verify the runtime:

```bash
python - <<'PY'
import torch

assert torch.cuda.is_available(), "No ROCm GPU is visible"
assert torch.version.hip is not None, "This is not a ROCm PyTorch build"

print("GPU:", torch.cuda.get_device_name(0))
print("PyTorch:", torch.__version__)
print("HIP:", torch.version.hip)
print("ROCm environment: PASS")
PY
```

Expected device family:

```text
GPU: AMD Radeon Graphics
PyTorch: 2.9.1+rocm7.2.1...
HIP: 7.2...
ROCm environment: PASS
```

## 3. Repository tests

Run the dependency-light unit tests before using model or dataset artifacts:

```bash
python -m unittest discover -s tests -v
```

The timestamp-corruption tests cover missing bursts, jitter determinism,
timestamp-channel swaps, and spoofed-clean metadata. Dataset-builder tests cover
split determinism, log-level leakage prevention, synchronization, and feature
shape.

Cross-check every public headline result against the frozen JSON evidence:

```bash
python scripts/verify_submission_claims.py
```

Expected output:

```text
SUBMISSION CLAIMS PASS: 118 frozen evidence checks
```

## 4. Required artifact layout

The commands below use the following paths:

```text
configs/
  nuscenes_trainval_v3_split.json

data/
  chronosafe_metadrive_timing_32seeds.npz
  chronosafe_nuscenes_trainval_timing_v3.npz
  chronosafe_nuscenes_trainval_timing_v3.json

artifacts/
  hybrid_timing_gru_v3_large_seed2026/model.pt
  hybrid_timing_gru_v3_large_seed2027/model.pt
  hybrid_timing_gru_v3_large_seed2028/model.pt
  hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt
  hybrid_timing_gru_v3_timestamp_robust_seed2027/model.pt
  hybrid_timing_gru_v3_timestamp_robust_seed2028/model.pt
```

Small submitted checkpoints and the frozen split manifest are supplied at these
exact paths. Large generated data are intentionally excluded from Git and can
be rebuilt as described in Section 9.

The selected checkpoint used by the closed-loop and ROCm benchmark has SHA-256:

```text
2e3eeb470ebba19f2b7bfc3f94a7c346f34a9634f91743a06a61a05baec62c5d
```

The frozen real-data and split hashes are:

```text
nuScenes derived NPZ:
023c2c24bb4e3b13ddfaf5fa45c0bf66f957337fd7070e0f3a5fdfa930437b50

split manifest:
1ec33bd7cd404438f47d06607710ae143d1a95e83603f61df7b457cd11607cac
```

## 5. Level A - reproduce AMD ROCm inference evidence

This is the fastest end-to-end GPU validation. It uses only frozen held-out
nuScenes sequences and the selected model.

```bash
python scripts/benchmark_rocm_inference.py \
  --data data/chronosafe_nuscenes_trainval_timing_v3.npz \
  --split-file configs/nuscenes_trainval_v3_split.json \
  --model artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt \
  --output results/rocm_inference_benchmark_seed2026 \
  --batch-sizes 1,32,256,1024 \
  --warmup-iterations 50 \
  --iterations 300 \
  --verification-samples 8192
```

Required terminal status:

```text
ChronoSafe AMD ROCm inference benchmark: PASS
```

Generated outputs:

```text
results/rocm_inference_benchmark_seed2026/
  benchmark.json
  benchmark.csv
  benchmark.md
  benchmark.png
```

The script fails if ROCm is unavailable or AMP numerical agreement violates the
frozen thresholds.

## 6. Level B - reproduce the 20-seed closed loop

Use Xvfb without `--raw-headless-fallback`. The fallback changes the camera
feature distribution and is not valid for formal evaluation.

```bash
xvfb-run -a python scripts/run_multiseed_closed_loop.py \
  --protocol configs/paper_protocol.json \
  --model artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt \
  --output results/closed_loop_xvfb_timestamp_robust_seed2026 \
  --log-dir evidence/closed_loop_xvfb_timestamp_robust_seed2026
```

To resume an interrupted run without repeating completed seeds:

```bash
xvfb-run -a python scripts/run_multiseed_closed_loop.py \
  --protocol configs/paper_protocol.json \
  --model artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt \
  --output results/closed_loop_xvfb_timestamp_robust_seed2026 \
  --log-dir evidence/closed_loop_xvfb_timestamp_robust_seed2026 \
  --resume
```

Required terminal status:

```text
ChronoSafe paper multi-seed closed-loop: PASS
```

Verify the frozen aggregate:

```bash
python - <<'PY'
import json

path = "results/closed_loop_xvfb_timestamp_robust_seed2026/aggregate.json"
data = json.load(open(path, encoding="utf-8"))

assert data["runs"] == 20
assert data["mrm_success_rate"] == 1.0
assert data["mrm_reached_rate"] == 1.0
assert data["premature_mrm_rate"] == 0.0

print("20-seed closed-loop aggregate: PASS")
PY
```

## 7. Level C - reproduce held-out real-data evaluation

### Fair evaluation for one robust seed

```bash
python scripts/evaluate_hybrid_nuscenes_gru.py \
  --data data/chronosafe_nuscenes_trainval_timing_v3.npz \
  --model artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt \
  --output results/fair_trainval_v3_timestamp_robust_seed2026 \
  --split-file configs/nuscenes_trainval_v3_split.json \
  --recalibrate
```

Repeat with seeds `2027` and `2028` for the three-seed aggregate.

### Timestamp stress evaluation for the three robust seeds

```bash
python scripts/evaluate_timestamp_robustness.py \
  --data data/chronosafe_nuscenes_trainval_timing_v3.npz \
  --split-file configs/nuscenes_trainval_v3_split.json \
  --models \
    artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026/model.pt \
    artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2027/model.pt \
    artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2028/model.pt \
  --output results/timestamp_robustness_v4_robust_aggregate \
  --batch-size 1024 \
  --seed 2026
```

Generated reports contain per-condition accuracy, factor metrics, risk MAE,
coverage, and plots. The standard-v3 checkpoints use the same command and split
for the baseline comparison.

## 8. Reproduce model training

The final robust model uses 120,000 sampled temporal sequences per run: 60,000
from MetaDrive and 60,000 from nuScenes.

```bash
python scripts/train_hybrid_nuscenes_gru.py \
  --simulation-data data/chronosafe_metadrive_timing_32seeds.npz \
  --real-data data/chronosafe_nuscenes_trainval_timing_v3.npz \
  --real-split-file configs/nuscenes_trainval_v3_split.json \
  --output artifacts/hybrid_timing_gru_v3_timestamp_robust_seed2026 \
  --epochs 100 \
  --sequence-length 8 \
  --hidden-size 128 \
  --batch-size 512 \
  --sequences-per-source 60000 \
  --scenario-loss-weight 0 \
  --timestamp-augmentation-probability 0.6 \
  --timestamp-calibration-mode stress \
  --seed 2026 \
  --deterministic
```

Repeat with seeds `2027` and `2028`, changing both `--seed` and `--output`.
Every training run checks for AMD ROCm and writes a checkpoint plus
machine-readable training/evaluation metrics.

## 9. Rebuild the derived datasets

### 9.1 MetaDrive timing dataset

The frozen 32 domains are the 28 training seeds, two calibration seeds, and two
internal test seeds in `configs/paper_protocol.json`.

```bash
xvfb-run -a python scripts/collect_dataset.py \
  --seeds 3,5,7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83,89,97,101,103,107,109,113,127,131,137 \
  --steps-per-seed 140 \
  --feature-mode timing \
  --output data/chronosafe_metadrive_timing_32seeds.npz
```

### 9.2 nuScenes timing dataset

Download nuScenes v1.0-trainval keyframe archives and metadata from the official
nuScenes website. Place the extracted files under `data/nuscenes_trainval`.
The repository does not redistribute raw nuScenes media.

```bash
python scripts/build_nuscenes_degradation_dataset.py \
  --root data/nuscenes_trainval \
  --version v1.0-trainval \
  --keyframes-only \
  --feature-mode timing \
  --augmentations 3 \
  --output data/chronosafe_nuscenes_trainval_timing_v3.npz \
  --split-output configs/nuscenes_trainval_v3_split.json \
  --preview-dir results/nuscenes_trainval_v3_previews
```

Expected derived-data scale:

```text
850 scenes
34,149 aligned camera/LiDAR pairs
239,043 degradation samples
5,950 temporal tracks
15 features per step
```

## 10. Expected headline results

| Result | Expected value |
|---|---:|
| Robust intact scenario accuracy | 99.3446% +/- 0.1093% |
| Missing-50% timestamp accuracy | 97.7715% +/- 0.0730% |
| Two-frame timestamp-jitter accuracy | 96.6868% +/- 0.4945% |
| 20-seed MRM success rate | 100% |
| Premature MRM rate | 0% |
| Closed-loop scenario accuracy | 97.0714% +/- 2.8541% |
| Closed-loop upper-risk coverage | 99.8333% +/- 0.2796% |
| AMD ROCm FP32 batch-1 p50 | 0.558821 ms |
| AMD ROCm FP32 batch-1024 throughput | 1,371,235.75 sequences/s |

Minor timing variation is expected across GPU clocks and concurrent workloads.
Diagnostic and safety metrics should match when artifacts, versions, and seeds
are unchanged.

## 11. Troubleshooting

### `torch.version.hip is None`

The environment contains a non-ROCm PyTorch build. Reactivate `/workspace/rdna`
and do not replace its AMD wheel with a generic PyPI installation.

### MetaDrive fails with `NoneType ... set_shader`

Run through `xvfb-run -a`. Do not use `--raw-headless-fallback` for reported
metrics because it changes camera observations.

### A long cloud run stops after SSH disconnects

Launch long training inside `tmux`, `screen`, or `nohup`. All data, code,
checkpoints, and results must remain under `/workspace/persistent`.

### nuScenes files are not found

Confirm that `v1.0-trainval/*.json`, `samples/CAM_FRONT`, and
`samples/LIDAR_TOP` are under the directory passed to `--root`.
