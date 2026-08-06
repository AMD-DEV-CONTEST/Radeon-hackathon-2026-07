"""Merge several LeRobot datasets into one aggregated dataset directory.

lerobot's trainer only accepts a *single* dataset -- ``MultiLeRobotDataset`` is
disabled in this version (``make_dataset`` raises ``NotImplementedError`` for a
list of repo ids). So to train on multiple per-object datasets at once
(e.g. banana + lemon + plum), you first merge them into one dataset on disk and
train on that.

This is a thin CLI around ``lerobot.datasets.aggregate.aggregate_datasets``:
it re-indexes episodes/tasks, concatenates data + videos, and rewrites
``info.json`` / ``stats.json`` for the merged dataset. All sources must share
the same ``fps`` / ``robot_type`` / feature schema (only common feature keys
are kept); differing task strings simply become distinct tasks in the result.

Usage:
    uv run python franka_fruit_pick/aggregate_datasets.py \
        --dataset-root datasets/banana_pick_50ep \
        --dataset-root datasets/lemon_pick_50ep \
        --dataset-root datasets/plum_pick_50ep \
        --out datasets/fruit_pick_150ep

Then train on the merged dir:
    uv run python franka_fruit_pick/train_policy.py act \
        --repo-id genesis/fruit_pick_150ep \
        --dataset-root datasets/fruit_pick_150ep
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def _resolve_source(root: str) -> Path:
    """Validate a source dataset dir and return its absolute path."""
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        sys.exit(f"[error] dataset root not found: {path}")
    if not (path / "meta" / "info.json").is_file():
        sys.exit(f"[error] not a LeRobot dataset (missing meta/info.json): {path}")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Aggregate multiple LeRobot datasets into a single dataset directory.",
    )
    ap.add_argument(
        "--dataset-root",
        action="append",
        required=True,
        metavar="DIR",
        help="Source dataset dir (repeat for each dataset to merge; order is preserved).",
    )
    ap.add_argument(
        "--out",
        required=True,
        metavar="DIR",
        help="Output directory for the merged dataset.",
    )
    ap.add_argument(
        "--repo-id",
        action="append",
        default=None,
        metavar="ID",
        help="Optional source repo id label (repeat, one per --dataset-root). "
        "Default: genesis/<source-dir-name>.",
    )
    ap.add_argument(
        "--aggr-repo-id",
        default=None,
        help="Repo id label for the merged dataset. Default: genesis/<out-dir-name>.",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete the output dir first if it already exists.",
    )
    ap.add_argument("--chunk-size", type=int, default=None, help="Max files per chunk (lerobot default if unset).")
    ap.add_argument("--data-files-size-mb", type=float, default=None, help="Max data file size in MB.")
    ap.add_argument("--video-files-size-mb", type=float, default=None, help="Max video file size in MB.")
    ap.add_argument("--dry-run", action="store_true", help="Print the plan and exit without merging.")
    args = ap.parse_args()

    roots = [_resolve_source(r) for r in args.dataset_root]
    if len(roots) < 2:
        sys.exit("[error] need at least two --dataset-root dirs to aggregate.")

    if args.repo_id is not None:
        if len(args.repo_id) != len(roots):
            sys.exit(
                f"[error] got {len(args.repo_id)} --repo-id but {len(roots)} --dataset-root; "
                "provide one --repo-id per dataset (or none to auto-derive)."
            )
        repo_ids = list(args.repo_id)
    else:
        repo_ids = [f"genesis/{p.name}" for p in roots]

    out = Path(args.out).expanduser().resolve()
    aggr_repo_id = args.aggr_repo_id or f"genesis/{out.name}"

    print("[aggregate] merging:")
    for rid, p in zip(repo_ids, roots, strict=True):
        info = json.loads((p / "meta" / "info.json").read_text())
        print(
            f"  - {rid:<28} {p}  "
            f"(episodes={info.get('total_episodes')}, tasks={info.get('total_tasks')}, "
            f"frames={info.get('total_frames')})"
        )
    print(f"[aggregate] output: {aggr_repo_id}  ->  {out}")

    if args.dry_run:
        print("[aggregate] dry-run: nothing written.")
        return

    if out.exists():
        if args.overwrite:
            print(f"[aggregate] --overwrite: removing existing {out}")
            shutil.rmtree(out)
        else:
            sys.exit(f"[error] output dir already exists: {out} (use --overwrite to replace).")

    # Imported lazily so --help / --dry-run don't pay the lerobot import cost.
    from lerobot.datasets.aggregate import aggregate_datasets

    aggregate_datasets(
        repo_ids=repo_ids,
        roots=roots,
        aggr_repo_id=aggr_repo_id,
        aggr_root=out,
        chunk_size=args.chunk_size,
        data_files_size_in_mb=args.data_files_size_mb,
        video_files_size_in_mb=args.video_files_size_mb,
    )

    info_path = out / "meta" / "info.json"
    if info_path.is_file():
        info = json.loads(info_path.read_text())
        print(
            f"[done] merged dataset at {out}\n"
            f"       total_episodes={info.get('total_episodes')} "
            f"total_tasks={info.get('total_tasks')} "
            f"total_frames={info.get('total_frames')}"
        )
        print(
            "[next] train with:\n"
            f"       uv run python franka_fruit_pick/train_policy.py act "
            f"--repo-id {aggr_repo_id} --dataset-root {out}"
        )
    else:
        print(f"[warn] aggregation finished but {info_path} not found; check output.")


if __name__ == "__main__":
    main()
