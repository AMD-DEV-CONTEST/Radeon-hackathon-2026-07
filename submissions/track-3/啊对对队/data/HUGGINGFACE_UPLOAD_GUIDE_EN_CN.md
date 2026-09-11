# Hugging Face Upload Guide / Hugging Face 上传指南

## Gate / 前置门

**English.** Do not upload from this checkout: it lacks the dataset payload.
Recover the exact remote candidate only, not a 9-episode substitute:

```bash
REMOTE=/workspace/parcel-sorter-opt-v1/outputs/mobile-primitive-dataset-v2
DEST=/path/to/mobile-primitive-dataset-v2
rsync -a --checksum "REMOTE_HOST:${REMOTE}/" "${DEST}/"
```

**中文。** 不得从当前 checkout 上传：它缺少数据集 payload。只恢复精确远端候选，不得用 9-episode 替代物：按上述命令将远端目录复制到本地。

## Hash and LeRobot v3 Validation / 哈希与 LeRobot v3 校验

Compare every recovered `data/chunk-000/file-000.parquet` through `file-006.parquet` with `output_data_sha256` in `evidence/training/pash-primitive-dataset-v2-manifest.json`. Stop on any mismatch.

```bash
cd "$DEST"
sha256sum data/chunk-000/file-*.parquet
test -f meta/info.json && test -f meta/tasks.parquet
find data -name '*.parquet' | wc -l
find videos -type f \( -name '*.mp4' -o -name '*.MP4' \) | wc -l
```

**English.** Confirm LeRobot v3 layout: `data/**/*.parquet`, `videos/**/*.mp4`, and `meta/` must exist; `meta/info.json` must report 7 episodes, 4,557 frames, 30 fps, 43-D state, 20-D action, and 24 task texts. Decode sampled MP4 files and rerun the repository audit.

**中文。** 确认 LeRobot v3 布局：必须有 `data/**/*.parquet`、`videos/**/*.mp4` 和 `meta/`；`meta/info.json` 必须对应 7 episode、4,557 帧、30 fps、43-D state、20-D action 和 24 task texts。抽样解码 MP4，并重新运行仓库审计。

## Publish / 上传

1. **English:** Create a private Hugging Face dataset repository first; upload only after all hashes and metadata pass.
   **中文：** 先创建私有 Hugging Face dataset repository；所有哈希和 metadata 通过后才上传。
2. **English:** Upload the exact directory with `huggingface-cli upload ORG/REPO "$DEST" . --repo-type dataset`.
   **中文：** 使用该命令上传精确目录：`huggingface-cli upload ORG/REPO "$DEST" . --repo-type dataset`。
3. **English:** Publish the audit, manifest, source commit, generation configuration, SHA-256 inventory, license review, and this limitation: simulation-only, no pure-VLA success claim.
   **中文：** 同时发布审计、manifest、源码 commit、生成配置、SHA-256 清单、许可证审阅，以及限制：仅仿真，不主张纯 VLA 成功。

The 96-episode / 11,753-frame ACT corpus is legacy and must be released, if at all, in a separately named repository with its own card and hashes.
