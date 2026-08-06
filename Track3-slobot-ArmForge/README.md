# Track 3 — ArmForge (slobot)

**ArmForge** is a ROCm-native SO-ARM-101 cube→disk teleop and LeRobot-shaped dataset pipeline on [Genesis](https://github.com/Genesis-Embodied-AI/Genesis).

| Deliverable | Location |
|-------------|----------|
| Dedicated source code | https://github.com/alexis779/slobot-armforge |
| Technical report | [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md) / [ArmForge-Technical-Report.pdf](ArmForge-Technical-Report.pdf) |
| Demo video notes | [VIDEO.md](VIDEO.md) |
| Report presentation (narrated) | [demo/ArmForge-Technical-Report-Presentation.mp4](demo/ArmForge-Technical-Report-Presentation.mp4) (~4:11) |
| Demo clips | [demo/](demo/) |
| Throughput snapshot | [benchmark/key_action_bench_compare.json](benchmark/key_action_bench_compare.json) |
| LeRobot dataset (Hub) | https://huggingface.co/datasets/alexis779/so101_cube_disk |
| LeRobot episode visualizer (idle-trimmed ep. 1) | https://huggingface.co/spaces/lerobot/visualize_dataset?path=%2Falexis779%2Fso101_cube_disk%2Fepisode_1 |
| ROCm Docker | https://github.com/alexis779/slobot-armforge/blob/main/docker/Dockerfile |

## Reproducibility

Following these steps should let evaluators reproduce the submitted teleop→dataset→replay→bench path.

### 1. Environment setup

```bash
git clone https://github.com/alexis779/slobot-armforge.git
cd slobot-armforge
```

**Option A — AMD ROCm Docker (recommended on Radeon / AMD Developer Cloud):**

```bash
docker build -f docker/Dockerfile -t slobot-armforge:rocm7.2.1 .
bash scripts/cloud_bootstrap.sh          # interactive GPU shell
# or
bash scripts/cloud_bootstrap.sh bench    # key-action throughput on amdgpu
```

**Option B — local `uv` (Python 3.12):**

```bash
uv sync
# Install a ROCm PyTorch build when targeting AMD GPUs
# See docs/AMD_DEVELOPER_CLOUD.md
```

Dependencies are declared in `pyproject.toml`. Cloud VM notes: `docs/AMD_DEVELOPER_CLOUD.md`.

### 2. Execution / usage

```bash
# Teleop + LeRobot-shaped dataset (key-action, 14-D multi-hot)
python armforge/record_lerobot.py --root datasets/so101_cube_disk

# Drop idle teleop frames and verify success
python armforge/optimize_lerobot.py --root datasets/so101_cube_disk --episode 0 --backend cpu

# Replay a recorded episode
python armforge/replay_lerobot.py --root datasets/so101_cube_disk --episode 0

# Parallel key-action throughput (use amdgpu on Radeon)
python armforge/benchmark_key_action.py --backend amdgpu -B 8
# Headless cloud VMs:
xvfb-run -a python armforge/benchmark_key_action.py --backend amdgpu -B 8
```

On AMD hardware, `--backend amdgpu` selects Genesis `gs.amdgpu`. Cameras use the Genesis rasterizer on ROCm (Madrona remains CUDA-only).

### 3. Expected artifacts

- Episode NPZ / video under `datasets/so101_cube_disk/`
- Dataset meta compatible with a LeRobot-shaped schema (`meta/info.json`)
- Benchmark JSON (env-steps/s, success rate) from `benchmark_key_action.py`
- Public Hub dataset: https://huggingface.co/datasets/alexis779/so101_cube_disk

### 4. Demo media in this PR

- Full episode: [demo/episode_000.mp4](demo/episode_000.mp4) (~80 s)
- Trimmed highlight: [demo/episode_000_trimmed.mp4](demo/episode_000_trimmed.mp4) (~12 s)
- Interactive LeRobot visualizer (episode 1 = idle-trimmed): https://huggingface.co/spaces/lerobot/visualize_dataset?path=%2Falexis779%2Fso101_cube_disk%2Fepisode_1

See [VIDEO.md](VIDEO.md) for the judge walkthrough script.

## Team

**slobot**

- **Alexis D** (@alexis779) — system design, Genesis/ROCm pipeline, teleop→LeRobot tooling, benchmarks, documentation

## License

Source code: Apache-2.0 (see dedicated repository).
