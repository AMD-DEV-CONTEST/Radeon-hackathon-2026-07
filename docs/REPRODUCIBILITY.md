# Reproducibility Guide

English | [Chinese version](REPRODUCIBILITY_ZH.md)

This document explains how competition evaluators can set up the environment, obtain dependencies and external artifacts, run the system, and reproduce the main results in the technical report.

> Results frozen on August 5, 2026. Run all commands from the repository root. Write new outputs under `reproductions/`; do not overwrite submitted results.

## 1. Reproduction Levels

| Level | Scope | Data/weights required | New training required |
|---|---|---:|---:|
| A | Read reports, figures, and compact results | No | No |
| B | Check Python syntax, CLIs, and summary tools | No | No |
| C | Load the model and run one closed-loop episode | Yes | No |
| D | Run full-inference benchmarks and strict validation | Yes | No |
| E | Run the 300-episode closed-loop A/B evaluation | Yes | No |
| F | Regenerate data and retrain | No (generate locally) | Yes |

Evaluators should start with A–D. Levels E and F are time-consuming and are not prerequisites for reviewing the submission.

## 2. Validated Environment

| Component | Version |
|---|---|
| OS | Ubuntu 24.04 |
| Python | 3.12.3 |
| ROCm | 7.2.1; result JSON records HIP `7.2.53211-e1a6bc5663` |
| PyTorch | `2.9.1+rocm7.2.1.gitff65f5bc` |
| torchvision | `0.24.0+rocm7.2.1.gitb919bd0c` |
| torchaudio | `2.9.0+rocm7.2.1.gite3c6ee2b` |
| Triton | `3.5.1+rocm7.2.1.gita272dfa8` |
| LeRobot | 0.6.0 |
| Genesis | 1.1.2 or compatible |
| Target GPU | AMD Radeon AI PRO R9700 |

The `cuda` device name in the code is the ROCm PyTorch compatibility interface.

## 3. Environment Setup

### 3.1 Docker

```bash
docker build -f docker/Dockerfile -t pick-fruit-smolvla:rocm7.2.1 .

docker run --rm -it \
  --network=host \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --group-add render \
  --security-opt seccomp=unconfined \
  --ipc=host \
  --shm-size=8g \
  -v "$PWD":/workspace/Pick-Fruit-By-SmolVLA \
  -w /workspace/Pick-Fruit-By-SmolVLA \
  pick-fruit-smolvla:rocm7.2.1
```

Inside the container:

```bash
export PYTHON_BIN=/opt/venv/bin/python
export PROJECT_ROOT=/workspace/Pick-Fruit-By-SmolVLA
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME=/workspace/huggingface_cache
export HSA_ENABLE_SDMA=0
```

The Dockerfile pins ROCm, PyTorch, Triton, and LeRobot. This compact submission does not yet include `uv.lock`; base Python dependencies are resolved from `pyproject.toml` during the build. Generating and validating a lock file remains a pre-release task.

### 3.2 Existing ROCm environment

```bash
export PROJECT_ROOT="$PWD"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export PYTHON_BIN=/path/to/rocm/python
export HF_HOME=/path/to/huggingface_cache
export HSA_ENABLE_SDMA=0
```

If the cache is complete, offline mode can be enabled:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

## 4. Obtaining Data and Weights

The external artifact manifest is `artifacts/manifest.json`. After downloading artifacts, the following paths must exist:

```text
artifacts/datasets/fruit_pick_dr_600ep/
artifacts/models/smolvla_fruit_pick_dr_600ep/
artifacts/models/plum_residual_sac_lift/last.pt
```

Download URLs must be filled in before formal release. A `null` URL means the current Git repository supports material and compact-result inspection but cannot independently run model evaluation.

Check the artifacts:

```bash
test -f artifacts/datasets/fruit_pick_dr_600ep/meta/info.json
test -f artifacts/models/smolvla_fruit_pick_dr_600ep/config.json
test -f artifacts/models/smolvla_fruit_pick_dr_600ep/model.safetensors
test -f artifacts/models/plum_residual_sac_lift/last.pt

sha256sum artifacts/models/smolvla_fruit_pick_dr_600ep/model.safetensors
sha256sum artifacts/models/plum_residual_sac_lift/last.pt
```

Expected SHA256 values are listed in the manifest.

## 5. Checks That Do Not Require Weights

### 5.1 Python syntax

```bash
"$PYTHON_BIN" -m compileall -q franka_fruit_pick optimization
```

### 5.2 Regenerate the saved runtime summary

Copy the inputs first to preserve submitted results:

```bash
mkdir -p reproductions/runtime_summary
cp results/runtime/*.json reproductions/runtime_summary/

"$PYTHON_BIN" -m optimization.runtime.summarize_results \
  --results-dir reproductions/runtime_summary
```

Expected `summary.csv` and `summary.md` results:

| Backend | Mean | Speedup | Correctness |
|---|---:|---:|---|
| Eager | 153.81 ms | 1.000x | Baseline |
| HIP Graph | 102.76 ms | 1.497x | Passed with zero error |
| Targeted Compile | 63.86 ms | 2.409x | Numerical mismatch |

### 5.3 Inspect closed-loop and residual results

```bash
sed -n '1,120p' results/closed_loop/hip_graph/summary_100ep.md
sed -n '1,120p' results/closed_loop/targeted_compile/summary_100ep.md
python -c 'import json; d=json.load(open("results/residual_rl/lift_no_gate_100ep.json")); print(d["baseline_success"], d["residual_success"])'
```

## 6. Verify the AMD GPU and Dependencies

```bash
"$PYTHON_BIN" - <<'PY'
import torch
print("torch:", torch.__version__)
print("HIP:", torch.version.hip)
print("GPU:", torch.cuda.get_device_name(0))
assert torch.version.hip is not None
assert torch.cuda.is_available()
PY
```

```bash
"$PYTHON_BIN" - <<'PY'
import genesis, lerobot, torch, torchvision, triton
print("genesis:", genesis.__version__)
print("lerobot:", getattr(lerobot, "__version__", "unknown"))
print("torch:", torch.__version__)
print("torchvision:", torchvision.__version__)
print("triton:", triton.__version__)
PY
```

## 7. Scene Smoke Test

Scene assets are included in the repository:

```bash
xvfb-run -a -s '-screen 0 1280x720x24' \
  "$PYTHON_BIN" franka_fruit_pick/build_scene.py \
  --steps 50 \
  --save-frames
```

This step does not require training data or weights.

## 8. One-Episode HIP Graph Closed Loop

```bash
mkdir -p reproductions/smoke

xvfb-run -a -s '-screen 0 1280x720x24' \
  "$PYTHON_BIN" franka_fruit_pick/eval_policy.py \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --repo-id demo/fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --episodes 1 \
  --seed 9000 \
  --policy-seed 9000 \
  --pick 011_banana \
  --device cuda \
  --inference-backend hip-graph \
  --hip-graph-capture-warmup 3 \
  --measure-inference \
  --results-out reproductions/smoke/banana_1ep.json
```

One episode validates the execution path only; it must not be used to assess the reported success rate.

## 9. Full-Inference Benchmark and Correctness

Use the repository launchers:

```bash
PYTHON_BIN="$PYTHON_BIN" bash scripts/benchmark_rocm_backends.sh
PYTHON_BIN="$PYTHON_BIN" bash scripts/validate_rocm_backends.sh
```

Equivalent low-level benchmark commands are provided for audit and isolated debugging:

```bash
export RUNTIME_REPRO=reproductions/runtime_backends
mkdir -p "$RUNTIME_REPRO"

"$PYTHON_BIN" -m optimization.runtime.benchmark_full_inference \
  --backend eager \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/full_eager.json"

"$PYTHON_BIN" -m optimization.runtime.benchmark_full_inference \
  --backend hip-graph \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/full_hip-graph.json"

"$PYTHON_BIN" -m optimization.runtime.benchmark_full_inference \
  --backend compile \
  --compile-mode max-autotune-no-cudagraphs \
  --matmul-precision high \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/full_compile.json"
```

Strict validation:

```bash
"$PYTHON_BIN" -m optimization.runtime.validate_full_inference \
  --backend hip-graph \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/validation_hip-graph.json"

"$PYTHON_BIN" -m optimization.runtime.validate_full_inference \
  --backend compile \
  --compile-mode max-autotune-no-cudagraphs \
  --matmul-precision high \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --output "$RUNTIME_REPRO/validation_compile.json"

"$PYTHON_BIN" -m optimization.runtime.summarize_results \
  --results-dir "$RUNTIME_REPRO"
```

HIP Graph should pass strict validation with zero maximum error on fixed and changing inputs. Targeted Compile is expected to report `numerical_mismatch`; do not loosen tolerances to relabel it as passing.

## 10. Closed-Loop A/B Reproduction

The launcher evaluates Eager and the selected candidate backend on identical seeds for each fruit, then invokes `summarize_closed_loop_ab.py`:

```bash
# HIP Graph; the report uses seeds 2000–2099
PYTHON_BIN="$PYTHON_BIN" CANDIDATE=hip-graph EPISODES=100 \
  SEED=2000 POLICY_SEED=2000 bash scripts/evaluate_rocm_closed_loop.sh

# Targeted Compile; the report uses seeds 1000–1099
PYTHON_BIN="$PYTHON_BIN" CANDIDATE=targeted-compile EPISODES=100 \
  SEED=1000 POLICY_SEED=1000 bash scripts/evaluate_rocm_closed_loop.sh
```

| Experiment | Seeds | Backends | Matmul precision |
|---|---|---|---|
| HIP Graph | 2000–2099 | eager / hip-graph | — |
| Targeted Compile | 1000–1099 | eager / targeted-compile | highest |

Each fruit runs for 100 episodes:

```text
011_banana
014_lemon
018_plum
```

`eval_policy.py` must receive the same `--seed`, `--policy-seed`, `--episodes 100`, and `--measure-inference`, with a separate `--results-out` for each run. Reference summaries are under `results/closed_loop/`.

## 11. Residual SAC Evaluation

```bash
mkdir -p reproductions/residual_rl

xvfb-run -a -s '-screen 0 1280x720x24' \
  "$PYTHON_BIN" -m franka_fruit_pick.residual_rl.evaluate \
  --policy-path artifacts/models/smolvla_fruit_pick_dr_600ep \
  --residual-checkpoint artifacts/models/plum_residual_sac_lift/last.pt \
  --repo-id demo/fruit_pick_dr_600ep \
  --dataset-root artifacts/datasets/fruit_pick_dr_600ep \
  --episodes 100 \
  --seed 2000 \
  --device cuda \
  --jitter 0.03 \
  --arm-scale 0.015 \
  --finger-scale 0.003 \
  --out reproductions/residual_rl/lift_no_gate_100ep.json
```

The reference exploratory result is 34/100 → 43/100 and has not been independently validated on new seeds.

## 12. Regenerating Data and Training

The [historical training record](../results/training/README.md) distinguishes checkpoint-proven facts, training-time monitoring, and fixed-seed evaluation results.

Training data is not stored in Git. Inspect the complete data-generation entry points:

```bash
"$PYTHON_BIN" franka_fruit_pick/record_dataset.py --help
"$PYTHON_BIN" franka_fruit_pick/aggregate_datasets.py --help
```

The original dataset contains 200 successful episodes per fruit with appearance, camera, initial pose, friction, and mass randomization. The root README provides the complete three-fruit collection command.

### 12.1 SmolVLA fine-tuning

Confirm the dataset metadata:

```bash
test -f artifacts/datasets/fruit_pick_dr_600ep/meta/info.json
```

Inspect the LeRobot command without training:

```bash
DRY_RUN=1 PYTHON_BIN="$PYTHON_BIN" bash scripts/train_smolvla_fruit_pick.sh
```

Start training:

```bash
PYTHON_BIN="$PYTHON_BIN" bash scripts/train_smolvla_fruit_pick.sh
```

The default `POLICY_PATH=lerobot/smolvla_base` requires network access on first use. For offline execution, point `HF_HOME` to a complete cache or set `POLICY_PATH` to a local base/checkpoint directory. Both training launchers write `<OUTPUT_DIR>.launcher.log` and treat a printed internal traceback with exit code zero as failure.

Defaults match the original experiment: 20,000 steps, batch size 128, seed 1000, and a checkpoint every 2,000 steps. The launcher calls `franka_fruit_pick/train_policy.py`, which invokes LeRobot 0.6.0 `lerobot_train`. Expected final checkpoint:

```text
reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model/
```

Confirm output:

```bash
test -f reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model/model.safetensors
```

The full configuration snapshot is `configs/smolvla_train_config.json`. The JSON records experiment parameters; the executable source of truth is the launcher and its Python entry point.

### 12.2 Residual SAC training

This stage requires the dataset and frozen SmolVLA checkpoint. It reads `artifacts/models/smolvla_fruit_pick_dr_600ep/` by default or can use the model reproduced in Section 12.1:

```bash
DRY_RUN=1 PYTHON_BIN="$PYTHON_BIN" \
  POLICY_PATH="$PROJECT_ROOT/reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model" \
  bash scripts/train_residual_sac_lift.sh
```

Start training:

```bash
PYTHON_BIN="$PYTHON_BIN" \
  POLICY_PATH="$PROJECT_ROOT/reproductions/train/smolvla_fruit_pick_dr_600ep/checkpoints/last/pretrained_model" \
  bash scripts/train_residual_sac_lift.sh
```

Defaults are 100,000 steps, 10,000 warmup steps, batch size 256, task mode `lift`, and a checkpoint every 10,000 steps. Expected output:

```text
reproductions/rl/plum_residual_sac/checkpoints/last.pt
reproductions/rl/plum_residual_sac/train_metrics.jsonl
```

The parameter snapshot is `configs/residual_sac_lift_config.json`. Residual SAC uses privileged simulator state and is not a directly deployable vision-only real-robot policy.

The original log records 361 completed episodes, 169 training-time successes, and 45 successes in the final 100 training episodes. These online-training metrics cannot replace the fixed-seed paired evaluation in Section 11.

### 12.3 Post-training validation

Use the Section 10 closed-loop commands for a newly trained SmolVLA model and the Section 11 paired evaluation for residual SAC. Retraining is not expected to produce bitwise-identical weights; compare aggregate success and paired outcome flips on a fixed episode set rather than a single trajectory.

## 13. Nondeterminism

Genesis physics on AMD GPUs is not bitwise deterministic across processes. Even with identical environment and PyTorch seeds, trajectories and termination steps may differ. Therefore:

- do not judge reproduction from one episode;
- compare aggregate success, paired flips, and latency distributions;
- do not require every seed to produce an identical trajectory;
- HIP Graph offline validation should retain zero error;
- Targeted Compile strict numerical mismatch is an expected saved result.

## 14. Acceptance Checklist

- [ ] Documentation, figure, and video links work.
- [ ] Core Python source passes `compileall`.
- [ ] Compact runtime inputs regenerate the summary.
- [ ] `torch.version.hip` is non-null and the AMD GPU is visible.
- [ ] Manifest artifact URLs download successfully and SHA256 values match.
- [ ] The Genesis scene smoke test passes.
- [ ] A one-episode HIP Graph run produces JSON.
- [ ] HIP Graph passes strict zero-error validation.
- [ ] Targeted Compile is labeled as a numerical mismatch.
- [ ] All new output is written under `reproductions/`.

## 15. Related Materials

- [Project README](../README.md)
- [Technical report](TECHNICAL_REPORT.md)
- [Formal results](../results/README.md)
- [Artifact guide](../artifacts/README.md)
- [ROCm runtime](../optimization/runtime/README.md)
- [Residual SAC](../franka_fruit_pick/residual_rl/README.md)
- [Historical training record](../results/training/README.md)
- [English-narrated success/failure video](video/smolvla_success_failure_demo.mp4)
- [Video rebuild notes](video/NARRATION_EN.md)
