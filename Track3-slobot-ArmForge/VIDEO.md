# Demonstration video

## Technical report presentation (narrated)

| File | Duration (approx.) | Description |
|------|--------------------|-------------|
| [demo/ArmForge-Technical-Report-Presentation.mp4](demo/ArmForge-Technical-Report-Presentation.mp4) | ~4:11 | Narrated 12-slide walkthrough of the technical report (teleop, CoACD, noslip, AMD GPU multi-env throughput, RL path) |

## Episode clips

| File | Duration (approx.) | Description |
|------|--------------------|-------------|
| [demo/episode_000.mp4](demo/episode_000.mp4) | ~80 s | Full recorded cube→disk episode from the ArmForge teleop / LeRobot pipeline |
| [demo/episode_000_trimmed.mp4](demo/episode_000_trimmed.mp4) | ~12 s | Highlight reel of the successful place |

## LeRobot Hub visualizer

Idle-trimmed episode (dataset episode 1):  
https://huggingface.co/spaces/lerobot/visualize_dataset?path=%2Falexis779%2Fso101_cube_disk%2Fepisode_1

Dataset: https://huggingface.co/datasets/alexis779/so101_cube_disk

The narrated presentation covers the report; episode clips are authentic simulation recordings from the submitted pipeline. Use the script below (and the source README) for the full workflow on AMD Radeon / ROCm.

## Judge walkthrough script

1. **Teleop teaching** — run `python armforge/record_lerobot.py --root datasets/so101_cube_disk` and show cube→disk key-action control.
2. **ROCm throughput** — run `python armforge/benchmark_key_action.py --backend amdgpu -B 8` (or `bash scripts/cloud_bootstrap.sh bench`).
3. **Optimize + replay** — `optimize_lerobot.py` then `replay_lerobot.py` on episode 0.
4. **Dataset compatibility** — point at `meta/info.json` / LeRobot-shaped layout and the Docker ROCm path.

## Source

Clips produced with the dedicated repository: https://github.com/alexis779/slobot-armforge
