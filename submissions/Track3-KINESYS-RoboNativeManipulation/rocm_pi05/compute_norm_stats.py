"""Compute pi05 normalization statistics for a LeRobot dataset (self-contained).

Reads the dataset's parquet store through the lerobot interface
(``LeRobotDataset.hf_dataset`` — its columns carry no image keys, so reading the
state/action columns never decodes video) and computes full-table per-frame
mean/std/q01/q99 for ``state`` and ``actions`` with openpi's ``RunningStats``.

State and actions share one per-frame distribution — the same per-frame statistics
as lerobot's own ``compute_episode_stats`` (the function behind ``meta/stats.json``).
mean/std/q01/q99 are all recomputed here rather than copied from ``meta/stats.json``,
which also sidesteps lerobot's per-episode count-weighted quantile aggregation
(``aggregate_feature_stats``) — not a true full-table quantile.

Run once before training, then pass the result to ``train_jax.py``
via ``--norm-stats``. Only three dataset facts are needed: the on-disk LeRobot v3.0
directory, and the state/action column names.

Usage:
  python3 compute_norm_stats.py \
      --data-dir ~/BiGym_Dev/data/bigym_plus/cupboards_close_all \
      --output-dir ./assets/cupboards_close_all
  # then train (same dataset dir):
  python3 train_jax.py ... --norm-stats ./assets/cupboards_close_all

The previous chunked-scan path (action_horizon chunks with repeat-last padding,
which decoded every video frame and biased actions stats toward end-of-episode
poses) has been removed in favor of this single per-frame path. It is what the
trainers consume; camera/model config is irrelevant to computing state/action
statistics.
"""

import argparse
import pathlib

import numpy as np

import lerobot.datasets.lerobot_dataset as lerobot_dataset
import openpi.shared.normalize as _normalize


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute pi05 norm_stats (mean/std/q01/q99) for a LeRobot dataset, "
        "reading parquet via the lerobot interface (no video decode)."
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Local LeRobot Dataset v3.0 directory (contains meta/, data/, videos/).",
    )
    parser.add_argument(
        "--state-source",
        default="observation.state",
        help="Parquet column name for the state (default: observation.state).",
    )
    parser.add_argument(
        "--action-source",
        default="action",
        help="Parquet column name for the action (default: action).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write norm_stats.json into.",
    )
    args = parser.parse_args()

    output_dir = pathlib.Path(args.output_dir)
    # The dataset is loaded from the local filesystem path in --data-dir: lerobot reads the
    # parquet store and metadata straight from that directory, fully offline (no Hugging Face
    # Hub, no network). That path is the only thing that locates the data; lerobot's constructor
    # also requires a placeholder string as its first argument, but it takes no part in locating
    # or fetching the dataset.
    ds = lerobot_dataset.LeRobotDataset(
        f"local/{pathlib.Path(args.data_dir).name}",  # required placeholder, not a locator
        root=args.data_dir,
    )
    # hf_dataset is a HuggingFace Dataset over the parquet store; it has no image columns
    # (videos live elsewhere), so reading state/action columns never decodes video.
    hfd = ds.hf_dataset

    norm_stats = {}
    for out_key, src_key in [("state", args.state_source), ("actions", args.action_source)]:
        arr = np.asarray(hfd[src_key], dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        rs = _normalize.RunningStats()
        for i in range(0, len(arr), 2048):  # chunked update keeps peak memory bounded
            rs.update(arr[i:i + 2048])
        norm_stats[out_key] = rs.get_statistics()

    _normalize.save(output_dir, norm_stats)
    out_file = output_dir / "norm_stats.json"
    print(f"Wrote norm_stats to {out_file}")
    print("Pass it to train_jax.py via --norm-stats.")


if __name__ == "__main__":
    main()
