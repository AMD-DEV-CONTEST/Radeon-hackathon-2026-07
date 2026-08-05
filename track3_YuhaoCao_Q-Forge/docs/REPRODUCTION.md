# Reproduction Guide

This guide separates a short evaluator check from the full training pipeline. The
reported study was run with Python 3.11 on one AMD Radeon `gfx1100` GPU with 48 GiB
VRAM. Commands assume the repository root as the current directory.

## 1. Required upstream components

Install compatible versions of:

- ROCm-capable PyTorch 2.8 (`2.8.0+rocm6.4` in the tested environment);
- LeRobot 0.4.1 with SmolVLA;
- RLinf 0.3.0;
- LIBERO-sim and its assets/demonstrations;
- packages declared by `pyproject.toml`.

Keep upstream repositories outside Q-Forge and export their paths. The exact AMD
wheel constraints are in `constraints/torch-rocm64.txt`.

```bash
python -m pip install -e .
export PYTHONPATH=/path/to/LIBERO-sim${PYTHONPATH:+:$PYTHONPATH}
export LIBERO_CONFIG_PATH="$PWD/configs/libero"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export TOKENIZERS_PARALLELISM=false
export SMOLVLA_ATTENTION_BACKEND=sdpa
```

Do not copy author-specific `/workspace/...` paths from historical notes. Substitute
paths on the evaluator's machine.

## 2. Verify AMD acceleration

```bash
rocm-smi --showproductname --showmeminfo vram --showdriverversion
python scripts/verify_rocm_torch.py
```

Expected properties are `torch.cuda.is_available() == True`, HIP rather than CUDA,
and a `gfx1100` device in the original environment.

## 3. Run tests

```bash
python -m pytest -q
```

Tests that import RLinf/LeRobot require those upstream packages. Core tensor,
critic, guidance, selection, paired-summary, and data-protocol tests are under
`tests/`.

## 4. Artifact layout

Large artifacts are generated locally and excluded from Git:

```text
outputs/native_lerobot_smolvla_task7_20d_20k/
  checkpoints/020000/pretrained_model/        # 20-demo Base

data/collected_pickle/
  task7_native20d20k_rollouts300_perturbed_v1/ # 300 automatic rollouts

data/qvgm_buffers/
  task7_native20d20k_q3_rollouts300_v1/        # feature/policy caches

checkpoints/qvgm_critic/
  task7_native20d20k_q3_rollouts300_mc_v1/
  task7_native20d20k_q3_rollouts300_calql_v1/

checkpoints/qvgm_policy/
  task7_native20d20k_q3_rollouts300_residual_v1/
```

## 5. Short paired video check

With Base and critic artifacts present, record reset state 1 twice:

```bash
BASE=outputs/native_lerobot_smolvla_task7_20d_20k/checkpoints/020000/pretrained_model
CRITIC=checkpoints/qvgm_critic/task7_native20d20k_q3_rollouts300_calql_v1/checkpoint-final.pt

python scripts/run_smolvla_libero_closed_loop.py \
  --task-id 7 --task-reset-state-id 1 --seed 2001 \
  --max-steps 240 --action-steps 5 \
  --model-path "$BASE" \
  --output-dir outputs/demo/base_state1

python scripts/run_smolvla_libero_closed_loop.py \
  --task-id 7 --task-reset-state-id 1 --seed 2001 \
  --max-steps 240 --action-steps 5 \
  --model-path "$BASE" --critic-checkpoint "$CRITIC" \
  --guidance-steps 10 --guidance-step-size 0.02 \
  --guidance-max-delta 0.05 \
  --guidance-optimize-prefix-steps 5 \
  --guidance-optimize-action-dims 7 \
  --output-dir outputs/demo/guidance_state1
```

Each directory receives `closed_loop_metrics.json` and an MP4. Under the frozen
protocol state 1 is a Base failure and Q-guidance success.

## 6. Full primary pipeline

The resumable wrapper is:

```bash
./scripts/run_task7_native20d_qvgm_rollouts300.sh
```

The explicit stages follow.

### 6.1 Fine-tune the 20-demo Base

```bash
./scripts/run_native_lerobot_task7_20d_sft.sh
```

Configuration: 20,000 steps, batch 64, BF16, seed 1000, frozen VLM, and trained
Action Expert. Inspect the script and YAML paths before launching on a new machine.

### 6.2 Collect 300 perturbed policy rollouts

```bash
python scripts/collect_task7_critic_diverse.py \
  --model-path outputs/native_lerobot_smolvla_task7_20d_20k/checkpoints/020000/pretrained_model \
  --output-dir data/collected_pickle/task7_native20d20k_rollouts300_perturbed_v1 \
  --states 0-49 --failure-states 0-49 \
  --perturb-probability 0.5 --action-steps 5 \
  --max-steps 240 --seed 3300
```

Validate episode count, transition count, and mixed outcomes before critic training:

```bash
python scripts/summarize_diverse_collection.py --help
python scripts/validate_task7_rollouts50.py --help
```

### 6.3 Cache frozen state features

```bash
python scripts/cache_qvgm_features.py \
  --pickle-dir data/collected_pickle/task7_native20d20k_rollouts300_perturbed_v1 \
  --output-dir data/qvgm_buffers/task7_native20d20k_q3_rollouts300_v1 \
  --model-path outputs/native_lerobot_smolvla_task7_20d_20k/checkpoints/020000/pretrained_model \
  --horizon 5 --gamma 0.99 --feature-dim 512 --projection-seed 1000
```

Also create the policy-observation cache required for residual distillation with
`scripts/cache_qvgm_policy_observations.py`.

#### Optional: use the learned 2048-dimensional RL-token representation

The primary 300-rollout result above uses the fixed 512-dimensional projection.
The repository also supports a separate RLT path. First cache the frozen SmolVLA
prefix tokens:

```bash
python scripts/cache_smolvla_prefix_tokens.py \
  --pickle-dir data/collected_pickle/task7_native20d20k_rollouts300_perturbed_v1 \
  --output-dir data/qvgm_buffers/task7_native20d20k_rollouts300_prefix_tokens \
  --model-path outputs/native_lerobot_smolvla_task7_20d_20k/checkpoints/020000/pretrained_model \
  --batch-size 8
```

Pretrain the two-layer, eight-head RLT encoder-decoder by prefix reconstruction:

```bash
python scripts/train_rlt_prefix_autoencoder.py \
  --token-dir data/qvgm_buffers/task7_native20d20k_rollouts300_prefix_tokens \
  --output-dir checkpoints/rlt/task7_native20d20k_rollouts300_rlt2048 \
  --steps 5000 --batch-size 4 --learning-rate 2.5e-5 \
  --embed-dim 2048 --num-layers 2 --num-heads 8 --mlp-ratio 4 \
  --validation-states 40,41,42,43,44,45,46,47,48,49
```

Then build a separate feature cache with the frozen RLT encoder:

```bash
python scripts/cache_qvgm_features.py \
  --pickle-dir data/collected_pickle/task7_native20d20k_rollouts300_perturbed_v1 \
  --output-dir data/qvgm_buffers/task7_native20d20k_q3_rollouts300_rlt2048_v1 \
  --model-path outputs/native_lerobot_smolvla_task7_20d_20k/checkpoints/020000/pretrained_model \
  --horizon 5 --gamma 0.99 \
  --rlt-checkpoint checkpoints/rlt/task7_native20d20k_rollouts300_rlt2048/checkpoint-final.pt \
  --prefix-token-dir data/qvgm_buffers/task7_native20d20k_rollouts300_prefix_tokens \
  --batch-size 8
```

The critic scripts infer `z_dim=2048` from this cache. In this repository the RLT
encoder is frozen during critic training; this is distinct from the Q-VGM paper's
joint encoder-and-critic training with a continuing reconstruction regularizer.

### 6.4 Train MC then TD/Cal-QL critics

Use the CLI help and wrapper for the complete path values:

```bash
python scripts/train_qvgm_critic_mc.py --help
python scripts/train_qvgm_critic_td.py --help
```

Primary hyperparameters:

```text
MC:       5000 steps, batch 256, LR 3e-4, hidden 512, ensemble 5
TD/CalQL: 2000 steps, batch 256, LR 1e-4, tau 0.005
           cql_alpha 0.05, 10 random actions, local noise 0.05
split:     states 0-39 train, states 40-49 validation
```

Expected final gate values are recorded in `results/critic_and_guidance.json`.

### 6.5 Select guidance configuration

```bash
python scripts/run_q_guidance_grid.py \
  --cache data/qvgm_buffers/task7_native20d20k_q3_rollouts300_v1/feature_cache.pt \
  --manifest data/qvgm_buffers/task7_native20d20k_q3_rollouts300_v1/feature_cache_manifest.json \
  --checkpoint-glob 'checkpoints/qvgm_critic/task7_native20d20k_q3_rollouts300_calql_v1/checkpoint-final.pt' \
  --output-dir outputs/qforge_300p/guidance_grid \
  --steps 5,10 --step-sizes 0.005,0.01,0.02 \
  --max-deltas 0.02,0.05 \
  --validation-states 40,41,42,43,44,45,46,47,48,49 \
  --batch-size 512
```

Expected: 12/12 eligible; top configuration `10 / 0.02 / 0.05`.

### 6.6 Train the optional residual policy

```bash
python scripts/train_qvgm_residual_velocity.py \
  --config configs/experiments/task7_native20d20k_q3_rollouts300_residual.yaml
```

This is an evaluated alternative, not the primary Q-Forge inference method.

### 6.7 Run paired evaluation

Run Base, Q selection, Q-guidance, and residual with states 0–49, seed 2001,
240 maximum steps, and 5 actions per replan. The primary Q-guidance command is in
the root README. Summarize paired outcomes with:

```bash
python scripts/summarize_paired_300p.py \
  --base-dir outputs/qforge_300p/base_seed2001 \
  --candidate-dir outputs/qforge_300p/q_guidance_seed2001 \
  --method Q-guidance
```

Expected primary result: Base `21/50`; Q-guidance `34/50`; 19 failure-to-success,
6 success-to-failure; exact two-sided McNemar `p=0.014633298`.

## 7. Attention benchmark

```bash
python scripts/benchmark_attention_fa_vs_sdpa.py --out outputs/attention_ck.json
PYTHONPATH=/path/to/flash-attention \
FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE \
python scripts/benchmark_attention_fa_vs_sdpa.py \
  --merge-into outputs/attention_ck.json --out outputs/attention_all.json
python scripts/validate_attention_backend.py --out outputs/attention_validation.json
python scripts/plot_attention_bench.py
```

Compile and test the CK wheel for the evaluator's exact Python/PyTorch/ROCm stack;
binary wheels are intentionally not committed.

## 8. Reproducibility notes

- The sweep reseeds PyTorch, all GPU RNGs, and NumPy before each episode.
- Critic construction preserves RNG state in the single-episode recorder, keeping
  Base and guided policy flow noise paired.
- All reported action arrays are finite.
- Use the exact reset-state and seed protocol; aggregate success alone loses the
  paired evidence.
- The repository's compact JSON files are evidence summaries, not substitutes for
  per-reset metrics when independently recomputing statistics.
