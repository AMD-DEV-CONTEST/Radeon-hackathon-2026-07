# Data / 数据

This repository does not contain Parquet files, camera videos, or dataset archives. The completed 2,800-update SmolVLA run used 7 episodes and 4,557 frames with a 43-D state, 20-D action, and 24 task texts. Only its manifest, audit, training log, and hashes remain in `evidence/training/`; the original payload and checkpoint are no longer available locally or on the Radeon host.

本仓库不上传 Parquet、相机视频或数据集压缩包。已完成的 2,800-update SmolVLA 训练使用 7 个 episode、4,557 帧、43-D state、20-D action 和 24 条 task text。目前只保留 `evidence/training/` 中的 manifest、审计、训练日志和哈希；原始数据与对应 checkpoint 已不在本地或 Radeon 主机。

## Generate a fresh LeRobot dataset / 重新生成 LeRobot 数据集

The generation chain is code-complete: `collect_mobile_suction_dataset_rocm.py` reads an episode plan, calls `evaluate_mobile_suction_lift_rocm.py`, keeps failure records, and merges only verified successful shards. `dataset.py` writes synchronized overhead and left-wrist RGB-D, state, action, task, and episode metadata.

```bash
python scripts/collect_mobile_suction_dataset_rocm.py \
  --config configs/mobile_suction_collection_v1.json \
  --output outputs/mobile-suction-collection \
  --backend rocm --wrist-rgbd

python scripts/audit_dataset.py \
  --dataset-root outputs/mobile-suction-collection/lerobot_dataset \
  --require-depth-rgb \
  --output outputs/mobile-suction-collection/dataset-audit.json
```

| File | Responsibility |
| --- | --- |
| `configs/mobile_suction_collection_v1.json` | Episode parameters and object profiles |
| `scripts/collect_mobile_suction_dataset_rocm.py` | Campaign control, success filtering, and shard merge |
| `scripts/evaluate_mobile_suction_lift_rocm.py` | Simulation rollout and per-episode recording |
| `src/parcel_sorter/dataset.py` | LeRobot schema and writer implementation |
| `scripts/audit_dataset.py` | Metadata and RGB-D schema validation |
| `scripts/build_dataset_split.py` | Deterministic train/validation split generation |

A separate local success set contains 7 episodes and 6,454 frames with a 43-D state, 19-D action, and overhead plus left-wrist RGB-D. It is not uploaded and was not used by the recorded 2,800-update checkpoint.

另有一套仅保存在本地的成功轨迹集，共 7 个 episode、6,454 帧、43-D state、19-D action，以及全景和左腕 RGB-D。该数据集不上传，也不是上述 2,800-update checkpoint 的训练数据。
