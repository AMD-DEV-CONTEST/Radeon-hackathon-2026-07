# Normalization Statistics (norm_stats)

π05 normalizes the proprioceptive state input and action targets during both training and inference. The normalization statistics are computed on **training data**, stored together with the checkpoint, and loaded as-is during inference. In this repository, the normalization statistics are computed by the self-contained script `compute_norm_stats.py` in the root directory — **pure command line, no need to modify `src/openpi/training/config.py`**.

## Computation

```bash
python3 compute_norm_stats.py \
    --data-dir /path/to/lerobot_dataset \
    --output-dir ./assets/<dataset_name>
```

- Only `--data-dir` (a local LeRobot Dataset v3.0 directory containing `meta/` and `data/`) and `--output-dir` are required.
- Via the lerobot interface, it **reads the state / action columns of the parquet files offline without decoding videos**, computing `mean / std / q01 / q99` frame-by-frame across the entire table.
- `--state-source` (default `observation.state`) and `--action-source` (default `action`) can be overridden when the dataset column names differ.
- Output: `./assets/<dataset_name>/norm_stats.json`, with keys `state` and `actions`, each being `mean / std / q01 / q99` arrays sized to the **robot's true dimensions**.

## Key Constraints

- **Normalization is performed before zero-padding to `--model-action-dim` (default 32)**, so the dimensions in `norm_stats.json` are the robot's true action dimensions (e.g., 16 for BiGym), not the padded 32.
- **Training and inference must use the same norm_stats.** A checkpoint trained with `train_jax.py --norm-stats ./assets/<dataset_name>` stores that `norm_stats.json` into `checkpoints/<config>/<exp>/<step>/assets/<asset_id>/`; `inference_server.py` loads it automatically from `--checkpoint-dir` without needing to specify it separately.
- After dataset changes (adding/removing episodes, changing action dimensions), you must recompute, otherwise the training/inference normalization will not match the data distribution.
- The `action_dim` / `action_horizon` / camera order of the training `Pi0Config` must be consistent with inference; normalization only handles the scale of state/action and does not replace these consistency requirements (see [README](../README.md) §Feature 1/Feature 2).

## Position in the Workflow

The complete training/inference workflow is described in [README](../README.md) (Step 1: compute statistics → Step 2: train → Step 3: inference) and [`amd_rocm_jax.md`](amd_rocm_jax.md) §2.2.
