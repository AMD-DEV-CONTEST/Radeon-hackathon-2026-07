# AMD BiGym 3DGS OpenDM

End-to-end AMD ROCm pipeline for fine-tuning OpenDM DM0.5 on BiGym
`DishwasherUnloadCutleryLong`, running deterministic closed-loop evaluation,
and evaluating the same policy through a 3D Gaussian Splatting kitchen shell.

## Results

The released full checkpoint is
[`wangbin08/DM05-BiGym-CutleryLong-50pct`](https://huggingface.co/wangbin08/DM05-BiGym-CutleryLong-50pct).
Policy quality is measured with seeds `200000-200049`, 20 Hz control and policy,
chunk 16, 10 diffusion steps, execute 8, maximum 800 policy steps and sequence
length 896.

| Visual domain | Success | Scope |
| --- | ---: | --- |
| Native BiGym | 25/50 (50%) | Fixed-seed closed-loop benchmark |
| Public 3DGS kitchen shell | 20/50 (40%) | Same model, seeds and control protocol |

The AMD implementation was validated on one Radeon PRO W7900 (`gfx1100`, 48
GB) with ROCm 7.2.1 and PyTorch 2.8.0 for ROCm. The repository includes the
source patches, strict shell validation, deterministic seed sharding and
machine-readable summaries needed to reproduce the workflow. Exact result
scope is recorded in [`results/benchmark.json`](results/benchmark.json).

The final 10-step strict 3DGS AMD gate completed seed `200009` successfully in
567 control steps and 71 model calls, with 726.58 ms mean model latency. This is
an end-to-end runtime gate, not an additional success-rate estimate.

## AMD contributions

- complete DM0.5 LoRA training and optimizer-preserving resume on `gfx1100`;
- cached LeRobot episode metadata with persistent data workers;
- shape-specific PyTorch TunableOp replay support for rocBLAS/hipBLASLt;
- merged-model inference without a redundant LoRA graph;
- `torch.inference_mode()` and action-identical Action Expert KV workspace
  reuse;
- patched `gsplat==1.4.0` build and runtime for ROCm `gfx1100`;
- strict 3DGS evaluation that never silently falls back to native rendering.

A controlled W7900 DM0.5 software benchmark improved training throughput from
1.244 to 1.548 samples/s (+24.4%). That measurement used ReachTarget to isolate
software throughput; task-success numbers above are exclusively
`DishwasherUnloadCutleryLong`. See
[`docs/training_optimization.md`](docs/training_optimization.md) and
[`docs/inference_optimization.md`](docs/inference_optimization.md).

A second matched sweep on the processed 32-episode CutleryLong workload selected
micro-batch 12 with gradient accumulation 4 (effective batch 48). Micro-batch
16 was rejected because throughput fell from 1.5276 to 1.5202 samples/s while
using more memory.

| AMD W7900 performance snapshot | GPU utilization | Peak VRAM | Throughput / latency |
| --- | ---: | ---: | ---: |
| Training, batch 12 x accumulation 4 | 99.47% | 28.74 GiB | 1.5295 samples/s |
| Inference, merged model, 4 diffusion steps, KV workspace | 67.68% | 12.79 GiB | 438.72 ms per steady policy call |

Training utilization is the mean over two complete steady optimizer steps.
Inference latency excludes four warm-up calls and reports the next 28 calls;
the 4-step row is a performance benchmark and does not replace the 10-step
quality protocol used for the success-rate results above.

## Pipeline

```text
LeRobot v3 demonstrations -> DM0.5 LoRA training -> resumable adapter
                                      |
                                      v
                              safe weight merge
                                      |
                   +------------------+------------------+
                   |                                     |
          native BiGym evaluation            BiGym + 3DGS evaluation
                   |                                     |
                   +------ summary.json + MP4 videos ----+
```

The task contract is fixed throughout the repository:

- RGB observations: head `848x480`, left wrist `640x480`, right wrist
  `640x480`;
- 16D state and absolute action: cumulative floating base, arm joints and two
  grippers;
- prompt: `Unload cutlery from dishwasher to drawer task.`;
- 20 Hz control and policy, chunk 16, 10 diffusion steps, execute 8;
- model sequence length 896, maximum 800 policy steps.

## Repository layout

| Path | Purpose |
| --- | --- |
| `train/` | LeRobot v3 loader and DM0.5 training configuration |
| `eval/` | Native and strict 3DGS closed-loop evaluators |
| `collect/` | Privileged closed-loop data generation and validation |
| `patches/` | Pinned OpenDM runtime and KV-workspace patches |
| `overlays/bigym/` | Self-contained BiGym 3DGS runtime overlay |
| `scripts/setup_amd_runtime.sh` | Pinned source and AMD environment setup |
| `scripts/download_3dgs_shell.py` | Public shell download and PLY verification |
| `scripts/train_cutlery_amd.sh` | Resumable W7900 training entry point |
| `scripts/merge_dm05_lora.py` | Adapter-to-full-model safe merge |
| `scripts/run_amd_eval.sh` | Deterministic native or 3DGS evaluation |

## 1. Prepare the AMD environment

System packages:

```bash
apt-get update
apt-get install -y ffmpeg git libglm-dev patch python3-venv
```

Select a Python 3.12 environment that already contains a working ROCm PyTorch
build. The setup script does not replace PyTorch because the correct wheel is
tied to the installed ROCm image.

```bash
git clone https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm.git \
  /workspace/amd-bigym-3dgs-opendm
cd /workspace/amd-bigym-3dgs-opendm

export VENV=/workspace/amd-bigym-3dgs-opendm/.venv
python3 -m venv --system-site-packages "$VENV"
bash scripts/setup_amd_runtime.sh "$PWD/third_party"
```

The setup pins OpenDM and the AMD 3DGS integration by commit, applies patches
idempotently, builds `gsplat` for `gfx1100`, installs the BiGym overlay and runs
a real ROCm rasterization smoke test. Compatibility headers and the compiler
wrapper stay inside the repository; `/opt/rocm` is not modified.

The official lightweight demo supplies environment and action metadata only;
its recorded actions are not replayed during policy evaluation. Runtime physics
are pinned by the BiGym source commit in `scripts/install_bigym_amd_overlay.sh`.

```bash
cp configs/cutlery_long.env.example .env
set -a
source .env
set +a
```

## 2. Prepare assets

Required assets are stored outside Git:

- base weights `Dexmal/DM05` or the released full checkpoint;
- 32 successful LeRobot v3 `DishwasherUnloadCutleryLong` trajectories;
- one official lightweight BiGym demonstration for environment metadata;
- the public AMD shell
  [`eustance/amd-bigym-3dgs-kitchen-shell`](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell/tree/amd-rocm-w7900d-20260804),
  revision `amd-rocm-w7900d-20260804`.

Download the shell by named revision, resolve it to an immutable commit and
verify every profile-referenced PLY:

```bash
"$PYTHON" scripts/download_3dgs_shell.py \
  --output-dir /data/amd-bigym-3dgs-kitchen-shell
source /data/amd-bigym-3dgs-kitchen-shell/shell.env
```

See [`docs/3dgs_evaluation.md`](docs/3dgs_evaluation.md) for the asset contract.

## 3. Train and merge

The validated recipe uses LoRA rank 32, alpha 16, all linear modules plus the
OpenDM action/time modules, BF16, micro-batch 12, gradient accumulation 4,
effective batch 48, learning rate `5e-4`, 500 warmup steps and 10,000 optimizer
steps. VLM gradient checkpointing is enabled and Action Expert checkpointing is
disabled.

```bash
AMD_GPU_IDS=0 NPROC=1 \
  bash scripts/train_cutlery_amd.sh 2>&1 | tee "$OUTPUT_ROOT/train.log"
```

The launcher resumes the highest complete numeric checkpoint. Every checkpoint
contains adapter, optimizer, scheduler, trainer state and normalization
statistics.

Merge the final adapter into a standalone model:

```bash
"$PYTHON" scripts/merge_dm05_lora.py \
  --opendm-root "$OPENDM_ROOT" \
  --base-model "$BASE_MODEL" \
  --adapter "$OUTPUT_ROOT/dm05-cutlery-long-amd/checkpoint-10000" \
  --output-dir "$MODEL_PATH" \
  --chunk-size 16
```

The merger uses PEFT safe merge, rejects adapter-only tensor names in the final
model and records SHA-256 hashes in `merge_manifest.json`.

## 4. Evaluate

Run one deterministic smoke episode before a formal evaluation:

```bash
NUM_EPISODES=1 SEED_START=200009 AMD_GPU_IDS=0 \
  bash scripts/run_amd_eval.sh native \
  "$MODEL_PATH" "$OFFICIAL_DEMO" "$OUTPUT_ROOT/native-smoke"
```

Run the fixed 50-episode native protocol:

```bash
NUM_EPISODES=50 SEED_START=200000 AMD_GPU_IDS=0 \
  bash scripts/run_amd_eval.sh native \
  "$MODEL_PATH" "$OFFICIAL_DEMO" "$OUTPUT_ROOT/native-50"
```

Run the same policy with the strict public 3DGS shell:

```bash
NUM_EPISODES=50 SEED_START=200000 AMD_GPU_IDS=0 \
  bash scripts/run_amd_eval.sh 3dgs \
  "$MODEL_PATH" "$OFFICIAL_DEMO" "$OUTPUT_ROOT/3dgs-50"
```

`AMD_GPU_IDS` accepts a comma-separated list. Seeds are deterministically
sharded, each process loads one model, and summaries are merged only after every
shard succeeds. MuJoCo remains the physics and success engine; the Gaussian
shell changes RGB observations only.

## 5. Optional HTTP provider

The same optimized policy implements `GET /health` and `POST /process_frame`
for an external simulator-side evaluator. It accepts three ordered RGB frames
and the 16D state, and returns a finite `10x16` action prefix.

```bash
export INFERENCE_HOST=127.0.0.1
export INFERENCE_PORT=7892
bash scripts/serve_http_provider.sh \
  "$MODEL_PATH" \
  wangbin08/DM05-BiGym-CutleryLong-50pct \
  IMMUTABLE_MODEL_REVISION
```

## Validation

```bash
"$PYTHON" scripts/preflight_amd.py --require-training --require-3dgs
python -m compileall -q collect eval inference scripts train
ruff check --select E,F collect eval inference scripts train tests
pytest -q
```

CI runs syntax, shell, protocol and unit checks on every push and pull request.

## License

Repository code is Apache-2.0. OpenDM, BiGym, LeRobot, MuJoCo, DM0.5 weights,
official demonstrations, Gaussian Renderer and the public 3DGS dataset retain
their own licenses and terms. Model weights and large scene assets are not
redistributed in this Git repository.
